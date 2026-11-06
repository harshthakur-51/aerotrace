"""Pure observation-to-feature adapter for AeroTrace's finite hypothesis model.

This reuses the established quality-aware detectors, never their hand-authored
categories or explanations. Prefix replay is deliberately simple in this first
offline path; it is not an optimized streaming implementation.

Incident closure after two normal progressing selected snapshots and the
three-simulator-second continuity bound are original project policies. They are
not aircraft warning limits or externally validated physical equations. No native
depletion rate, failure label, admission result or operator phase is inspected.
"""

from __future__ import annotations

from collections.abc import Iterable
import copy

from .airborne_evidence import analyze_airborne_observations
from .airborne_profile import validate_airborne_observation, validate_propulsion_observation
from .evidence import THRESHOLDS, analyze_observations
from .observations import ObservationFormatError, validate_observation
from .pilot_display import GroundPowerClock
from .propulsion_features import (
    PROPULSION_FACTS, PROPULSION_IMPACTS, add_propulsion_evidence, retained_drive_relations, yellow_supply_relation,
)


MAXIMUM_OBSERVATION_GAP_SIM_S = 3.0
_SPECS = {
    "generator_source_anomaly": ("generator_2", "generator_2_voltage", "value_v"),
    "blue_inventory_loss": ("blue_inventory", "blue_quantity", "value_raw"),
    "bus_supply_loss": ("ac_bus_2", "ac_bus_2", "value_v"),
    "blue_pressure_loss": ("blue_pressure", "blue_pressure", "value_psi"),
}
_EVENTS = {
    "generator_source_anomaly": "generator_2_source_unavailable",
    "blue_inventory_loss": "blue_inventory_loss",
}


def _decision(name: str, state: dict) -> tuple[str, bool]:
    """Return tri-state evidence and whether uncertainty is only initial reference."""
    status = state["status"]
    if name == "generator_source_anomaly":
        if status in {"source_unavailable", "reduced_output_observed"}:
            return "observed", False
        return ("not_observed", False) if status == "energized_output_observed" else ("unknown", False)
    if name == "blue_inventory_loss":
        if status == "inventory_loss_observed":
            return "observed", False
        if status == "reference_pending":
            return "unknown", True
        if status == "near_observed_reference":
            # A developing but unconfirmed decline is not healthy evidence.
            if state["drop_from_reference_raw"] >= THRESHOLDS["blue_quantity_onset_drop_raw"]:
                return "unknown", False
            return "not_observed", False
        return "unknown", False
    positives = {"supply_unavailable", "supply_degraded"} if name == "bus_supply_loss" else {"pressure_degraded"}
    negative = "supply_retained" if name == "bus_supply_loss" else "pressure_retained"
    if status in positives:
        return "observed", False
    return ("not_observed", False) if status == negative else ("unknown", False)


def _snapshot(record: dict, report: dict) -> dict:
    states = report["current_state"]
    facts, usable, points, soft = {}, {}, {}, {}
    for name, (state_name, channel, value_name) in _SPECS.items():
        state = states[state_name]
        facts[name], soft[name] = _decision(name, state)
        stamp = state.get("observed_at")
        reading = record["readings"].get(channel)
        usable[name] = bool(stamp is not None and reading and reading["valid"])
        points[name] = None if not usable[name] else {
            "sample_index": record["sample_index"], "sim_time_s": stamp["sim_time_s"],
            "channel": channel, "value": state[value_name], "unit": reading["unit"],
            "observed_status": state["status"],
            "evidence_id": state.get("evidence_id"),
        }
    clock = record["readings"].get("sim_time", {})
    impact = copy.deepcopy(report["impact"])
    for item in impact:
        # Adapt the archived ground report's wording at the causal display boundary.
        if item["observation"] == "Blue-system inventory loss observed.":
            item["observation"] = "Reported Blue reservoir quantity declined from its observed reference."
    return {"sample_index": record["sample_index"],
            "sim_time_s": clock.get("value") if clock.get("valid") else None,
            "epoch": states["data_quality"]["epoch"], "states": states,
            "facts": facts, "soft_reference": soft, "usable": usable, "points": points,
            "events": report["ledger"], "impact": impact}


def _all_normal(snapshot: dict) -> bool:
    return all(value == "not_observed" for value in snapshot["facts"].values())


def _trigger(snapshot: dict) -> bool:
    if any(value == "observed" for value in snapshot["facts"].values()):
        return True
    states = snapshot["states"]
    return (states["generator_2"]["status"] in {
                "suspected_source_unavailable", "unavailable_output_without_energized_reference"}
            or (states["blue_inventory"]["status"] == "near_observed_reference"
                and states["blue_inventory"]["drop_from_reference_raw"] >= THRESHOLDS["blue_quantity_onset_drop_raw"]))


