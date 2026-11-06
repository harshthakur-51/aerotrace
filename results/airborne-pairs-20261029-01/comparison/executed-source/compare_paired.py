"""Public-input pair comparison; no experiment labels, phases or native access.

Each inference call receives one public prefix. Source reads happen separately
for provenance. The comparison uses inputA/inputB labels, never private causes.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

from aircraft_debugger.airborne_evidence import analyze_airborne_observations
from aircraft_debugger.airborne_profile import AIRBORNE_CHANNELS, iter_profile_observations


SOURCE_NAMES = (
    "aircraft_debugger/__init__.py",
    "aircraft_debugger/airborne_evidence.py",
    "aircraft_debugger/airborne_profile.py",
    "aircraft_debugger/evidence.py",
    "aircraft_debugger/observations.py",
    "aircraft_debugger/flightgear.py",
)
RANGE_NAMES = (
    "generator_2_voltage", "ac_bus_1", "ac_bus_2", "blue_quantity", "blue_pressure",
    "altitude", "airspeed", "height_agl", "vertical_speed", "bank",
    "main_gear_1_wow", "main_gear_2_wow", "autopilot_1", "autopilot_2", "autothrust",
)
LIMITS = [
    "Only two explicitly named public observation inputs enter inference; no manifests, private labels, actions, admission or phase files are read.",
    "InputA/inputB are identifiers, not claims of distinct physical initiating causes.",
    "Separate recordings need not be byte-identical and are not treated as independent statistical trials or a diagnosis-accuracy benchmark.",
    "Source/inventory/pressure compatibility rules are illustrative project choices; no root probabilities, unique causal identification or real-aircraft validation is computed.",
    "All-input ranges include every recorded sample; category-conditioned ranges select only by public-prefix analysis, never operator phases.",
    "Retained bus voltage and stable automated motion do not establish every actuator's capability or whole-aircraft health.",
    "Raw quantity units remain unresolved; any native automatic refill is not proof of physical repair.",
    "Different simulator clocks, receipt times, conditions and sampling offsets prevent direct byte-for-byte trajectory comparisons from establishing causal differences.",
]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def ranges(rows: list[dict]) -> dict:
    result = {}
    for name in RANGE_NAMES:
        readings = [row["readings"].get(name) for row in rows]
        values = [reading["value"] for reading in readings if reading and reading["valid"]]
        item = {"unit": AIRBORNE_CHANNELS[name].unit, "samples": len(rows),
                "valid_values": len(values), "unavailable_values": len(rows) - len(values)}
        if AIRBORNE_CHANNELS[name].kind == "bool":
            item["value_counts"] = {str(value).lower(): count for value, count in Counter(values).items()}
        else:
            item.update(minimum=min(values) if values else None, maximum=max(values) if values else None)
        result[name] = item
    return result


def canonical_candidates(explanations: list[dict]) -> list[dict]:
    return sorted(({"hypothesis": item["hypothesis"], "compatibility": item["compatibility"]}
                   for item in explanations), key=lambda item: (item["hypothesis"], item["compatibility"]))


def summarize(path: Path) -> tuple[dict, bytes]:
    before = path.read_bytes()
    rows = list(iter_profile_observations(path))
    if not rows:
        raise ValueError(f"At least one public observation is required: {path}")
    timeline, transitions, multiple, previous = [], [], [], None
    for end in range(1, len(rows) + 1):
        report = analyze_airborne_observations(rows[:end])
        row = rows[end - 1]
        time_reading = row["readings"].get("sim_time")
        entry = {"sample_index": row["sample_index"],
                 "sim_time_s": time_reading["value"] if time_reading and time_reading["valid"] else None,
                 "assessment": report["assessment"], "current_state": report["current_state"],
                 "explanations": report["explanations"], "impact": report["impact"],
                 "context_quality": report["airborne_context"]["quality"],
                 "evidence_ids": [event["evidence_id"] for event in report["ledger"]]}
        timeline.append(entry)
        category = report["assessment"]["category"]
        if category != previous:
            transitions.append({"sample_index": entry["sample_index"], "sim_time_s": entry["sim_time_s"],
                                "category": category})
            previous = category
        if category == "multiple_system_anomalies":
            multiple.append({"sample_index": entry["sample_index"], "sim_time_s": entry["sim_time_s"],
                             "candidates": canonical_candidates(report["explanations"]),
                             "cause_identifiable": report["assessment"]["cause_identifiable"],
                             "probabilities_computed": report["assessment"]["probabilities_computed"],
                             "complete_current_assessment": report["assessment"]["complete_current_assessment"]})
    if path.read_bytes() != before:
        raise ValueError(f"Explicit observation input changed during replay: {path}")
    variants = sorted({json.dumps(entry["candidates"], sort_keys=True) for entry in multiple})
    selected_indices = {entry["sample_index"] for entry in multiple}
    result = {
        "input_provenance": {"explicit_path": str(path.resolve()), "observation_file_sha256": digest(before),
                             "canonical_observations_sha256": report["input_provenance"]["canonical_observations_sha256"],
                             "bytes": len(before), "samples": len(rows)},
        "category_transitions": transitions,
        "category_sample_counts": dict(Counter(entry["assessment"]["category"] for entry in timeline)),
        "multiple_system_anomalies": {
            "sample_count": len(multiple), "indices": [entry["sample_index"] for entry in multiple],
            "samples": multiple, "candidate_set_variants": [json.loads(value) for value in variants],
            "all_have_multiple_candidates": all(len(entry["candidates"]) >= 2 for entry in multiple) if multiple else None,
            "all_candidates_equally_compatible": all(
                all(candidate["compatibility"] == "equally_compatible" for candidate in entry["candidates"])
                for entry in multiple) if multiple else None,
            "all_cause_identifiable_false": all(entry["cause_identifiable"] is False for entry in multiple) if multiple else None,
            "all_probabilities_not_computed": all(entry["probabilities_computed"] is False for entry in multiple) if multiple else None,
        },
        "ranges_all_public_samples": ranges(rows),
        "ranges_during_multiple_system_category": ranges([row for row in rows if row["sample_index"] in selected_indices]),
        "final_assessment": report["assessment"], "final_explanations": report["explanations"],
        "ledger": report["ledger"], "timeline": timeline,
        "context_unusable_sample_indices": [entry["sample_index"] for entry in timeline
                                             if not entry["context_quality"]["all_twenty_current_usable"]],
    }
    return result, before


def markdown(report: dict) -> str:
    lines = ["# Public-input paired observation comparison", "", report["comparison"]["finding"], "",
             "InputA/inputB are public-input identifiers. No private initiating-cause label is used.", ""]
    for label in ("inputA", "inputB"):
        summary = report[label]
        multi = summary["multiple_system_anomalies"]
        lines.extend([f"## {label}", "", f"Public samples: {summary['input_provenance']['samples']}.",
                      f"Final selected category: `{summary['final_assessment']['category']}`.",
                      f"Multiple-system category observed at {multi['sample_count']} public prefixes.", "",
                      "| Category transition index | Observed simulator time (s) | Category |", "|---|---|---|"])
        lines.extend(f"| {entry['sample_index']} | {entry['sim_time_s']} | {entry['category']} |"
                     for entry in summary["category_transitions"])
        lines.extend(["", "Candidate-set variants during multiple-system prefixes:", ""])
        if multi["candidate_set_variants"]:
            for variant in multi["candidate_set_variants"]:
                lines.append("- " + "; ".join(f"{item['hypothesis']} ({item['compatibility']})" for item in variant))
        else:
            lines.append("No multiple-system prefix was observed; no candidate-set conclusion is imposed.")
        lines.extend(["", f"All multiple-system candidates equally compatible: {multi['all_candidates_equally_compatible']}.",
                      f"Cause unidentified at every multiple-system prefix: {multi['all_cause_identifiable_false']}.", "",
                      "All-input selected ranges (including baseline and recovery if present):", "",
                      "| Public channel | Minimum | Maximum | Unit | Unavailable samples |", "|---|---|---|---|---|"])
        for name in RANGE_NAMES[:10]:
            item = summary["ranges_all_public_samples"][name]
            lines.append(f"| {name} | {item['minimum']} | {item['maximum']} | {item['unit']} | {item['unavailable_values']} |")
        lines.extend(["", "Recorded automation/contact value counts:", ""])
        for name in RANGE_NAMES[10:]:
            item = summary["ranges_all_public_samples"][name]
            lines.append(f"- {name}: {item['value_counts']}; unavailable: {item['unavailable_values']}.")
        lines.extend(["", f"Observation-file SHA-256: `{summary['input_provenance']['observation_file_sha256']}`.", ""])
    lines.extend(["## Limits", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.extend(["", "s means recorded simulator seconds, V volts, psi pounds per square inch, ft feet, kt knots (one nautical mile per hour), and AC alternating current. Quantity uses raw native units. Source hashes and exact archives are in provenance.json."])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations-a", required=True, type=Path)
    parser.add_argument("--observations-b", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("--output must name a new directory")
    # Freeze actual contributing source bytes before analysis; no source inspection
    # supplies evidence or labels to the inference function.
    project = Path(__file__).resolve().parents[2]
    for name in SOURCE_NAMES:
        module_name = name[:-3].replace("/", ".").removesuffix(".__init__")
        if Path(sys.modules[module_name].__file__).resolve() != (project / name).resolve():
            raise ValueError(f"Contributing module was imported from a different checkout: {module_name}")
    source_bytes = {name: (project / name).read_bytes() for name in SOURCE_NAMES}
    source_bytes["compare_paired.py"] = Path(__file__).read_bytes()
    input_a, bytes_a = summarize(args.observations_a)
    input_b, bytes_b = summarize(args.observations_b)
    ma, mb = input_a["multiple_system_anomalies"], input_b["multiple_system_anomalies"]
    both_multiple = bool(ma["sample_count"] and mb["sample_count"])
    unresolved = both_multiple and all(item["all_candidates_equally_compatible"] and item["all_cause_identifiable_false"]
                                       for item in (ma, mb))
    finding = ("Both public inputs contain multiple-system prefixes with equally compatible explanations and no identified initiating cause."
               if unresolved else
               "The two public inputs do not both exhibit that complete ambiguity pattern; inspect the reported categories and quality without imposing expected outcomes.")
    report = {"schema_version": 1, "report_type": "public_observation_pair_comparison",
              "inputA": input_a, "inputB": input_b,
              "comparison": {"finding": finding, "both_contain_multiple_system_prefixes": both_multiple,
                             "both_retain_equal_compatibility_and_unidentified_cause": unresolved,
                             "multiple_system_candidate_set_variants_equal": ma["candidate_set_variants"] == mb["candidate_set_variants"] if both_multiple else None,
                             "observation_file_bytes_identical": bytes_a == bytes_b,
                             "comparison_is_causal_identification": False, "independent_statistical_trials_claimed": False},
              "limitations": LIMITS}
    for name in SOURCE_NAMES:
        if (project / name).read_bytes() != source_bytes[name]:
            raise ValueError(f"Contributing source changed during comparison: {name}")
    if args.observations_a.read_bytes() != bytes_a or args.observations_b.read_bytes() != bytes_b:
        raise ValueError("Explicit observation input changed before publication")
    args.output.mkdir(parents=True, exist_ok=False)
    archive_paths = {}
    for name, data in source_bytes.items():
        target = args.output / "executed-source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        archive_paths[name] = target.relative_to(args.output).as_posix()
    write_json(args.output / "comparison.json", report)
    (args.output / "comparison.md").write_text(markdown(report), encoding="utf-8", newline="\n")
    provenance = {"created_utc": datetime.now(timezone.utc).isoformat(),
                  "purpose": "Two explicit public inputs only; prefix replay, no private labels or native I/O",
                  "command_arguments": sys.argv[1:],
                  "inputs": {label: report[label]["input_provenance"] for label in ("inputA", "inputB")},
                  "source_sha256": {name: digest(data) for name, data in source_bytes.items()},
                  "executed_source_archives": archive_paths,
                  "artifact_sha256": {name: digest((args.output / name).read_bytes()) for name in ("comparison.json", "comparison.md")}}
    write_json(args.output / "provenance.json", provenance)
    print(json.dumps({"output": str(args.output.resolve()), "samples": {label: report[label]["input_provenance"]["samples"] for label in ("inputA", "inputB")},
                      "comparison": report["comparison"]}))


if __name__ == "__main__":
    main()
