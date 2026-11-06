"""Versioned airborne observation transport; no simulator controls or admission.

Schema 1 remains the frozen twelve-channel format in observations.py. Schema 2
adds the fixed airborne profile identifier and eight measured context channels.
Complete transport does not establish stable flight: admission is a separate
consumer of the measurements, timestamps and native-readiness checks.

There is intentionally no public conversion from schema 2 into legacy diagnostic
input. A legacy analyzer must reject context it cannot evaluate. The private
projection below only reuses schema-1 validation of the unchanged base fields.
"""

from __future__ import annotations

from collections.abc import Iterator
import json
from pathlib import Path
import re
from typing import TextIO

from .flightgear import PropertySpec, TelemetrySnapshot
from .observations import (
    CHANNELS,
    ObservationFormatError,
    _ERROR_CODES,
    _MAX_LINE_BYTES,
    _READING_FIELDS,
    _RECORD_FIELDS,
    _boolean,
    _fields,
    _number,
    _reject_constant,
    _unique_object,
    validate_observation,
)


PROFILE_ID = "a320-stable-airborne-v1"
PROPULSION_PROFILE_ID = "a320-propulsion-airborne-v1"
_BASE_CHANNELS = dict(CHANNELS)
_CONTEXT_CHANNELS = {
    "main_gear_1_wow": PropertySpec("/gear/gear[1]/wow", kind="bool"),
    "main_gear_2_wow": PropertySpec("/gear/gear[2]/wow", kind="bool"),
    "height_agl": PropertySpec("/position/altitude-agl-ft", unit="ft"),
    "vertical_speed": PropertySpec("/velocities/vertical-speed-fps", unit="ft/s"),
    "bank": PropertySpec("/orientation/roll-deg", unit="deg"),
    "autopilot_1": PropertySpec("/it-autoflight/output/ap1", kind="bool"),
    "autopilot_2": PropertySpec("/it-autoflight/output/ap2", kind="bool"),
    "autothrust": PropertySpec("/it-autoflight/output/athr", kind="bool"),
}
AIRBORNE_CHANNELS = {**_BASE_CHANNELS, **_CONTEXT_CHANNELS}
PROPULSION_CHANNELS = {
    **AIRBORNE_CHANNELS,
    "engine_2_n2": PropertySpec("/engines/engine[1]/n2-actual", unit="%"),
    "engine_2_fuel_flow": PropertySpec("/engines/engine[1]/ff-actual", unit="lb/h"),
    "yellow_edp_pressure": PropertySpec("/systems/hydraulic/sources/yellow-edp/output-psi", unit="psi"),
    "yellow_electric_pressure": PropertySpec("/systems/hydraulic/sources/yellow-elec/output-psi", unit="psi"),
    "yellow_transfer_pressure": PropertySpec("/systems/hydraulic/sources/ptu/green-yellow", unit="psi"),
    "yellow_pressure": PropertySpec("/systems/hydraulic/yellow-psi", unit="psi"),
    "yellow_quantity": PropertySpec("/systems/hydraulic/yellow-qty", unit="raw model quantity"),
    "ptu_selected": PropertySpec("/controls/hydraulic/switches/ptu", kind="bool"),
}
_AIRBORNE_SPECS = dict(AIRBORNE_CHANNELS)
_PROPULSION_SPECS = dict(PROPULSION_CHANNELS)
_AIRBORNE_FIELDS = _RECORD_FIELDS | {"observation_profile"}


def _validate_context_reading(name: str, spec: PropertySpec, reading: object,
                              started: int | float, received: int | float) -> None:
    """Use the frozen primitive rules with this context's exact path and kind."""
    label = f"readings.{name}"
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
        if spec.kind == "bool":
            _boolean(reading["value"], f"{label}.value")
        else:
            _number(reading["value"], f"{label}.value")
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


def validate_airborne_observation(record: object) -> dict:
    """Validate schema 2 without dropping fields, coercing values or reading truth.

    Missing channels are allowed only with complete=false. Clock/availability
    representation matches schema 1; stability, physical ranges and freshness
    are not certified by this structural validator. The input is not mutated.
    """
    return _validate_profile(record, 2, PROFILE_ID, _AIRBORNE_SPECS)


def validate_propulsion_observation(record: object) -> dict:
    """Validate the explicit extended airborne profile, including every extra reading."""
    return _validate_profile(record, 3, PROPULSION_PROFILE_ID, _PROPULSION_SPECS)