def _fact(name: str, channel: str, snapshots: list[dict], *, whole_epoch=False) -> dict:
    positive = [s for s in snapshots if s["facts"][name] == "observed"]
    unavailable = [s["sample_index"] for s in snapshots if not s["usable"][name]]
    pending = [s["sample_index"] for s in snapshots
               if s["facts"][name] == "unknown" and not s["soft_reference"][name]]
    points = [s["points"][name] for s in snapshots if s["points"][name] is not None]
    gaps = []
    for previous, current in zip(points, points[1:]):
        delta = current["sim_time_s"] - previous["sim_time_s"]
        skipped_poll = whole_epoch and current["sample_index"] != previous["sample_index"] + 1
        if skipped_poll or delta <= 0 or delta > MAXIMUM_OBSERVATION_GAP_SIM_S:
            gaps.append({"from_sample_index": previous["sample_index"], "to_sample_index": current["sample_index"],
                         "simulator_gap_s": delta})
    coverage = {"samples": len(snapshots), "usable_samples": len(points),
                "unavailable_sample_indices": unavailable, "pending_sample_indices": pending,
                "timestamp_gaps": gaps, "measurement_coverage_complete": not unavailable and not gaps,
                "absence_complete": len(points) >= 2 and not unavailable and not pending and not gaps,
                "counts_are_not_independent_experiments": True}
    observed = bool(positive)
    state = "observed" if observed else "not_observed" if coverage["absence_complete"] else "unknown"
    reason = ("A confirmed selected anomaly was observed within this incident/window. Later recovery or missingness does not erase it."
              if observed else "No selected anomaly was observed across the progressing covered window; this is not whole-aircraft health."
              if state == "not_observed" else "Missing, discontinuous, reference-pending or unconfirmed observations prevent an absence claim.")
    evidence = []
    interval = None
    if observed:
        first = positive[0]
        onset_index = first["sample_index"]
        upper = first["points"][name]["sim_time_s"]
        evidence.append(copy.deepcopy(first["points"][name]))
        last = positive[-1]["points"][name]
        if last["sample_index"] != evidence[0]["sample_index"]:
            evidence.append(copy.deepcopy(last))
        event_kind = _EVENTS.get(name)
        events = first["events"]
        matches = [event for event in events if event["kind"] == event_kind
                   and event["epoch"] == first["epoch"]
                   and snapshots[0]["sample_index"] <= event["confirmation"]["sample_index"] <= first["sample_index"]]
        if matches:
            event = matches[-1]
            onset_index = event["onset"]["sample_index"]
            upper = event["onset"]["sim_time_s"]
            evidence[0]["legacy_event_id"] = event["evidence_id"]
            evidence[0]["onset_sample_index"] = onset_index
            evidence[0]["confirmation_sample_index"] = event["confirmation"]["sample_index"]
        prior = [s["points"][name] for s in snapshots
                 if s["sample_index"] < onset_index and s["facts"][name] == "not_observed" and s["usable"][name]]
        lower_point = prior[-1] if prior else None
        interval = {"lower_sim_time_s": lower_point["sim_time_s"] if lower_point else None,
                    "upper_sim_time_s": upper,
                    "lower_sample_index": lower_point["sample_index"] if lower_point else None,
                    "upper_sample_index": onset_index,
                    "semantics": "Last observed non-anomalous to first observed qualifying change, not exact physical failure onset."}
        if whole_epoch:
            confirmation = first["sample_index"]
            interval["covered_through_confirmation"] = not (
                any(index <= confirmation for index in unavailable)
                or any(gap["to_sample_index"] <= confirmation for gap in gaps)
            )
    elif points:
        evidence.append(copy.deepcopy(points[-1]))
    return {"state": state, "evidence": evidence, "channels": [channel],
            "onset_interval": interval, "reason": reason, "coverage": coverage}


def _relation(facts: dict) -> dict:
    quantity, pressure = facts["blue_inventory_loss"], facts["blue_pressure_loss"]
    result = {"status": "not_applicable", "evidence": [],
              "reason": "Both inventory and pressure loss have not been established within this incident."}
    if quantity["state"] != "observed" or pressure["state"] != "observed":
        return result
    result["evidence"] = copy.deepcopy(quantity["evidence"][:1] + pressure["evidence"][:1])
    q, p = quantity["onset_interval"], pressure["onset_interval"]
    result.update(status="unknown", reason="Onset brackets overlap or observation gaps prevent a qualitative ordering claim.")
    if (q is None or p is None or q["lower_sim_time_s"] is None or p["lower_sim_time_s"] is None
            or not q.get("covered_through_confirmation", quantity["coverage"]["measurement_coverage_complete"])
            or not p.get("covered_through_confirmation", pressure["coverage"]["measurement_coverage_complete"])):
        return result
    # Requiring separate poll brackets prevents tiny non-atomic read offsets in
    # one poll from becoming a fabricated physical propagation direction.
    if (q["upper_sim_time_s"] < p["lower_sim_time_s"]
            and q["upper_sample_index"] < p["lower_sample_index"]):
        result.update(status="consistent", reason="The observed inventory-loss bracket precedes the pressure-loss bracket; this supports the qualitative selected depletion path, not an exact physical delay.")
    elif (p["upper_sim_time_s"] < q["lower_sim_time_s"]
          and p["upper_sample_index"] < q["lower_sample_index"]):
        result.update(status="contradicted", reason="Observed pressure loss clearly precedes observed inventory loss under continuous selected measurements; the represented inventory-first path does not account for this order.")
    return result


