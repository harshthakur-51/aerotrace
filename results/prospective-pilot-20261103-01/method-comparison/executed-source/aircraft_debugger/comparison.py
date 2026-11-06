"""Fair development comparison on explicit public observation recordings.

This is a method ablation, not an accuracy benchmark. All methods see identical
incident facts and catalogue. Alert-only reports observed effects without inferring
causes. The two dependency methods differ only in temporal constraint evaluation.
"""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import time

from .airborne_profile import iter_profile_observations
from .diagnosis import _sources, _write_json
from .diagnostic_features import build_feature_frames
from .hypotheses import default_model, evaluate_hypotheses


def _compact(result):
    keys = ("status", "candidate_ids", "plausible_candidate_ids", "data_sufficiency",
            "model_fit", "ambiguity", "cause_identifiable", "probabilities_computed")
    return {**{key: copy.deepcopy(result[key]) for key in keys},
        "candidate_outcomes": [{"id": item["id"], "status": item["status"],
            "contradicting_evidence": copy.deepcopy(item["contradicting_evidence"])}
            for item in result["candidates"]]}


def compare_methods(records, *, model=None):
    """Pure, deterministic comparison. No private truth, labels or I/O."""
    active_model = default_model() if model is None else copy.deepcopy(model)
    frames = build_feature_frames(records)["frames"]
    timeline = []
    changed = []
    for frame in frames:
        facts = frame["facts"]
        observed = [key for key, fact in facts.items() if fact["state"] == "observed"]
        unknown = [key for key, fact in facts.items() if fact["state"] == "unknown"]
        alert = {"status": "selected_anomalies_observed" if observed else
                 "insufficient_observations" if unknown else "no_selected_anomaly",
                 "observed_fact_ids": observed, "unknown_fact_ids": unknown,
                 "candidate_ids": None, "cause_inference": "not_performed",
                 "scope": "Incident/window facts shared with both dependency methods; not a separate detector benchmark."}
        static = _compact(evaluate_hypotheses(frame, temporal=False, model=active_model))
        temporal = _compact(evaluate_hypotheses(frame, temporal=True, model=active_model))
        if any(static[key] != temporal[key] for key in ("status", "candidate_ids", "plausible_candidate_ids")):
            changed.append(frame["sample_index"])
        timeline.append({"sample_index": frame["sample_index"], "sim_time_s": frame["sim_time_s"],
            "epoch": frame["epoch"], "scope": copy.deepcopy(frame["scope"]),
            "shared_facts": copy.deepcopy(facts),
            "shared_current_impact": copy.deepcopy(frame["current_impact"]),
            "shared_incident_impact": copy.deepcopy(frame["observed_impact"]),
            "shared_temporal_relations": copy.deepcopy(frame["temporal_relations"]),
            "methods": {"alert_only": alert, "dependency": static, "temporal_dependency": temporal}})
    return {"schema_version": 1, "report_type": "aerotrace_development_method_comparison",
        "purpose": "Development ablation; no locked evaluation or physical-cause accuracy claim",
        "model": active_model, "sample_count": len(frames), "timeline": timeline,
        "summary": {"final_methods": copy.deepcopy(timeline[-1]["methods"]),
            "temporal_changed_sample_indices": changed,
            "temporal_changed_prefix_count": len(changed),
            "counts_are_independent_trials": False,
            "accuracy_measured": False, "probabilities_computed": False},
        "comparison_contract": {
            "shared_feature_extraction_passes": 1, "same_observations_and_incident_scope": True,
            "same_finite_catalogue": True, "same_detector_thresholds": True,
            "timing_ablation_changes_only_model_temporal_constraints": True,
            "atemporal_preserves_timestamp_quality_and_incident_bookkeeping": True,
            "alert_only_does_not_invent_candidate_sets_or_receive_diagnostic_credit": True},
        "limitations": [
            "Alert-only uses the same history-aware facts; it measures the added causal layer, not raw cockpit alert latency.",
            "A null alert-only candidate set means inference was not performed, not that every or no cause was identified.",
            "A changed temporal result is a model-consistency difference, not evidence of improved physical accuracy.",
            "Known development recordings and correlated prefixes are not untouched evaluation runs or independent trials.",
            "Private recipe labels cannot distinguish equivalent independent and grouped initiating histories.",
        ]}


def _markdown(cases):
    lines = ["# AeroTrace development method comparison", "",
        "Identical extracted facts/catalogue; only model temporal constraints change between dependency methods.",
        "Alert-only reports effects and performs no cause inference. These are development replays, not accuracy scores.", "",
        "| Explicit input | Polls | Final dependency | Final temporal | Prefixes with changed result |",
        "|---|---:|---|---|---:|"]
    for case in cases:
        report = case["report"]
        final = report["summary"]["final_methods"]
        def verdict(method):
            value = final[method]
            return value["status"] + ": " + (", ".join(value["candidate_ids"]) or "none compatible")
        lines.append(f"| {case['input']} | {report['sample_count']} | {verdict('dependency')} | {verdict('temporal_dependency')} | {report['summary']['temporal_changed_prefix_count']} |")
    lines.extend(["", "Changed-prefix counts describe correlated views of whole recordings, not independent successes.",
        "Zero changes must be reported as no observed discrimination gain on that input, not concealed.",
        "The saved model, shared facts and candidate contradictions make each method comparison inspectable.",
        "No hidden/private truth, injected physical-cause label or ground-truth scoring enters this command.", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", type=Path, nargs="+", required=True,
                        help="Whole public recording files; each analyzed separately")
    parser.add_argument("--output", type=Path, required=True, help="New directory only")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("--output must name a new directory")
    if len({path.resolve() for path in args.observations}) != len(args.observations):
        parser.error("Each whole recording may appear only once")
    try:
        originals = {path: path.read_bytes() for path in args.observations}
        sources = {**_sources(), "aircraft_debugger/comparison.py": Path(__file__).read_bytes()}
        started = time.perf_counter()
        cases = [{"input": str(path), "input_sha256": hashlib.sha256(originals[path]).hexdigest(),
                  "report": compare_methods(iter_profile_observations(path))} for path in args.observations]
        duration = time.perf_counter() - started
        if any(path.read_bytes() != payload for path, payload in originals.items()):
            raise ValueError("Observation input changed during comparison")
        current_sources = {**_sources(), "aircraft_debugger/comparison.py": Path(__file__).read_bytes()}
        if current_sources != sources:
            raise ValueError("Executed source changed during comparison")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"AeroTrace comparison failed: {exc}\n")
    args.output.mkdir(parents=True, exist_ok=False)
    _write_json(args.output / "comparison.json", {"purpose": "Development only; no accuracy score", "cases": cases})
    (args.output / "comparison.md").write_text(_markdown(cases), encoding="utf-8", newline="\n")
    for name, payload in sources.items():
        target = args.output / "executed-source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    _write_json(args.output / "provenance.json", {
        "inputs": [{"path": str(path), "sha256": hashlib.sha256(payload).hexdigest()} for path, payload in originals.items()],
        "source_sha256": {name: hashlib.sha256(payload).hexdigest() for name, payload in sources.items()},
        "artifact_sha256": {name: hashlib.sha256((args.output / name).read_bytes()).hexdigest()
                            for name in ("comparison.json", "comparison.md")},
        "whole_comparison_local_s": duration,
        "timing_scope": "Shared feature extraction and both methods for whole files; not streaming or method speed ranking",
        "evaluation_split": "Development recordings only; no final holdout claimed"})
    print(f"Compared {len(cases)} whole development recordings; {args.output.resolve()}")


if __name__ == "__main__":
    main()
