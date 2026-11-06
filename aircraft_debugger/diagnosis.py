"""AeroTrace: public-observation replay through executable causal hypotheses.

The inference API performs no file, network or simulator access. The CLI opens
one explicitly named observation input, archives the executed public model/source
and writes a new report directory. Operator labels never enter inference.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import time

from .airborne_profile import iter_profile_observations
from .candidate_support import evidence_support
from .diagnostic_features import build_feature_frames
from .hypotheses import MODEL_VERSIONS, V4_MODEL_ID, default_model, evaluate_hypotheses, model_for_version, uses_propulsion_profile


def analyze_diagnosis(records, *, temporal: bool = True, model: dict | None = None) -> dict:
    """Explain the latest observed incident, separately from current recovery.

    Temporal/atemporal paths use identical observations, facts and candidates.
    Only the model's qualitative temporal constraints are switched. This first
    bounded implementation replays detector prefixes; it is not a streaming or
    constant-memory performance claim.
    """
    if type(temporal) is not bool:
        raise ValueError("temporal must be Boolean")
    active_model = default_model() if model is None else copy.deepcopy(model)
    propulsion = uses_propulsion_profile(active_model)
    generated = active_model["model_id"] == V4_MODEL_ID
    extracted = build_feature_frames(records, propulsion=propulsion, generated=generated)
    frames = extracted["frames"]
    if not frames:
        raise ValueError("At least one public observation is required")
    timeline = []
    incidents = {}
    diagnosis = None
    for frame in frames:
        diagnosis = evaluate_hypotheses(frame, temporal=temporal, model=active_model)
        timeline.append({
            "sample_index": frame["sample_index"], "epoch": frame["epoch"],
            "sim_time_s": frame["sim_time_s"], "scope": copy.deepcopy(frame["scope"]),
            "status": diagnosis["status"], "candidate_ids": list(diagnosis["candidate_ids"]),
            "plausible_candidate_ids": list(diagnosis["plausible_candidate_ids"]),
            "current_impact": copy.deepcopy(frame["current_impact"]),
        })
        if generated:
            timeline[-1]["minimal_candidate_ids"] = list(diagnosis["minimal_candidate_ids"])
            incident_id = frame["scope"]["incident_id"]
            if incident_id is not None:
                incidents[incident_id] = {
                    "scope": copy.deepcopy(frame["scope"]),
                    "minimal_candidate_ids": list(diagnosis["minimal_candidate_ids"]),
                    "additional_compatible_ids": list(diagnosis["additional_compatible_ids"]),
                    "observed_onsets": {name: copy.deepcopy(fact["onset_interval"]) for name, fact in frame["facts"].items()
                                        if fact["onset_interval"] is not None},
                }
    last = frames[-1]
    observations = extracted["observation_report"]
    report = {
        "schema_version": 1, "report_type": "aerotrace_causal_diagnosis",
        "method": "dependency_compatibility_with_temporal_constraints" if temporal else "dependency_compatibility",
        "sample_count": observations["sample_count"],
        "observation_schema_version": observations["schema_version"],
        "model": active_model, "scope": copy.deepcopy(last["scope"]),
        "diagnosis": diagnosis, "evidence": copy.deepcopy(last["facts"]),
        "temporal_relations": copy.deepcopy(last["temporal_relations"]),
        "current_state": copy.deepcopy(last["current_state"]),
        "current_impact": copy.deepcopy(last["current_impact"]),
        "observed_impact": copy.deepcopy(last["observed_impact"]),
        "event_ledger": copy.deepcopy(observations["ledger"]),
        "observation_context": copy.deepcopy(observations.get("airborne_context", {})),
        "timeline": timeline,
        "input_provenance": copy.deepcopy(observations.get("input_provenance", {})),
        "limitations": [
            "Five bounded candidate configurations reuse two verified native mechanisms; this is not complete aircraft diagnosis." if len(active_model["roots"]) == 2 else "Eight configurations represent three selected mechanism classes; native confirmation and scope are documented separately. This is not complete aircraft diagnosis.",
            "A compatible model candidate is not a uniquely identified physical component failure or calibrated probability.",
            "The grouped joint-event and independent pair have identical observable predictions in this model; no available observation is invented to distinguish them.",
            "Incident-history hypotheses and confirmed incident degradation remain separate from current recovered or unavailable readings.",
            "A valid, advancing quantity indication can still be wrong. Physical fluid loss requires independent corroboration.",
            "The simulator and diagnostic model are related engineering abstractions, not independent real-aircraft validation.",
            "Temporal constraints are qualitative model assumptions; native depletion rates and exact propagation delays are not fitted signatures.",
            "The first offline path uses repeated prefix analysis; computation and memory suitability for a live display require separate measurement.",
        ],
    }
    if propulsion:
        report["limitations"][0] = (
            f"{len(active_model['candidates'])} configurations represent {len(active_model['roots'])} selected mechanism classes."
        )
        report["limitations"][6] = "Temporal checks use declared observation-order and Yellow supply-settling assumptions."
        report["candidate_evidence_support"] = {
            candidate["id"]: evidence_support(candidate) for candidate in diagnosis["candidates"]
        }
    if generated:
        report["limitations"][2] = "An observed set of effects can be compatible with multiple root sets and initiating histories."
        report["incidents"] = list(incidents.values())
    return report


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def _describe(item) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        if "nodes" in item:
            return " -> ".join(item["nodes"]) + f" ({item.get('necessity', 'modeled')}). " + item.get("reason", "")
        if "observation" in item:
            return item["observation"] + " " + item.get("remaining_capability", "") + _references(item.get("evidence", []))
        reason = item.get("reason") or item.get("description") or item.get("explanation")
        if reason:
            prefix = (item["fact"].replace("_", " ") + ": ") if "fact" in item else ""
            channels = item.get("channels") or item.get("available_measurements")
            measurements = " Measurements: " + ", ".join(channels) + "." if channels else ""
            return prefix + str(reason) + measurements + _references(item.get("evidence", []))
    return json.dumps(item, sort_keys=True)


def _references(evidence: list) -> str:
    references = []
    for point in evidence:
        if isinstance(point, dict) and "channel" in point and "sample_index" in point:
            references.append(f"{point['channel']} at sample {point['sample_index']}: {point.get('value')} {point.get('unit', '')}".rstrip())
    return " Evidence: " + "; ".join(references) + "." if references else ""


def _markdown(report: dict) -> str:
    diagnosis = report["diagnosis"]
    lines = ["# AeroTrace causal diagnosis", "", f"Outcome: **{diagnosis['status']}**.",
             f"Public observations: {report['sample_count']}; method: `{report['method']}`.",
             "", "Explanation scope: " + json.dumps(report["scope"], sort_keys=True),
             "", "Compatible model candidates: " + (", ".join(diagnosis["candidate_ids"]) or "none"),
             "Plausible candidates awaiting evidence: " + (", ".join(name for name in diagnosis["plausible_candidate_ids"] if name not in diagnosis["candidate_ids"]) or "none"),
             "", "A surviving model configuration does not establish a unique physical cause or probability."]
    if "incidents" in report:
        labels = {candidate["id"]: candidate["label"] for candidate in diagnosis["candidates"]}
        facts = report["model"]["facts"]
        lines.extend(["", "**Observed incident sequence.**"])
        for incident in report["incidents"]:
            scope = incident["scope"]
            minimal = ", ".join(labels[name] for name in incident["minimal_candidate_ids"]) or "Unresolved"
            status = "closed" if scope["closed"] else "active"
            lines.append(f"- {scope['incident_id']} ({status}). Minimal fit {minimal}. "
                         f"Additional compatible sets {len(incident['additional_compatible_ids'])}.")
            for name, onset in incident["observed_onsets"].items():
                lower = onset["lower_sim_time_s"]
                start = f"{lower:.2f}" if lower is not None else "unknown"
                lines.append(f"  - {facts[name]['label']} observed onset bracket {start} to "
                             f"{onset['upper_sim_time_s']:.2f} simulator seconds.")
    lines.extend(["", "**What could reduce uncertainty.**"])
    discriminators = diagnosis.get("missing_evidence", [])
    lines.extend("- " + _describe(item) for item in discriminators)
    if not discriminators:
        lines.append("No additional selected discriminator is identified for the surviving configuration.")
    lines.extend(["", "**Executable dependency model.** Conditional links permit retained downstream supply.", "", "```mermaid", "flowchart LR"])
    for edge in report["model"]["edges"]:
        lines.append(f"    {edge['from']} -->|{edge['necessity']}| {edge['to']}")
    lines.append("```")
    for title, key in (("Confirmed incident degradation", "observed_impact"), ("Current observed impact", "current_impact")):
        lines.extend(["", f"**{title}.**"])
        lines.extend("- " + _describe(item) for item in report[key])
        if not report[key]:
            lines.append("No selected confirmed impact in this scope; this is not a whole-aircraft health statement.")
    for candidate in diagnosis["candidates"]:
        lines.extend(["", f"**Hypothesis: {candidate.get('label', candidate['id'])}** (`{candidate['id']}`).",
                      f"Status: `{candidate['status']}`."])
        score = report.get("candidate_evidence_support", {}).get(candidate["id"])
        if score and score["percent"] is not None:
            lines.append(f"Evidence support **{score['percent']}%** ({score['supported_checks']} of {score['total_checks']} checks).")
        for title, key in (("Supporting evidence", "supporting_evidence"),
                           ("Contradicting evidence", "contradicting_evidence"),
                           ("Predicted consequences", "predicted_consequences"),
                           ("Possible dependency paths", "dependency_paths"),
                           ("Missing evidence", "missing_evidence")):
            lines.append(f"{title}:")
            values = candidate.get(key, [])
            lines.extend("- " + _describe(item) for item in values)
            if not values:
                lines.append("- None recorded for this candidate.")
        lines.append("Alternative compatible candidates: " + (", ".join(candidate.get("alternative_candidate_ids", [])) or "none"))
    lines.extend(["", "**Diagnostic timeline.**", "", "| Sample | Epoch | Simulator seconds | Status | Compatible candidates |",
                  "|---:|---:|---:|---|---|"])
    for row in report["timeline"]:
        lines.append(f"| {row['sample_index']} | {row['epoch']} | {row['sim_time_s']} | {row['status']} | {', '.join(row['candidate_ids'])} |")
    lines.extend(["", "**Limits.**"])
    lines.extend("- " + item for item in report["limitations"])
    return "\n".join(lines) + "\n"


def _sources() -> dict[str, bytes]:
    root = Path(__file__).resolve().parents[1]
    names = ["__init__", "diagnosis", "diagnostic_features", "hypotheses", "airborne_evidence",
             "airborne_profile", "evidence", "observations", "flightgear", "propulsion_features", "candidate_support"]
    return {f"aircraft_debugger/{name}.py": (root / "aircraft_debugger" / f"{name}.py").read_bytes() for name in names}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="New directory; existing output is refused")
    parser.add_argument("--mode", choices=("temporal", "atemporal"), default="temporal")
    parser.add_argument("--model", choices=MODEL_VERSIONS, default="v1", help="Versions 3 and 4 use the propulsion observation profile")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("--output must name a new directory")
    try:
        original = args.observations.read_bytes()
        source_hash = hashlib.sha256(original).hexdigest()
        executed = _sources()
        rows = list(iter_profile_observations(args.observations))
        started = time.perf_counter()
        report = analyze_diagnosis(rows, temporal=args.mode == "temporal", model=model_for_version(args.model))
        duration = time.perf_counter() - started
        if args.observations.read_bytes() != original or _sources() != executed:
            raise ValueError("Observation input or executed source changed during replay")
    except (OSError, ValueError) as error:
        parser.exit(1, f"AeroTrace replay failed: {error}\n")
    report["input_provenance"].update({
        "observation_file_sha256": source_hash,
        "input_access": "Only the explicitly named public observation input enters inference; no manifests, private labels or native simulator access",
    })
    args.output.mkdir(parents=True, exist_ok=False)
    _write_json(args.output / "report.json", report)
    (args.output / "report.md").write_text(_markdown(report), encoding="utf-8", newline="\n")
    _write_json(args.output / "timeline.json", report["timeline"])
    _write_json(args.output / "model.json", report["model"])
    hashes, archives = {}, {}
    for name, payload in executed.items():
        relative = Path("executed-source") / name
        path = args.output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        hashes[name] = hashlib.sha256(payload).hexdigest()
        archives[name] = relative.as_posix()
    project = Path(__file__).resolve().parents[1]
    try:
        repository = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=project, stderr=subprocess.DEVNULL).decode().strip()
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=project, stderr=subprocess.DEVNULL).decode().strip() if Path(repository).resolve() == project else None
    except (OSError, subprocess.CalledProcessError):
        commit = None
    _write_json(args.output / "provenance.json", {
        "purpose": "AeroTrace public-input causal replay; private truth is never diagnostic evidence",
        "observation_file_sha256": source_hash, "samples": report["sample_count"],
        "mode": args.mode, "source_commit_before_run": commit,
        "source_sha256": hashes, "executed_source_archives": archives,
        "artifact_sha256": {name: hashlib.sha256((args.output / name).read_bytes()).hexdigest()
                            for name in ("report.json", "report.md", "timeline.json", "model.json")},
        "complete_replay_computation_local_s": duration,
        "timing_scope": "Entire offline prefix replay on this machine; not per-update streaming latency or a performance benchmark",
    })
    print(f"{report['diagnosis']['status']}: {', '.join(report['diagnosis']['candidate_ids']) or 'no compatible candidate'}; {args.output.resolve()}")


if __name__ == "__main__":
    main()
