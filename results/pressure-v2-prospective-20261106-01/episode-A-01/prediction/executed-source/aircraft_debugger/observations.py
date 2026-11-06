"""Strict recording/replay boundary for the selected FlightGear observations.

The allowlist describes twelve model properties, not private interventions or
diagnostic conclusions. JSON Lines recordings contain one independent poll per
line. Polls are non-atomic and retain each reading's simulator and local times.
No file other than the explicitly supplied observation path is opened by replay.

This validates structure and declared channel provenance. It cannot establish
that an otherwise well-formed value actually came from FlightGear. Simulator
time can pause or reset; those are analysis conditions, not malformed recordings.
"""

from __future__ import annotations

from collections.abc import Iterator
import json
import math
from pathlib import Path
import re
from typing import TextIO

from .flightgear import PropertySpec, TelemetrySnapshot


CHANNELS = {
    "aircraft": PropertySpec("/sim/aircraft", kind="string"),
    "sim_time": PropertySpec("/sim/time/elapsed-sec", unit="s"),
    "paused": PropertySpec("/sim/freeze/master", kind="bool"),
    "altitude": PropertySpec("/position/altitude-ft", unit="ft"),
    "airspeed": PropertySpec("/velocities/airspeed-kt", unit="kt"),
    "engine_1_n1": PropertySpec("/engines/engine[0]/n1-actual", unit="%"),
    "engine_2_n1": PropertySpec("/engines/engine[1]/n1-actual", unit="%"),
    "generator_2_voltage": PropertySpec("/systems/electrical/sources/idg-2/output-volt", unit="V"),
    "ac_bus_1": PropertySpec("/systems/electrical/bus/ac-1", unit="V"),
    "ac_bus_2": PropertySpec("/systems/electrical/bus/ac-2", unit="V"),
    "blue_pressure": PropertySpec("/systems/hydraulic/blue-psi", unit="psi"),
    "blue_quantity": PropertySpec("/systems/hydraulic/blue-qty", unit="raw model quantity"),
}

# Preserve the validation allowlist even if a caller edits its polling selection.
_CHANNEL_SPECS = dict(CHANNELS)
_RECORD_FIELDS = frozenset({
    "schema_version", "sample_index", "poll_started_monotonic_s", "readings",
    "connected", "complete", "received_monotonic_s",
})
_READING_FIELDS = frozenset({
    "path", "value", "valid", "error", "sim_time_s", "received_monotonic_s",
    "reachable", "unit",
})
_ERROR_CODES = frozenset({
    "missing_property", "response_too_large", "malformed_json", "malformed_property",
    "property_path_mismatch", "missing_value", "invalid_value", "invalid_timestamp",
    "timeout", "connection_error",
})
_MAX_LINE_BYTES = 65_536


class ObservationFormatError(ValueError):
    """An observation violates the public schema or replay sequence."""


def _fields(value: object, expected: frozenset[str], label: str) -> dict:
    if not isinstance(value, dict):
        raise ObservationFormatError(f"{label} must be an object")
    missing = expected - value.keys()
    extra = value.keys() - expected
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing fields {sorted(missing)!r}")
        if extra:
            details.append(f"unexpected fields {sorted(extra, key=repr)!r}")
        raise ObservationFormatError(f"{label}: {'; '.join(details)}")
    return value