def _impact(facts: dict) -> list[dict]:
    descriptions = {
        "generator_source_anomaly": ("electrical", "Generator-2 source-output degradation was observed in this incident.",
                                      "Bus observations are separate; source loss does not establish total downstream supply loss."),
        "blue_inventory_loss": ("hydraulic", "Reported Blue reservoir quantity declined in this incident.",
                                "Physical fluid loss requires independent evidence. Pressure is assessed separately."),
        "bus_supply_loss": ("electrical", "Monitored bus-2 supply degradation was observed in this incident.",
                            "This does not establish loss of all buses or every electrical function."),
        "blue_pressure_loss": ("hydraulic", "Blue pressure degradation was observed in this incident.",
                               "Pressure degradation does not establish total controllability or manual-control force."),
    }
    descriptions.update(PROPULSION_IMPACTS)
    return [{"fact_id": name, "system": descriptions[name][0], "observation": descriptions[name][1],
             "remaining_capability": descriptions[name][2], "scope": "incident_or_selected_window_history",
             "evidence": copy.deepcopy(fact["evidence"])}
            for name, fact in facts.items() if fact["state"] == "observed"]


class FeatureHistory:
    """Incremental incident aggregation over already validated detector reports.

    The detector still evaluates the supplied public prefix. This class avoids
    rebuilding earlier feature frames on every live update; no thresholds change.
    """

    def __init__(self, *, propulsion=False, generated=False, sequence=False):
        self.propulsion = propulsion or generated
        self.generated = generated
        self.channels = {name: spec[1] for name, spec in _SPECS.items()}
        if self.propulsion:
            self.channels.update({name: channel for name, (channel, _) in PROPULSION_FACTS.items()})
        self.epoch_history = []
        self.sequence_snapshots = [] if sequence else None
        self.power_clock = GroundPowerClock() if sequence else None
        self.incident = None
        self.epoch = None
        self.incident_counter = 0
        self.normal_run = 0

    def snapshot(self, row: dict, report: dict) -> dict:
        snapshot = _snapshot(row, report)
        if self.propulsion:
            add_propulsion_evidence(snapshot, report["airborne_context"]["latest_channels"], generated=self.generated)
        return snapshot

    def advance(self, row: dict, report: dict) -> dict:
        snapshot = self.snapshot(row, report)
        if self.sequence_snapshots is not None:
            self.retain_sequence_snapshot(row, snapshot)
        if snapshot["epoch"] != self.epoch:
            self.epoch, self.epoch_history, self.incident, self.normal_run = snapshot["epoch"], [], None, 0
        previous = self.epoch_history[-1] if self.epoch_history else None
        self.epoch_history.append(snapshot)
        self.epoch_history = self.epoch_history[-2:]
        trigger = _trigger(snapshot)
        if trigger and (self.incident is None or self.incident["closed"]):
            self.incident_counter += 1
            self.incident = {"incident_id": f"I{self.incident_counter:04d}", "epoch": self.epoch,
                        "start_sample_index": snapshot["sample_index"],
                        "end_sample_index": snapshot["sample_index"], "closed": False,
                        "snapshots": ([previous] if previous is not None else []) + [snapshot]}
            self.normal_run = 0
        elif self.incident is not None and not self.incident["closed"]:
            self.incident["snapshots"].append(snapshot)
            self.incident["end_sample_index"] = snapshot["sample_index"]
        if self.incident is not None and not self.incident["closed"]:
            self.normal_run = self.normal_run + 1 if _all_normal(snapshot) else 0
            if self.normal_run >= 2:
                self.incident["closed"] = True
        if self.incident is not None:
            scope = {key: copy.deepcopy(value) for key, value in self.incident.items() if key != "snapshots"}
            scope["kind"] = "last_observed_incident"
            window = self.incident["snapshots"]
        else:
            window = self.epoch_history[-2:]
            scope = {"kind": "selected_reference_window", "incident_id": None, "epoch": self.epoch,
                     "start_sample_index": window[0]["sample_index"],
                     "end_sample_index": snapshot["sample_index"], "closed": False}
        scope["reference_sample_index"] = window[0]["sample_index"]
        facts, relations = self.window_evidence(window)
        frame = {"sample_index": snapshot["sample_index"], "sim_time_s": snapshot["sim_time_s"],
                 "epoch": self.epoch, "scope": scope, "facts": facts,
                 "temporal_relations": relations,
                 "current_state": copy.deepcopy(snapshot["states"]),
                 "current_impact": copy.deepcopy(snapshot["impact"]), "observed_impact": _impact(facts),
                 "current_quality": copy.deepcopy(report.get("airborne_context", {}).get("quality", snapshot["states"]["data_quality"])),
                 "fact_provenance": "aircraft_debugger.diagnostic_features; existing detector states/events, no category or private-label inference"}
        return frame

    def window_evidence(self, window, *, whole_epoch=False):
        facts = {name: _fact(name, channel, window, whole_epoch=whole_epoch)
                 for name, channel in self.channels.items()}
        relations = {"inventory_before_pressure": _relation(facts)}
        if self.propulsion:
            relations["yellow_pressure_follows_measured_supply"] = yellow_supply_relation(facts, window)
        if self.generated:
            relations.update(retained_drive_relations(window))
        return facts, relations

    def retain_sequence_snapshot(self, row, snapshot):
        if self.power_clock.epoch != snapshot["epoch"]:
            self.sequence_snapshots.clear()
        self.power_clock.observe(row, snapshot["epoch"])
        readings = row["readings"]
        if not self.sequence_snapshots and "external_power_output" in readings:
            # A startup-inclusive capture sets the display clock on the
            # ground. Its cold aircraft readings are outside airborne fit.
            gear = [readings.get(name, {}) for name in ("main_gear_1_wow", "main_gear_2_wow")]
            height = readings.get("height_agl", {})
            if (not all(point.get("valid") and point["value"] is False for point in gear)
                    or not height.get("valid") or height["value"] <= 0):
                return
        self.sequence_snapshots.append(snapshot)

    def sequence_frame(self):
        if not self.sequence_snapshots:
            return None
        window = self.sequence_snapshots
        facts, relations = self.window_evidence(window, whole_epoch=True)
        return {"epoch": window[0]["epoch"], "first_sample_index": window[0]["sample_index"],
                "last_sample_index": window[-1]["sample_index"], "power_on_sim_s": self.power_clock.origin,
                "facts": facts, "temporal_relations": relations}