def _validate_profile(record, version, profile_id, specs):
    record = _fields(record, _AIRBORNE_FIELDS, "airborne observation")
    if type(record["schema_version"]) is not int or record["schema_version"] != version:
        raise ObservationFormatError(f"schema_version must be integer {version}")
    if record["observation_profile"] != profile_id:
        raise ObservationFormatError(f"observation_profile must equal {profile_id!r}")
    connected = _boolean(record["connected"], "connected")
    complete = _boolean(record["complete"], "complete")
    readings = record["readings"]
    if not isinstance(readings, dict):
        raise ObservationFormatError("readings must be an object")
    unknown = readings.keys() - specs.keys()
    if unknown:
        raise ObservationFormatError(f"readings contains unknown channels {sorted(unknown, key=repr)!r}")

    # Private validation projection: it never leaves this function, becomes
    # analysis input, alters the supplied record or hides an unvalidated field.
    base_readings = {name: reading for name, reading in readings.items() if name in _BASE_CHANNELS}
    legacy = {name: value for name, value in record.items() if name != "observation_profile"}
    legacy.update(
        schema_version=1,
        readings=base_readings,
        connected=any(isinstance(item, dict) and item.get("reachable") is True for item in base_readings.values()),
        complete=base_readings.keys() == _BASE_CHANNELS.keys() and all(
            isinstance(item, dict) and item.get("valid") is True for item in base_readings.values()
        ),
    )
    validate_observation(legacy)
    for name, reading in readings.items():
        if name not in _BASE_CHANNELS:
            _validate_context_reading(name, specs[name], reading,
                                      record["poll_started_monotonic_s"], record["received_monotonic_s"])
    if connected != any(reading["reachable"] for reading in readings.values()):
        raise ObservationFormatError("connected must match whether any selected reading is reachable")
    expected_complete = readings.keys() == specs.keys() and all(
        reading["valid"] for reading in readings.values()
    )
    if complete != expected_complete:
        raise ObservationFormatError(f"complete must be true exactly when all {len(specs)} airborne channels are present and valid")
    return record


def airborne_observation_record(
    snapshot: TelemetrySnapshot, sample_index: int, poll_started_monotonic_s: float, *, propulsion: bool = False
) -> dict:
    """Build the versioned record, retaining all context and transport timestamps."""
    record = snapshot.to_dict()
    record.update(schema_version=3 if propulsion else 2,
                  observation_profile=PROPULSION_PROFILE_ID if propulsion else PROFILE_ID,
                  sample_index=sample_index, poll_started_monotonic_s=poll_started_monotonic_s)
    validator = validate_propulsion_observation if propulsion else validate_airborne_observation
    return validator(record)


def write_airborne_observation(stream: TextIO, record: dict) -> None:
    """Validate one airborne record before writing a bounded JSON line."""
    propulsion = isinstance(record, dict) and record.get("schema_version") == 3
    validator = validate_propulsion_observation if propulsion else validate_airborne_observation
    validator(record)
    encoded = json.dumps(record, allow_nan=False, ensure_ascii=True, separators=(",", ":"))
    if len(encoded) > _MAX_LINE_BYTES:
        raise ObservationFormatError("observation exceeds the maximum JSON line length")
    stream.write(encoded + "\n")
    stream.flush()


def iter_profile_observations(path: Path) -> Iterator[dict]:
    """Read one explicit, homogeneous schema/profile file, retaining original data.

    The legacy and both airborne profiles use their own validators. Neither
    schema/profile mixing nor backwards local receipt times
    are allowed. Simulator-time pauses/resets remain observations for consumers.
    No files besides the explicitly supplied input are opened.
    """
    path = Path(path)
    profile_key = None
    previous_index = -1
    previous_started = -1.0
    previous_received = -1.0
    previous_channel_times: dict[str, int | float] = {}
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
                raw = json.loads(line.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
                if not isinstance(raw, dict) or type(raw.get("schema_version")) is not int:
                    raise ObservationFormatError("schema_version must be integer 1, 2 or 3")
                if raw["schema_version"] == 1:
                    record = validate_observation(raw)
                    current_profile = (1, None)
                elif raw["schema_version"] == 2:
                    record = validate_airborne_observation(raw)
                    current_profile = (2, PROFILE_ID)
                elif raw["schema_version"] == 3:
                    record = validate_propulsion_observation(raw)
                    current_profile = (3, PROPULSION_PROFILE_ID)
                else:
                    raise ObservationFormatError("unsupported schema_version; expected 1, 2 or 3")
                if profile_key is not None and current_profile != profile_key:
                    raise ObservationFormatError("mixed schema versions/profiles are not allowed in one file")
                profile_key = current_profile
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
