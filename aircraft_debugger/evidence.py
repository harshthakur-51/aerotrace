"""Observation-only evidence replay for the native A320 development experiment.

The constants below are illustrative detector choices, with this module as their
provenance. They are not aircraft warning limits or externally validated physical
laws. This compatibility demonstrator has no Bayesian probabilities, initiating
cause identification, flightworthiness verdict, or operational procedures.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
import json
from pathlib import Path


THRESHOLDS = {
    "generator_unavailable_below_v": 20.0,
    "energized_reference_at_least_v": 100.0,
    "bus_retained_at_least_v": 100.0,
    "blue_pressure_retained_at_least_psi": 2500.0,
    "blue_quantity_drop_raw": 0.5,
    "blue_quantity_onset_drop_raw": 0.1,
    "blue_quantity_recovery_tolerance_raw": 0.1,
    "generator_confirmation_readings": 2,
    "quantity_minimum_progressing_readings": 2,
    "maximum_reading_age_local_s": 2.0,
}

LIMITATIONS = [
    "Thresholds are illustrative native-model detector choices; provenance: aircraft_debugger/evidence.py. They are not physical laws or aircraft warning limits.",
    "A stable or energized observed reference does not establish that the whole aircraft is healthy.",
    "Internal simulator properties have not been validated as realistic aircraft sensors.",
    "Readings are non-atomic. Simulator seconds and local monotonic seconds are distinct clocks and are never subtracted from each other.",
    "Current means the final recorded sample, not a live assessment at the wall-clock time when this historical file is replayed.",
    "Event onset means the first observed qualifying change, not the exact physical failure time; confirmation can occur later.",
    "Closely timed electrical and hydraulic observations do not identify a shared initiating cause. Independent faults remain equally compatible.",
    "The two multi-system explanations are a limited comparison, not an exhaustive set of causes. No evidence here establishes fire or an uncontained engine failure.",
    "Retained bus voltage or hydraulic pressure does not establish full remaining capability, flightworthiness, or safe flight.",
    "Upward hydraulic quantity changes can reflect the native model's automatic restoration. They do not prove repair or physical fluid recovery.",
]


def analyze_observations(records: Iterable[dict]) -> dict:
    """Return a deterministic report using only the strict observation contract.

    Validation errors are raised, never converted into healthy observations.
    Each channel must advance on its own simulator timestamp. Paused, disconnected,
    stale and frozen final samples make current evidence insufficient while prior
    ledger entries remain. A simulator clock reset starts a new reference epoch.
    """
    from .observations import validate_observation

    ledger: list[dict] = []
    current: dict = {}
    epoch = 0
    total = 0
    previous_index = -1
    previous_sim_time = None
    previous_receipt = None
    previous_channel_time: dict[str, float] = {}
    generator_reference = None
    quantity_reference = None
    quantity_count = 0
    quantity_onset = None
    generator_low: list[dict] = []
    generator_active = None
    quantity_active = None
    last_unusable_reason = None

    def add_event(kind: str, onset: dict, confirmation: dict, channels: list[str], details: str) -> str:
        evidence_id = f"E{len(ledger) + 1:04d}"
        ledger.append({
            "evidence_id": evidence_id, "kind": kind, "epoch": epoch,
            "onset": onset, "confirmation": confirmation,
            "channels": channels, "details": details,
        })
        return evidence_id

    def stamp(sample_index: int, reading: dict | None = None, sim_time: float | None = None) -> dict:
        return {
            "sample_index": sample_index,
            "sim_time_s": reading["sim_time_s"] if reading else sim_time,
            "received_monotonic_s": reading["received_monotonic_s"] if reading else receipt,
        }

    def unknown(reason: str) -> dict:
        return {"status": "insufficient_evidence", "value": None, "reason": reason}

    for raw in records:
        record = validate_observation(raw)
        total += 1
        index = record["sample_index"]
        if index <= previous_index:
            raise ValueError("sample_index must increase strictly across observations")
        previous_index = index
        receipt = record["received_monotonic_s"]
        readings = record["readings"]
        current = {name: unknown("not_evaluated") for name in ("generator_2", "ac_bus_2", "blue_inventory", "blue_pressure")}
        time_reading = readings.get("sim_time")
        pause_reading = readings.get("paused")
        sim_time = time_reading["value"] if time_reading and time_reading["valid"] else None
        reasons = []
        if not record["connected"]:
            reasons.append("disconnected")
        aircraft_reading = readings.get("aircraft")
        if not aircraft_reading or not aircraft_reading["valid"] or aircraft_reading["value"] not in {"A320-200-CFM", "A320-200-IAE", "A320neo-CFM", "A320neo-PW"}:
            reasons.append("supported_native_aircraft_not_observed")
        if sim_time is None:
            reasons.append("missing_simulator_time")
        if not pause_reading or not pause_reading["valid"]:
            reasons.append("pause_state_unknown")
        elif pause_reading["value"]:
            reasons.append("simulator_paused")
        for reading, label in ((time_reading, "simulator_time"), (pause_reading, "pause_state"), (aircraft_reading, "aircraft_identity")):
            if reading and receipt - reading["received_monotonic_s"] > THRESHOLDS["maximum_reading_age_local_s"]:
                reasons.append(f"stale_{label}")
        # Equal receipts are not a reset: before Python 3.13, Windows monotonic time ticks every ~16 ms.
        local_reset = previous_receipt is not None and receipt < previous_receipt
        sim_reset = sim_time is not None and previous_sim_time is not None and sim_time < previous_sim_time
        if local_reset or sim_reset:
            epoch += 1
            add_event("clock_reset", stamp(index, sim_time=sim_time), stamp(index, sim_time=sim_time), [],
                      "Clock discontinuity: previous references and active conditions are not carried into the new epoch.")
            previous_channel_time.clear()
            generator_reference = quantity_reference = quantity_onset = None
            generator_active = quantity_active = None
            quantity_count = 0
            generator_low.clear()
            reasons.append("clock_reset_requires_new_reference")
        elif sim_time is not None and previous_sim_time is not None and sim_time == previous_sim_time:
            reasons.append("simulator_time_not_advancing")
        previous_receipt = receipt
        if sim_time is not None:
            previous_sim_time = sim_time
        if reasons:
            reason = ", ".join(reasons)
            for name in current:
                current[name] = unknown(reason)
            if reason != last_unusable_reason:
                add_event("current_evidence_unavailable", stamp(index, sim_time=sim_time), stamp(index, sim_time=sim_time), [], reason)
            last_unusable_reason = reason
            # A missing/paused cycle must not complete a two-reading voltage test.
            generator_low.clear()
            current["data_quality"] = {"usable": False, "reasons": reasons, "sample_index": index, "epoch": epoch}
            continue
        last_unusable_reason = None

        def selected(name: str) -> tuple[dict | None, str | None]:
            reading = readings.get(name)
            if reading is None:
                return None, "missing_channel"
            if not reading["valid"]:
                return None, reading["error"] or "invalid_reading"
            if not reading["reachable"]:
                return None, "unreachable_reading"
            if receipt - reading["received_monotonic_s"] > THRESHOLDS["maximum_reading_age_local_s"]:
                return None, "stale_reading"
            channel_time = reading["sim_time_s"]
            if channel_time is None:
                return None, "missing_channel_timestamp"
            old_time = previous_channel_time.get(name)
            previous_channel_time[name] = channel_time
            if old_time is not None and channel_time <= old_time:
                return None, "channel_time_not_advancing"
            return reading, None

        gen, error = selected("generator_2_voltage")
        if gen is None:
            generator_low.clear()
            current["generator_2"] = unknown(error)
        else:
            value = gen["value"]
            now = stamp(index, gen)
            if value >= THRESHOLDS["energized_reference_at_least_v"]:
                if generator_reference is None:
                    generator_reference = {"value_v": value, "observed_at": now}
                if generator_active is not None:
                    add_event("generator_output_restored", now, now, ["generator_2_voltage"],
                              "Output voltage returned to the illustrative energized range. This does not identify a repair.")
                    generator_active = None
                generator_low.clear()
                status = "energized_output_observed"
            elif value < THRESHOLDS["generator_unavailable_below_v"]:
                if generator_reference is None:
                    status = "unavailable_output_without_energized_reference"
                    generator_low.clear()
                elif generator_active is not None:
                    status = "source_unavailable"
                else:
                    generator_low.append(now)
                    status = "suspected_source_unavailable"
                    if len(generator_low) >= THRESHOLDS["generator_confirmation_readings"]:
                        generator_active = add_event("generator_2_source_unavailable", generator_low[0], now,
                            ["generator_2_voltage"], "Low output persisted on two advancing readings after an observed energized reference; this is source-output evidence, not identification of a generator fault.")
                        status = "source_unavailable"
            else:
                status = "reduced_output_observed"
                generator_low.clear()
            current["generator_2"] = {"status": status, "value_v": value, "observed_at": now,
                "energized_reference": generator_reference, "evidence_id": generator_active}

        bus, error = selected("ac_bus_2")
        if bus is None:
            current["ac_bus_2"] = unknown(error)
        else:
            value = bus["value"]
            status = "supply_retained" if value >= THRESHOLDS["bus_retained_at_least_v"] else "supply_unavailable" if value < THRESHOLDS["generator_unavailable_below_v"] else "supply_degraded"
            current["ac_bus_2"] = {"status": status, "value_v": value, "observed_at": stamp(index, bus)}

        qty, error = selected("blue_quantity")
        if qty is None:
            current["blue_inventory"] = unknown(error)
        else:
            value = qty["value"]
            now = stamp(index, qty)
            quantity_count += 1
            if quantity_reference is None:
                quantity_reference = {"value_raw": value, "observed_at": now}
            drop = quantity_reference["value_raw"] - value
            if drop >= THRESHOLDS["blue_quantity_onset_drop_raw"] and quantity_onset is None:
                quantity_onset = now
            elif drop < THRESHOLDS["blue_quantity_onset_drop_raw"] and quantity_active is None:
                quantity_onset = None
            if drop >= THRESHOLDS["blue_quantity_drop_raw"] and quantity_count >= THRESHOLDS["quantity_minimum_progressing_readings"]:
                if quantity_active is None:
                    quantity_active = add_event("blue_inventory_loss", quantity_onset or now, now, ["blue_quantity"],
                        "Observed quantity fell at least 0.5 raw model units from its reference across advancing readings. This does not identify a leak or its initiating cause.")
                status = "inventory_loss_observed"
            elif quantity_active is not None and drop <= THRESHOLDS["blue_quantity_recovery_tolerance_raw"]:
                add_event("blue_quantity_returned_to_reference", now, now, ["blue_quantity"],
                          "Quantity returned near the original reference. Native automatic restoration is a possible explanation; physical repair is not established.")
                quantity_active = None
                quantity_onset = None
                status = "near_observed_reference"
            elif quantity_active is not None:
                status = "inventory_loss_observed"
            elif quantity_count < THRESHOLDS["quantity_minimum_progressing_readings"]:
                status = "reference_pending"
            else:
                status = "near_observed_reference" if drop < THRESHOLDS["blue_quantity_drop_raw"] else "inventory_loss_observed"
            current["blue_inventory"] = {"status": status, "value_raw": value, "drop_from_reference_raw": drop,
                "reference": quantity_reference, "observed_at": now, "evidence_id": quantity_active}

        pressure, error = selected("blue_pressure")
        if pressure is None:
            current["blue_pressure"] = unknown(error)
        else:
            value = pressure["value"]
            current["blue_pressure"] = {"status": "pressure_retained" if value >= THRESHOLDS["blue_pressure_retained_at_least_psi"] else "pressure_degraded",
                "value_psi": value, "observed_at": stamp(index, pressure)}
        current["data_quality"] = {"usable": True, "reasons": [], "sample_index": index, "epoch": epoch}

    if not current:
        current = {name: unknown("no_observations") for name in ("generator_2", "ac_bus_2", "blue_inventory", "blue_pressure")}
        current["data_quality"] = {"usable": False, "reasons": ["no_observations"], "sample_index": None, "epoch": epoch}

    # Channel requests are concurrent, so confirmation order within a poll need
    # not match code order. Preserve input sample order across simulator resets.
    ledger.sort(key=lambda event: (event["confirmation"]["sample_index"], event["confirmation"]["received_monotonic_s"], event["evidence_id"]))
    gen_status = current["generator_2"]["status"]
    hyd_status = current["blue_inventory"]["status"]
    bus_status = current["ac_bus_2"]["status"]
    pressure_status = current["blue_pressure"]["status"]
    electrical_anomaly = gen_status in {"source_unavailable", "reduced_output_observed"} or bus_status in {"supply_unavailable", "supply_degraded"}
    hydraulic_loss = hyd_status == "inventory_loss_observed"
    pressure_anomaly = pressure_status == "pressure_degraded"
    known_no_electrical_anomaly = gen_status == "energized_output_observed" and bus_status == "supply_retained"
    known_no_hydraulic_anomaly = hyd_status == "near_observed_reference" and pressure_status == "pressure_retained"
    current_ids = [state["evidence_id"] for state in current.values() if state.get("evidence_id")]
    explanations = []
    if electrical_anomaly and (hydraulic_loss or pressure_anomaly):
        category = "multiple_system_anomalies"
        for name in ("shared regional damage", "independent electrical/hydraulic faults"):
            explanations.append({"hypothesis": name, "compatibility": "equally_compatible", "supporting_evidence_ids": current_ids,
                "reason": "Both can account for the observed source-output and inventory changes. These channels provide no distinguishing observation of the initiating event." if hydraulic_loss else
                          "Both can account for the observed electrical and hydraulic-pressure anomalies. These channels do not distinguish pressure/supply effects, measurement error or the initiating event."})
    elif electrical_anomaly:
        category = "isolated_electrical_anomaly" if known_no_hydraulic_anomaly else "electrical_anomaly_with_incomplete_hydraulic_assessment"
        explanations.append({"hypothesis": "electrical supply/source anomaly", "compatibility": "compatible", "supporting_evidence_ids": current_ids,
            "reason": "Output or bus voltage is abnormal relative to the detector choices. Engine stoppage, switching, supply configuration and component faults are not distinguished."})
    elif hydraulic_loss:
        category = "hydraulic_depletion"
        explanations.append({"hypothesis": "hydraulic inventory depletion", "compatibility": "compatible", "supporting_evidence_ids": current_ids,
            "reason": "Observed quantity decreased from its reference; external leakage is one possible explanation, not a uniquely identified cause."})
    elif pressure_anomaly:
        category = "hydraulic_pressure_anomaly"
        explanations.append({"hypothesis": "hydraulic pressure anomaly", "compatibility": "compatible", "supporting_evidence_ids": current_ids,
            "reason": "Observed blue pressure is below the illustrative retained range without currently confirmed inventory depletion. These observations do not distinguish pressure/supply effects, measurement error or the initiating cause."})
    elif known_no_electrical_anomaly and known_no_hydraulic_anomaly:
        category = "no_fault_observed"
        explanations.append({"hypothesis": "no selected anomaly currently observed", "compatibility": "compatible", "supporting_evidence_ids": [],
            "reason": "The selected channels are currently near their references. This is not a whole-aircraft health claim."})
    else:
        category = "insufficient_current_evidence"
        explanations.append({"hypothesis": "cause unresolved", "compatibility": "insufficient_evidence", "supporting_evidence_ids": current_ids,
            "reason": "Missing, unconfirmed, paused, frozen, stale or discontinuous observations prevent a current selected-system assessment."})

    impact = []
    if gen_status == "source_unavailable":
        impact.append({"system": "electrical", "observation": "Generator 2 source output unavailable; one observed source is lost.",
                       "remaining_capability": "AC bus 2 voltage remains available; total bus loss is not observed." if bus_status == "supply_retained" else "AC bus 2 voltage is unavailable." if bus_status == "supply_unavailable" else "AC bus 2 supply assessment is degraded or unknown."})
    if hydraulic_loss:
        impact.append({"system": "hydraulic", "observation": "Blue-system inventory loss observed.",
                       "remaining_capability": "Pressure remains in the illustrative retained range; inventory loss can precede pressure degradation." if pressure_status == "pressure_retained" else "Pressure is below the illustrative retained range." if pressure_status == "pressure_degraded" else "Pressure evidence is unavailable; remaining hydraulic capability is unknown."})
    if bus_status in {"supply_unavailable", "supply_degraded"}:
        impact.append({"system": "electrical", "observation": "AC bus 2 voltage is unavailable." if bus_status == "supply_unavailable" else "AC bus 2 voltage is below the illustrative retained range.",
                       "remaining_capability": "Selected bus supply is affected; this does not establish loss of every aircraft bus or all electrical power."})
    if pressure_status == "pressure_degraded" and not hydraulic_loss:
        impact.append({"system": "hydraulic", "observation": "Blue pressure is below the illustrative retained range.",
                       "remaining_capability": "Pressure degradation is observed without confirmed inventory depletion; cause and actuator capability remain unresolved."})
    if not current["data_quality"]["usable"]:
        impact.append({"system": "observability", "observation": "Insufficient current evidence; history remains available.", "remaining_capability": "Unknown."})

    return {
        "schema_version": 1, "method": "observation_only_compatibility_rules", "sample_count": total,
        "thresholds": THRESHOLDS.copy(), "threshold_provenance": "aircraft_debugger/evidence.py: project-specific illustrative detector choices",
        "threshold_units": {"v": "volts", "psi": "pounds per square inch", "raw": "unverified native quantity units", "s": "seconds", "readings": "count"},
        "ledger": ledger, "current_state": current,
        "assessment": {"category": category, "cause_identifiable": False, "probabilities_computed": False,
            "complete_current_assessment": current["data_quality"]["usable"] and all(state["status"] not in {"insufficient_evidence", "reference_pending", "suspected_source_unavailable", "unavailable_output_without_energized_reference"} for name, state in current.items() if name != "data_quality")},
        "explanations": explanations, "impact": impact, "limitations": LIMITATIONS.copy(),
    }


def _markdown(report: dict) -> str:
    lines = ["# Observation-only evidence replay", "", f"Assessment: **{report['assessment']['category']}**", "",
             "Compatibility rules only. No cause probabilities or flightworthiness verdict.", "", "## Current observations", ""]
    for name, state in report["current_state"].items():
        if name != "data_quality":
            lines.append(f"- {name}: {state['status']}")
    lines.extend(["", "## Possible explanations", ""])
    for explanation in report["explanations"]:
        lines.append(f"- {explanation['hypothesis']} ({explanation['compatibility']}): {explanation['reason']}")
    lines.extend(["", "## Observed impact", ""])
    for item in report["impact"]:
        lines.append(f"- {item['observation']} {item['remaining_capability']}")
    if not report["impact"]:
        lines.append("No selected confirmed current impact. This does not establish health.")
    lines.extend(["", "## Evidence ledger", ""])
    for event in report["ledger"]:
        onset, confirmation = event["onset"], event["confirmation"]
        lines.append(f"- {event['evidence_id']} {event['kind']}: first observed at simulator {onset['sim_time_s']} s; confirmed at {confirmation['sim_time_s']} s. {event['details']}")
    lines.extend(["", "## Limits and provenance", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    return "\n".join(lines) + "\n"


def main() -> None:
    from .observations import iter_observations
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="A new report directory; existing directories are refused")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("--output must name a new directory")
    report = analyze_observations(iter_observations(args.observations))
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (args.output / "report.md").write_text(_markdown(report), encoding="utf-8")
    print(f"{report['assessment']['category']}: {args.output.resolve()}")


if __name__ == "__main__":
    main()