def _number(value: object, label: str, *, nonnegative: bool = False) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ObservationFormatError(f"{label} must be a finite JSON number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ObservationFormatError(f"{label} must be finite")
    if nonnegative and value < 0:
        raise ObservationFormatError(f"{label} must be nonnegative")
    return value


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise ObservationFormatError(f"{label} must be a JSON boolean")
    return value


def validate_observation(record: object) -> dict:
    """Validate one record without dropping fields, coercion or source access.

    Missing channels may be represented by omission or an explicit invalid
    reading. They cannot coexist with ``complete=True``. Error strings are
    transport codes, rather than free text that could contain a hidden label.
    Cross-record ordering is additionally checked by ``iter_observations``.
    """
    record = _fields(record, _RECORD_FIELDS, "observation")
    if type(record["schema_version"]) is not int or record["schema_version"] != 1:
        raise ObservationFormatError("schema_version must be integer 1")
    if type(record["sample_index"]) is not int or record["sample_index"] < 0:
        raise ObservationFormatError("sample_index must be a nonnegative integer")
    started = _number(record["poll_started_monotonic_s"], "poll_started_monotonic_s", nonnegative=True)
    received = _number(record["received_monotonic_s"], "received_monotonic_s", nonnegative=True)
    if received < started:
        raise ObservationFormatError("received_monotonic_s precedes poll_started_monotonic_s")
    connected = _boolean(record["connected"], "connected")
    complete = _boolean(record["complete"], "complete")
    readings = record["readings"]
    if not isinstance(readings, dict):
        raise ObservationFormatError("readings must be an object")
    unknown = readings.keys() - _CHANNEL_SPECS.keys()
    if unknown:
        raise ObservationFormatError(f"readings contains unknown channels {sorted(unknown, key=repr)!r}")

    for name, reading in readings.items():
        label = f"readings.{name}"
        spec = _CHANNEL_SPECS[name]
        reading = _fields(reading, _READING_FIELDS, label)
        if reading["path"] != spec.path:
            raise ObservationFormatError(f"{label}.path must equal {spec.path!r}")
        if reading["unit"] != spec.unit:
            raise ObservationFormatError(f"{label}.unit must equal {spec.unit!r}")
        valid = _boolean(reading["valid"], f"{label}.valid")
        reachable = _boolean(reading["reachable"], f"{label}.reachable")
        local_time = _number(reading["received_monotonic_s"], f"{label}.received_monotonic_s", nonnegative=True)
        if not started <= local_time <= received:
            raise ObservationFormatError(f"{label}.received_monotonic_s must fall within this poll")

        if valid:
            if reading["error"] is not None:
                raise ObservationFormatError(f"{label}: valid reading must have error=null")
            if not reachable:
                raise ObservationFormatError(f"{label}: valid reading must be reachable")
            value = reading["value"]
            if spec.kind == "number":
                _number(value, f"{label}.value")
            elif spec.kind == "bool":
                _boolean(value, f"{label}.value")
            elif (
                not isinstance(value, str)
                or len(value) > 256
                or any(ord(character) < 32 or ord(character) == 127 for character in value)
            ):
                raise ObservationFormatError(f"{label}.value must be text of at most 256 characters without control characters")
            if reading["sim_time_s"] is not None:
                _number(reading["sim_time_s"], f"{label}.sim_time_s", nonnegative=True)
        else:
            if reading["value"] is not None:
                raise ObservationFormatError(f"{label}: invalid reading must have value=null")
            if reading["sim_time_s"] is not None:
                raise ObservationFormatError(f"{label}: invalid reading must have sim_time_s=null")
            error = reading["error"]
            if not isinstance(error, str) or not (
                error in _ERROR_CODES or (re.fullmatch(r"http_[1-5][0-9]{2}", error) and error != "http_200")
            ):
                raise ObservationFormatError(f"{label}.error must be a supported transport error code")
            if not reachable and error not in ("timeout", "connection_error"):
                raise ObservationFormatError(f"{label}: {error} requires a reachable HTTP server")

    if connected != any(reading["reachable"] for reading in readings.values()):
        raise ObservationFormatError("connected must match whether any selected reading is reachable")
    expected_complete = readings.keys() == _CHANNEL_SPECS.keys() and all(
        reading["valid"] for reading in readings.values()
    )
    if complete != expected_complete:
        raise ObservationFormatError("complete must be true exactly when all 12 canonical channels are present and valid")
    return record


def observation_record(
    snapshot: TelemetrySnapshot, sample_index: int, poll_started_monotonic_s: float
) -> dict:
    """Convert a transport snapshot into the public, versioned recording schema."""
    record = snapshot.to_dict()
    record.update(
        schema_version=1,
        sample_index=sample_index,
        poll_started_monotonic_s=poll_started_monotonic_s,
    )
    return validate_observation(record)


def write_observation(stream: TextIO, record: dict) -> None:
    """Validate before writing one JSON line; never silently remove private fields.

    Sequence ordering belongs to the recorder and is checked again during replay.
    This function does not inspect an output directory or any sibling artifact.
    """
    validate_observation(record)
    encoded = json.dumps(record, allow_nan=False, ensure_ascii=True, separators=(",", ":"))
    if len(encoded) > _MAX_LINE_BYTES:
        raise ObservationFormatError("observation exceeds the maximum JSON line length")
    stream.write(encoded + "\n")
    stream.flush()


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ObservationFormatError(f"duplicate JSON field {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ObservationFormatError(f"non-finite JSON constant {value!r} is not allowed")


def iter_observations(path: Path) -> Iterator[dict]:
    """Replay only the requested JSON Lines file, with actionable line failures.

    Sample indices must increase strictly, although gaps are allowed. Local
    poll and receipt times must not move backwards; equal local times are
    permitted at clock resolution limits. Simulator-time resets remain visible
    to the analyzer. Ordering state is bounded to one time per selected channel.
    """
    path = Path(path)
    previous_index = -1
    previous_started = -1.0
    previous_received = -1.0
    previous_channel_times: dict[str, int | float] = {}
    # Decode one bounded line at a time so malformed UTF-8 reports its own line,
    # rather than the earlier line whose text-reader buffer happened to load it.
    with path.open("rb") as stream:
        line_number = 0
        while True:
            line_number += 1
            try:
                line = stream.readline(_MAX_LINE_BYTES + 2)
                if not line:
                    return
                if len(line.rstrip(b"\r\n")) > _MAX_LINE_BYTES:
                    raise ObservationFormatError("observation exceeds the maximum JSON line length")
                record = validate_observation(json.loads(
                    line.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant
                ))
                if record["sample_index"] <= previous_index:
                    raise ObservationFormatError("sample_index must increase strictly across records")
                if record["poll_started_monotonic_s"] < previous_started:
                    raise ObservationFormatError("poll_started_monotonic_s moved backwards")
                if record["received_monotonic_s"] < previous_received:
                    raise ObservationFormatError("received_monotonic_s moved backwards")
                for name, reading in record["readings"].items():
                    if reading["received_monotonic_s"] < previous_channel_times.get(name, -1.0):
                        raise ObservationFormatError(f"readings.{name}.received_monotonic_s moved backwards")
                    previous_channel_times[name] = reading["received_monotonic_s"]
                previous_index = record["sample_index"]
                previous_started = record["poll_started_monotonic_s"]
                previous_received = record["received_monotonic_s"]
            except (ValueError, UnicodeError, RecursionError) as exc:
                raise ObservationFormatError(f"{path}: line {line_number}: {exc}") from exc
            yield record
