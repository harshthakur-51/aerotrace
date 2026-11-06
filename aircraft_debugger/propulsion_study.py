"""Compare the four recorded drive-loss contrasts and two measurement ablations."""

import argparse
import hashlib
import json
from pathlib import Path
from statistics import median

from .airborne_profile import iter_profile_observations
from .diagnosis import _sources, _write_json, analyze_diagnosis
from .diagnostic_session import DiagnosisSession
from .hypotheses import propulsion_model


_PAIR = "independent_generator_yellow_pump_loss"
_ENGINE = "engine_2_power_loss"
_LABELS = {_PAIR: "Separate generator and Yellow pump losses", _ENGINE: "Engine 2 power loss"}
_RUNS = {"pair-auto": (_PAIR, True), "engine-auto": (_ENGINE, True),
         "pair-off": (_PAIR, False), "engine-off": (_ENGINE, False)}
_DRIVE = ("engine_2_n2", "engine_2_fuel_flow")
_BACKUP = ("yellow_electric_pressure", "yellow_transfer_pressure")
_MEASUREMENTS = (*_DRIVE, "generator_2_voltage", "ac_bus_2", "yellow_edp_pressure",
                 *_BACKUP, "yellow_pressure", "yellow_quantity", "blue_pressure")
_RELATION = "yellow_pressure_follows_measured_supply"


def _ablate(rows, channels):
    """Keep the original sample/clock evidence and mark withheld readings missing."""
    return [{**row, "complete": False,
             "readings": {name: value for name, value in row["readings"].items() if name not in channels}}
            for row in rows]


def _prediction(rows, model):
    report = analyze_diagnosis(rows, model=model)
    diagnosis = report["diagnosis"]
    return {
        "status": diagnosis["status"], "compatible": diagnosis["candidate_ids"],
        "plausible": diagnosis["plausible_candidate_ids"], "support": {
            name: report["candidate_evidence_support"][name] for name in diagnosis["plausible_candidate_ids"]
        },
        "yellow_supply": report["temporal_relations"][_RELATION],
        "onset_intervals": {name: fact["onset_interval"] for name, fact in report["evidence"].items()},
        "current_impact": report["current_impact"], "incident_impact": report["observed_impact"],
    }, diagnosis


def _measure(rows, private_summary, ptu_selected):
    if (not private_summary["completed"] or private_summary["pending_faults_unverified_clear"]
            or private_summary["reference_ptu_selected"] is not ptu_selected):
        raise ValueError("Run lacks a complete, verified operator record for the specified condition")
    active = next(phase for phase in private_summary["phases"] if phase["name"] == "active")
    end = active["end_sample_index_exclusive"]
    stable = rows[end - 6:end]
    if (end - active["first_sample_index"] < 6 or len(stable) != 6
            or any(not row["complete"] or row["readings"]["ptu_selected"]["value"] is not ptu_selected
                   or row["sample_index"] != index for index, row in enumerate(stable, end - 6))):
        raise ValueError("The declared end-of-intervention comparison window is unavailable")
    measures = {}
    for name in _MEASUREMENTS:
        readings = [row["readings"][name] for row in stable]
        values = [reading["value"] for reading in readings]
        measures[name] = {"median": median(values), "minimum": min(values), "maximum": max(values),
                          "unit": readings[0]["unit"]}
    return {"samples": [end - 6, end - 1], "measurements": measures}


def _case(path, expected, ptu_selected, model):
    public_input = path / "observations.jsonl"
    original = public_input.read_bytes()
    rows = list(iter_profile_observations(public_input))
    full, offline = _prediction(rows, model)
    no_drive, _ = _prediction(_ablate(rows, _DRIVE), model)
    no_backup, _ = _prediction(_ablate(rows, _BACKUP), model)
    session = DiagnosisSession(model=model)
    for row in rows:
        live = session.advance(row)
    # Compare against separately stored operator provenance only after diagnosis.
    digest = hashlib.sha256(original).hexdigest()
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    truth = json.loads((path / "private_truth/summary.json").read_text(encoding="utf-8"))
    if digest != manifest["sha256"] or original != public_input.read_bytes():
        raise ValueError(f"Observation hash mismatch for {path.name}")
    native_panel = path / "live-inspector-final.json"
    native_result = None
    if native_panel.is_file():
        native_result = json.loads(native_panel.read_text(encoding="utf-8"))["diagnosis"]["result"]
    return {
        "observation_sha256": digest, "polls": len(rows), "expected_candidate": expected,
        "ptu_selected": ptu_selected, "matched_candidate": full["compatible"] == [expected],
        "streaming_replay_agreement": live["result"] == offline,
        "native_inspector_replay_agreement": native_result == offline if native_result is not None else None,
        "full": full, "without_drive_measurements": no_drive, "without_backup_measurements": no_backup,
        "end_of_intervention": _measure(rows, truth, ptu_selected),
    }


