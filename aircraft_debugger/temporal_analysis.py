"""Analyze onset order, overlap and recovery from public replay observations."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .airborne_profile import iter_profile_observations
from .candidate_support import evidence_support
from .diagnosis import _sources, _write_json
from .diagnostic_features import MAXIMUM_OBSERVATION_GAP_SIM_S, _SPECS, _decision, build_feature_frames
from .hypotheses import evaluate_hypotheses, pressure_supply_model


EFFECTS = ("generator_source_anomaly", "blue_pressure_loss")
MAXIMUM_JOINT_READING_SKEW_SIM_S = 0.25


def validate_response_bounds(bounds):
    """The experimenter supplies effect latency intervals in simulator seconds."""
    if not isinstance(bounds, dict) or bounds.keys() != set(EFFECTS):
        raise ValueError("Response bounds must cover generator source and Blue pressure effects")
    result = {}
    for name, interval in bounds.items():
        if (not isinstance(interval, list) or len(interval) != 2
                or any(type(value) not in (int, float) for value in interval)
                or not 0 <= interval[0] <= interval[1] <= 120):
            raise ValueError("Each response interval requires ordered bounds between 0 and 120 seconds")
        result[name] = list(interval)
    return result


def _joint_state(frame):
    """Describe two selected readings from a close pair of sample timestamps."""
    states, times = [], []
    for effect in EFFECTS:
        state = frame["current_state"][_SPECS[effect][0]]
        observed, _ = _decision(effect, state)
        if observed == "unknown" or state.get("observed_at") is None:
            return "unknown"
        states.append(observed == "observed")
        times.append(state["observed_at"]["sim_time_s"])
    if abs(times[0] - times[1]) > MAXIMUM_JOINT_READING_SKEW_SIM_S:
        return "unknown"
    return {
        (False, False): "both_nominal", (True, False): "generator_only",
        (True, True): "both_degraded", (False, True): "pressure_only",
    }[tuple(states)]


def _windows(frames):
    windows = []
    for frame in frames:
        state, index, time = _joint_state(frame), frame["sample_index"], frame["sim_time_s"]
        last = windows[-1] if windows else None
        if (last and state == last["state"] and index == last["last_sample"] + 1
                and time is not None and last["last_sim_s"] is not None
                and 0 < time - last["last_sim_s"] <= MAXIMUM_OBSERVATION_GAP_SIM_S):
            last.update(last_sample=index, last_sim_s=time)
        else:
            windows.append({"state": state, "first_sample": index, "last_sample": index,
                            "first_sim_s": time, "last_sim_s": time})
    return windows


def _shared_trigger(frame, scope_frames, bounds):
    facts = [frame["facts"][effect] for effect in EFFECTS]
    onsets = [fact["onset_interval"] for fact in facts]
    result = {"status": "not_applicable", "onsets": dict(zip(EFFECTS, onsets)),
              "order": "unresolved", "trigger_intervals_sim_s": {}, "common_trigger_interval_sim_s": None}
    if any(fact["state"] == "unknown" for fact in facts):
        result["status"] = "unknown"
        return result
    if not all(fact["state"] == "observed" for fact in facts):
        return result
    result["status"] = "unknown"
    if (not all(onset and onset["lower_sim_time_s"] is not None for onset in onsets)
            or not all(fact["coverage"]["measurement_coverage_complete"] for fact in facts)
            or any(b["sample_index"] != a["sample_index"] + 1 for a, b in zip(scope_frames, scope_frames[1:]))):
        return result
    generator, pressure = onsets
    if (generator["upper_sim_time_s"] < pressure["lower_sim_time_s"]
            and generator["upper_sample_index"] < pressure["lower_sample_index"]):
        result["order"] = "generator_before_pressure"
    elif (pressure["upper_sim_time_s"] < generator["lower_sim_time_s"]
            and pressure["upper_sample_index"] < generator["lower_sample_index"]):
        result["order"] = "pressure_before_generator"
    if bounds is None:
        return result
    intervals = {}
    for name, onset in zip(EFFECTS, onsets):
        minimum, maximum = bounds[name]
        intervals[name] = [onset["lower_sim_time_s"] - maximum, onset["upper_sim_time_s"] - minimum]
    result["trigger_intervals_sim_s"] = intervals
    lower = max(interval[0] for interval in intervals.values())
    upper = min(interval[1] for interval in intervals.values())
    result["status"] = "consistent" if lower <= upper else "contradicted"
    if lower <= upper:
        result["common_trigger_interval_sim_s"] = [lower, upper]
    return result


def analyze_timing(records, *, response_bounds=None):
    """Keep all observed incidents and compare the bounded trigger hypothesis."""
    bounds = validate_response_bounds(response_bounds) if response_bounds is not None else None
    frames = build_feature_frames(records)["frames"]
    latest = {}
    for frame in frames:
        incident = frame["scope"].get("incident_id")
        if incident is not None:
            latest[incident] = frame
    incidents = []
    for incident, frame in latest.items():
        scope = frame["scope"]
        scope_frames = [item for item in frames if item["epoch"] == frame["epoch"] and
                        scope["reference_sample_index"] <= item["sample_index"] <= scope["end_sample_index"]]
        timing = _shared_trigger(frame, scope_frames, bounds)
        base = evaluate_hypotheses(frame, model=pressure_supply_model())
        candidates = []
        for candidate in base["candidates"]:
            paired = candidate["id"] == "grouped_pressure_joint_event" and bounds is not None
            checks = [{"status": timing["status"]}] if paired else []
            status = candidate["status"]
            if paired and status != "contradicted":
                if timing["status"] == "contradicted":
                    status = "contradicted_under_response_bounds"
                elif timing["status"] == "unknown":
                    status = "unconfirmed_timing"
            label = "One shared trigger within the declared response bounds" if paired else candidate["label"]
            candidates.append({"id": candidate["id"], "label": label, "status": status,
                               "evidence_support": evidence_support(candidate, checks)})
        incidents.append({"id": incident, "scope": scope, "joint_windows": _windows(scope_frames),
                          "shared_trigger": timing, "candidates": candidates,
                          "v2_compatible_ids": base["candidate_ids"]})
    return {"profile": "observed-generator-pressure-chronology-v1", "samples": len(frames),
            "response_bounds_sim_s": bounds, "maximum_joint_reading_skew_sim_s": MAXIMUM_JOINT_READING_SKEW_SIM_S,
            "physical_cause_probability": None, "incidents": incidents}


def _markdown(report):
    lines = ["# AeroTrace incident timing", "",
             "Times are simulator seconds. Each window spans sampled states. Evidence support "
             "counts corroborated model checks. Physical cause probability remains unresolved.", ""]
    if report["response_bounds_sim_s"] is not None:
        lines.extend(["Declared response bounds: " + json.dumps(report["response_bounds_sim_s"]), ""])
    for incident in report["incidents"]:
        timing = incident["shared_trigger"]
        lines.extend([f"## {incident['id']}", "",
                      f"Observed onset order: **{timing['order'].replace('_', ' ')}**.",
                      f"Bounded shared trigger: **{timing['status'].replace('_', ' ')}**.", ""])
        if timing["trigger_intervals_sim_s"]:
            lines.extend(["| Effect | Observed onset (s) | Plausible trigger (s) |", "| --- | --- | --- |"])
            for effect, (earliest, latest) in timing["trigger_intervals_sim_s"].items():
                onset = timing["onsets"][effect]
                lines.append(f"| {effect.replace('_', ' ')} | {onset['lower_sim_time_s']:.2f} to "
                             f"{onset['upper_sim_time_s']:.2f} | {earliest:.2f} to {latest:.2f} |")
            lines.append("")
        lines.extend(["| State | Samples | Simulator time (s) |", "| --- | --- | --- |"])
        for window in incident["joint_windows"]:
            first, last = (window[key] for key in ("first_sim_s", "last_sim_s"))
            span = f"{first:.2f} to {last:.2f}" if first is not None and last is not None else "unavailable"
            lines.append(f"| {window['state'].replace('_', ' ')} | "
                         f"{window['first_sample']} to {window['last_sample']} | {span} |")
        lines.extend(["", "| Candidate | Fit | Evidence support |", "| --- | --- | --- |"])
        for candidate in incident["candidates"]:
            support = candidate["evidence_support"]
            value = "Excluded" if support["contradicted_checks"] else "Unavailable"
            if support["percent"] is not None:
                value = f"{support['percent']}% ({support['supported_checks']} of {support['total_checks']})"
            lines.append(f"| {candidate['label']} | {candidate['status'].replace('_', ' ')} | {value} |")
        lines.append("")
    if not report["incidents"]:
        lines.append("No selected incident was observed.")
    return "\n".join(lines).rstrip() + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", required=True, type=Path)
    parser.add_argument("--response-bounds", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output must name a new directory")
    before = args.observations.read_bytes()
    bounds = json.loads(args.response_bounds.read_text(encoding="utf-8")) if args.response_bounds else None
    report = analyze_timing(iter_profile_observations(args.observations), response_bounds=bounds)
    if args.observations.read_bytes() != before:
        raise RuntimeError("Observation file changed during analysis")
    report["observation_sha256"] = hashlib.sha256(before).hexdigest()
    sources = _sources()
    for name in ("temporal_analysis.py", "candidate_support.py"):
        sources["aircraft_debugger/" + name] = Path(__file__).with_name(name).read_bytes()
    report["source_sha256"] = {name: hashlib.sha256(content).hexdigest() for name, content in sources.items()}
    args.output.mkdir(parents=True, exist_ok=False)
    _write_json(args.output / "timing.json", report)
    (args.output / "report.md").write_text(_markdown(report), encoding="utf-8", newline="\n")
    print(args.output / "report.md")


if __name__ == "__main__":
    main()