def build_feature_frames(records: Iterable[dict], *, propulsion: bool = False, generated: bool = False,
                         whole_epoch: bool = False, sequence_prefixes: bool = False) -> dict:
    """Validate public input and return per-prefix incident features plus its report.

    The only input is the supplied observations. A new clock epoch clears incident
    references. After two normal selected snapshots an incident closes; its history
    remains inspectable until a genuinely new anomaly starts a fresh incident.
    Whole-epoch mode returns one evidence frame per clock epoch, retaining facts
    across observable recovery gaps.
    """
    propulsion = propulsion or generated
    rows = [copy.deepcopy(row) for row in records]
    if not rows:
        raise ObservationFormatError("At least one public observation is required")
    if not isinstance(rows[0], dict):
        raise ObservationFormatError("Each public observation must be an object")
    version = rows[0].get("schema_version")
    supported = (3,) if propulsion else (1, 2)
    if type(version) is not int or version not in supported:
        raise ObservationFormatError("The propulsion catalogue requires schema 3; other catalogues require schema 1 or 2")
    if propulsion:
        validator = validate_propulsion_observation
    else:
        validator = validate_airborne_observation if version == 2 else validate_observation
    for row in rows:
        if not isinstance(row, dict):
            raise ObservationFormatError("Each public observation must be an object")
        if type(row.get("schema_version")) is not int or row["schema_version"] != version:
            raise ObservationFormatError("Mixed observation schemas are not permitted")
        validator(row)

    history = FeatureHistory(propulsion=propulsion, generated=generated, sequence=whole_epoch or sequence_prefixes)
    frames = []
    report = None

    for end, row in enumerate(rows, 1):
        report = (analyze_observations(rows[:end]) if version == 1
                  else analyze_airborne_observations(rows[:end], propulsion=propulsion))
        if not whole_epoch:
            frame = history.advance(row, report)
            if sequence_prefixes:
                frame["sequence_epoch"] = history.sequence_frame()
            frames.append(frame)
            continue
        snapshot = history.snapshot(row, report)
        if history.sequence_snapshots and history.power_clock.epoch != snapshot["epoch"]:
            frames.append(history.sequence_frame())
        history.retain_sequence_snapshot(row, snapshot)
    if whole_epoch and history.sequence_snapshots:
        frames.append(history.sequence_frame())
    return {"frames": frames, "observation_report": report}


# A descriptive alias for callers that prefer the extraction terminology.
extract_features = build_feature_frames