def _markdown(result):
    lines = ["# Engine 2 drive-loss contrast results", "",
             "Each row represents a whole native run. Measurements are medians of the six declared end-of-intervention polls.", "",
             "| Run | Fuel flow (lb/h) | Core speed (%) | Gen 2 (V) | Yellow pump (psi) | Transfer (psi) | Yellow line (psi) |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for name, case in result["runs"].items():
        measures = case["end_of_intervention"]["measurements"]
        columns = ("engine_2_fuel_flow", "engine_2_n2", "generator_2_voltage", "yellow_edp_pressure",
                   "yellow_transfer_pressure", "yellow_pressure")
        lines.append(f"| {name} | " + " | ".join(
            f"{measures[channel]['median']:,.1f}" for channel in columns) + " |")
    lines.extend(["", "Fuel flow is measured in pounds per hour (lb/h). Core speed is measured as a percentage "
                  "of the simulator's reference high-pressure spool speed. V means volts and psi means pounds per square inch.", "",
                  "| Run | Full input | Fuel flow and core speed withheld | Alternate pressure measurements withheld |",
                  "| --- | --- | --- | --- |"])
    for name, case in result["runs"].items():
        full, no_drive, no_backup = (case[key] for key in (
            "full", "without_drive_measurements", "without_backup_measurements"))
        compatible = []
        for candidate in full["compatible"]:
            label = _LABELS.get(candidate, candidate.replace("_", " "))
            score = full["support"][candidate]["percent"]
            compatible.append(f"{label} ({score}% support)" if score is not None else label)
        drive_scores = ", ".join(f"{item['percent']}%" for item in no_drive["support"].values()
                                 if item["percent"] is not None)
        backup_score = no_backup["support"].get(case["expected_candidate"], {}).get("percent")
        drive_result = f"{len(no_drive['plausible'])} plausible, {len(no_drive['compatible'])} confirmed"
        if drive_scores:
            drive_result += f" ({drive_scores})"
        backup_result = f"Supply check {no_backup['yellow_supply']['status']}"
        if backup_score is not None:
            backup_result += f" ({backup_score}% support)"
        lines.append(f"| {name} | {', '.join(compatible) or 'Unresolved'} | "
                     f"{drive_result} | {backup_result} |")
    lines.extend(["", f"Matched the predeclared candidate in **{result['matched_runs']} of {len(result['runs'])}** runs. "
                  f"Streaming and replay agreed in **{result['streaming_replay_matches']} of {len(result['runs'])}** runs.",
                  "", "The percentage measures model checks supported by the available observations. "
                  "The tested contrasts use one pinned simulator and target flight condition.", "",
                  "[Full evidence and onset intervals](study.json)"])
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", required=True, type=Path, help="Directory containing the four named native runs")
    parser.add_argument("--output", required=True, type=Path, help="New directory for the comparison")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output must name a new directory")
    model = propulsion_model()
    protocol = args.study / "PROTOCOL.md"
    result = {"protocol_sha256": hashlib.sha256(protocol.read_bytes()).hexdigest(),
              "model_id": model["model_id"], "runs": {
                  name: _case(args.study / name, expected, ptu, model) for name, (expected, ptu) in _RUNS.items()
              }}
    result["matched_runs"] = sum(case["matched_candidate"] for case in result["runs"].values())
    result["streaming_replay_matches"] = sum(case["streaming_replay_agreement"] for case in result["runs"].values())
    sources = {**_sources(), "aircraft_debugger/propulsion_study.py": Path(__file__).read_bytes(),
               "aircraft_debugger/diagnostic_session.py": Path(__file__).with_name("diagnostic_session.py").read_bytes()}
    result["source_sha256"] = {name: hashlib.sha256(payload).hexdigest() for name, payload in sources.items()}
    args.output.mkdir(parents=True, exist_ok=False)
    _write_json(args.output / "study.json", result)
    (args.output / "REPORT.md").write_text(_markdown(result), encoding="utf-8", newline="\n")
    print(args.output / "REPORT.md")


if __name__ == "__main__":
    main()
