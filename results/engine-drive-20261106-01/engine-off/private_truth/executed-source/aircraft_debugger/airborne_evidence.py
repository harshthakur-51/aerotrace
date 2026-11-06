"""Explicit observation-only replay of the airborne profiles.

Full airborne records are validated and retained. A private, validated projection
reuses the unchanged selected-system detectors; it is never a public conversion
or a ground report presented as airborne validation. Context remains separately
visible, including motion/automation changes and unavailable observations. No
stability/admission filter is applied, and no private experiment files are read.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from dataclasses import asdict
import copy
import hashlib
import json
from pathlib import Path

from .airborne_profile import (
    AIRBORNE_CHANNELS, PROFILE_ID, PROPULSION_CHANNELS, PROPULSION_PROFILE_ID,
    iter_profile_observations, validate_airborne_observation, validate_propulsion_observation,
)
from .evidence import THRESHOLDS, analyze_observations
from .observations import CHANNELS, ObservationFormatError


_AUTOMATION_NAMES = ("autopilot_1", "autopilot_2", "autothrust")
_CONTEXT_NAMES = ("aircraft", "sim_time", "paused", "altitude", "airspeed") + tuple(
    name for name in AIRBORNE_CHANNELS if name not in CHANNELS
)
_LIMITATIONS = [
    "This report analyzes the airborne observation profile; it does not certify that a flight was qualified or that a physical fault experiment was performed.",
    "Selected voltage/inventory compatibility rules are reused from aircraft_debugger.evidence. Their thresholds are project choices, not aircraft warning limits or calibrated probabilities.",
    "All {channel_count} recorded channels, transport quality and per-reading timestamps remain in retained_observations. Derived current values are null when unavailable; raw historical values are not substituted for current evidence.",
    "No stability-band or admission filter is applied. Motion after any event remains an observation, including altitude, airspeed and bank departures.",
    "Automation engagement is observed context. Unchanged motion with engaged automation, retained pressure or a normal bus does not establish healthy actuators or whole-aircraft controllability.",
    "Observed contact/height indications do not independently establish loaded-terrain validity, flightworthiness or an admitted airborne baseline.",
    "Context changes are observations, not proof that a fault caused the motion. Simulator time and local monotonic time are separate clocks.",
    "Current means the final recorded sample; replay does not establish live state at the wall-clock time of analysis.",
]


def _shared_core_record(record: dict) -> dict:
    """Internal reuse only, after full airborne validation and context retention."""
    readings = {name: reading for name, reading in record["readings"].items() if name in CHANNELS}
    return {
        "schema_version": 1, "sample_index": record["sample_index"],
        "poll_started_monotonic_s": record["poll_started_monotonic_s"],
        "received_monotonic_s": record["received_monotonic_s"], "readings": readings,
        "connected": any(reading["reachable"] for reading in readings.values()),
        "complete": readings.keys() == CHANNELS.keys() and all(reading["valid"] for reading in readings.values()),
    }


class _ContextHistory:
    def __init__(self, *, propulsion=False):
        self.channels = PROPULSION_CHANNELS if propulsion else AIRBORNE_CHANNELS
        self.profile_id = PROPULSION_PROFILE_ID if propulsion else PROFILE_ID
        self.records: list[dict] = []
        self.changes: list[dict] = []
        self.latest_channels: dict[str, dict] = {}
        self.quality: dict = {}
        self.previous_sim = None
        self.previous_local = None
        self.previous_channel_times: dict[str, float] = {}
        self.previous_index = -1
        self.epoch = 0

    def _event(self, kind: str, record: dict, **details) -> None:
        time_reading = record["readings"].get("sim_time")
        self.changes.append({
            "context_evidence_id": f"C{len(self.changes) + 1:04d}", "kind": kind,
            "sample_index": record["sample_index"], "epoch": self.epoch,
            "sim_time_s": time_reading["value"] if time_reading and time_reading["valid"] else None,
            "received_monotonic_s": record["received_monotonic_s"], **details,
        })

    def add(self, record: dict) -> None:
        if record["sample_index"] <= self.previous_index:
            raise ObservationFormatError("sample_index must increase strictly across airborne observations")
        self.previous_index = record["sample_index"]
        readings, receipt = record["readings"], record["received_monotonic_s"]
        time_reading, pause_reading = readings.get("sim_time"), readings.get("paused")
        sim_time = time_reading["value"] if time_reading and time_reading["valid"] else None
        reasons = []
        if not record["connected"]:
            reasons.append("disconnected")
        if sim_time is None or sim_time < 0:
            reasons.append("simulator_time_unavailable")
        if not pause_reading or not pause_reading["valid"]:
            reasons.append("pause_state_unknown")
        elif pause_reading["value"]:
            reasons.append("simulator_paused")
        for reading, label in ((time_reading, "simulator_time"), (pause_reading, "pause_state")):
            if reading and receipt - reading["received_monotonic_s"] > THRESHOLDS["maximum_reading_age_local_s"]:
                reasons.append(f"stale_{label}")
            if reading and reading["valid"] and reading["sim_time_s"] is None:
                reasons.append(f"{label}_timestamp_unavailable")
        reset = (self.previous_local is not None and receipt <= self.previous_local) or (
            sim_time is not None and self.previous_sim is not None and sim_time < self.previous_sim
        )
        if reset:
            self.epoch += 1
            self.previous_channel_times.clear()
            reasons.append("clock_reset")
            self._event("clock_reset", record)
        elif sim_time is not None and self.previous_sim is not None and sim_time == self.previous_sim:
            reasons.append("simulator_time_not_advancing")
        self.previous_local = receipt
        if sim_time is not None:
            self.previous_sim = sim_time

        current = {}
        for name, spec in self.channels.items():
            reading = readings.get(name)
            channel_reasons = list(reasons)
            if reading is None:
                channel_reasons.append("missing_channel")
            elif not reading["valid"]:
                channel_reasons.append(reading["error"])
            else:
                if receipt - reading["received_monotonic_s"] > THRESHOLDS["maximum_reading_age_local_s"]:
                    channel_reasons.append("stale_reading")
                timestamp = reading["sim_time_s"]
                if timestamp is None:
                    channel_reasons.append("missing_channel_timestamp")
                else:
                    previous = self.previous_channel_times.get(name)
                    if previous is not None and timestamp <= previous:
                        channel_reasons.append("channel_time_not_advancing")
                    self.previous_channel_times[name] = timestamp
            usable = not channel_reasons
            state = {
                "path": spec.path, "kind": spec.kind, "unit": spec.unit,
                "status": "observed" if usable else "unknown", "current_usable": usable,
                "value": reading["value"] if usable else None,
                "transport_valid": reading["valid"] if reading else False,
                "reasons": list(dict.fromkeys(channel_reasons)),
                "sim_time_s": reading["sim_time_s"] if reading else None,
                "received_monotonic_s": reading["received_monotonic_s"] if reading else None,
            }
            current[name] = state
            previous = self.latest_channels.get(name)
            if previous is not None:
                if previous["status"] != state["status"] or previous["reasons"] != state["reasons"]:
                    self._event("channel_quality_changed", record, channel=name,
                                previous_status=previous["status"], current_status=state["status"], reasons=state["reasons"])
                elif usable and previous["current_usable"] and previous["value"] != state["value"]:
                    self._event("observed_value_changed", record, channel=name, unit=spec.unit,
                                previous_value=previous["value"], current_value=state["value"],
                                channel_sim_time_s=state["sim_time_s"])
        self.latest_channels = current
        self.quality = {
            "sample_index": record["sample_index"], "epoch": self.epoch,
            "all_twenty_current_usable": all(current[name]["current_usable"] for name in AIRBORNE_CHANNELS),
            "context_channels_current_usable": all(current[name]["current_usable"] for name in _CONTEXT_NAMES),
            "unavailable_channels": [name for name, state in current.items() if not state["current_usable"]],
            "time_progressing": not reasons, "global_reasons": reasons,
        }
        # Keep the exact validated public record, including channels not yet used
        # by the selected-system rules. Caller mutations cannot rewrite the report.
        self.records.append(copy.deepcopy(record))

    def to_dict(self) -> dict:
        automation = {name: self.latest_channels[name]["value"] for name in _AUTOMATION_NAMES}
        contact = [self.latest_channels[name]["value"] for name in ("main_gear_1_wow", "main_gear_2_wow")]
        height = self.latest_channels["height_agl"]["value"]
        if any(value is True for value in contact):
            airborne_status = "ground_contact_observed"
        elif all(value is False for value in contact) and height is not None and height > 0:
            airborne_status = "airborne_indications_observed"
        else:
            airborne_status = "unknown"
        return {
            "profile_id": self.profile_id, "channel_specs": {name: asdict(spec) for name, spec in self.channels.items()},
            "latest_channels": self.latest_channels, "quality": self.quality,
            "automation": {"values": automation, "complete": all(value is not None for value in automation.values())},
            "airborne_indications": airborne_status,
            "qualification_evaluated": False, "stability_filter_applied": False,
            "changes": self.changes, "retained_observations": self.records,
        }


def analyze_airborne_observations(records: Iterable[dict], *, propulsion: bool = False) -> dict:
    """Analyze the selected airborne schema after validating every recorded field.

    The selected-system category keeps its original limited meaning. Full current
    assessment additionally requires usable airborne context. Missing context does
    not erase valid voltage/inventory evidence, and normal motion is never used to
    establish actuator health. The canonical hash includes every validated field.
    """
    context = _ContextHistory(propulsion=propulsion)
    validator = validate_propulsion_observation if propulsion else validate_airborne_observation
    version = 3 if propulsion else 2
    digest = hashlib.sha256()

    def shared_records():
        for raw in records:
            record = validator(raw)
            context.add(record)
            digest.update((json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8"))
            yield _shared_core_record(record)

    report = analyze_observations(shared_records())
    if not context.records:
        raise ObservationFormatError(f"At least one schema-{version} airborne observation is required")
    selected_complete = report["assessment"]["complete_current_assessment"]
    report.update(
        schema_version=version, report_type="airborne_observation_evidence_replay",
        observation_schema_version=version, observation_profile=context.profile_id,
        airborne_context=context.to_dict(),
        input_provenance={
            "canonical_observations_sha256": digest.hexdigest(),
            "canonical_encoding": "UTF-8 JSON Lines; sorted keys, compact separators, ASCII escapes, LF endings",
            "input_access": "Explicit public observations only; no manifests, private truth, sibling files or simulator state",
        },
        implementation_provenance={
            "airborne_analysis": "aircraft_debugger.airborne_evidence.analyze_airborne_observations",
            "shared_selected_system_detector": "aircraft_debugger.evidence.analyze_observations",
            "internal_reuse": f"Full schema-{version} validation and retention precede the private shared-field projection",
            "legacy_schema_1_api_unchanged": True,
        },
    )
    report["method"] = "airborne_observation_only_compatibility_with_context"
    report["assessment"]["selected_system_assessment_complete"] = selected_complete
    context_complete = not context.quality["unavailable_channels"]
    report["assessment"]["airborne_context_complete"] = context_complete
    report["assessment"]["complete_current_assessment"] = selected_complete and context_complete
    report["assessment"]["category_scope"] = "Selected generator/bus and blue quantity/pressure observations; not whole-aircraft health"
    report["limitations"] = report["limitations"] + [
        limit.format(channel_count="28" if propulsion else "twenty") for limit in _LIMITATIONS
    ]
    return report


def _markdown(report: dict) -> str:
    context = report["airborne_context"]
    lines = ["# Airborne-profile observation replay", "", f"Selected-system assessment: **{report['assessment']['category']}**.",
             "", "This report retains flight context; it does not establish airborne qualification, physical fault validation or whole-aircraft controllability.",
             "", f"Profile: `{report['observation_profile']}`; samples: {report['sample_count']}.",
             f"Context indications: {context['airborne_indications']}. All twenty channels currently usable: {context['quality']['all_twenty_current_usable']}.",
             "", "## Latest flight context and automation", "", "| Channel | Value | Unit | Current quality |", "|---|---|---|---|"]
    for name in _CONTEXT_NAMES:
        state = context["latest_channels"][name]
        value = "unknown" if state["value"] is None else str(state["value"])
        quality = ", ".join(state["reasons"]) if state["reasons"] else "observed"
        lines.append(f"| {name} | {value} | {state['unit']} | {quality} |")
    lines.extend(["", "## Compatible explanations", ""])
    lines.extend(f"- {item['hypothesis']} ({item['compatibility']}): {item['reason']}" for item in report["explanations"])
    lines.extend(["", "## Observed impact", ""])
    lines.extend(f"- {item['observation']} {item['remaining_capability']}" for item in report["impact"])
    if not report["impact"]:
        lines.append("No selected confirmed impact; this does not establish health.")
    lines.extend(["", "## Evidence and context history", ""])
    lines.extend(f"- {event['evidence_id']} {event['kind']}: first observed at {event['onset']['sim_time_s']} simulator seconds, confirmed at {event['confirmation']['sim_time_s']} simulator seconds." for event in report["ledger"])
    lines.append(f"- {len(context['changes'])} observed value/quality changes; all twenty-channel snapshots and changes are retained in report.json.")
    lines.extend(["", "## Limits and provenance", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.append(f"- Canonical observation SHA-256: `{report['input_provenance']['canonical_observations_sha256']}`.")
    if "observation_file_sha256" in report["input_provenance"]:
        lines.append(f"- Original observation-file SHA-256: `{report['input_provenance']['observation_file_sha256']}`.")
    return "\n".join(lines) + "\n"


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="New report directory; existing directories are refused")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("--output must name a new directory")
    try:
        source_hash = _file_hash(args.observations)
        report = analyze_airborne_observations(iter_profile_observations(args.observations))
        if _file_hash(args.observations) != source_hash:
            raise ValueError("Observation file changed during replay; no report was written")
        report["input_provenance"]["observation_file_sha256"] = source_hash
    except (OSError, ValueError) as error:
        parser.exit(1, f"Airborne observation replay failed: {error}\n")
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    (args.output / "report.md").write_text(_markdown(report), encoding="utf-8", newline="\n")
    print(f"{report['assessment']['category']}: {args.output.resolve()}")


if __name__ == "__main__":
    main()
