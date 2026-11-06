"""Seal and score a bounded diagnostic-profile evaluation protocol.

Private targets are consumed only AFTER prediction. The scorer never calls the
diagnoser. Targets describe expected configurations in our finite catalogue, not
unique physical initiating causes, pilot benefit or real-aircraft accuracy.
"""

import argparse
import hashlib
import json
from pathlib import Path

from .diagnosis import _sources, _write_json
from .airborne_profile import iter_profile_observations
from .evidence import THRESHOLDS
from .hypotheses import default_model, pressure_supply_model


PROFILES = {
    "reference": ["selected_reference"],
    "source_path": ["generator_2_source_path_fault"],
    "blue_inventory": ["blue_inventory_loss"],
    "joint_selected_effects": ["independent_pair", "grouped_joint_event"],
}

_PROTOCOL_SPECS = {
    "bounded_candidate_profile_v1": (default_model, PROFILES),
    "bounded_candidate_profile_v2": (pressure_supply_model, {
        **PROFILES,
        "pressure_supply": ["blue_pressure_supply_loss"],
        "joint_pressure_effects": ["independent_pressure_pair", "grouped_pressure_joint_event"],
    }),
}
_TEMPORAL_METHOD = "dependency_compatibility_with_temporal_constraints"


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def canonical_observation_hash(records):
    """Encoding-independent hash of validated public rows, not independence proof."""
    digest = hashlib.sha256()
    for row in records:
        digest.update((json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8"))
    return digest.hexdigest()


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def make_protocol(development_runs, inference_hashes, scorer_hash, planned_final_runs=None, *, model_version="v1"):
    """Pure protocol constructor; run membership is declared, not authenticated."""
    kind = f"bounded_candidate_profile_{model_version}"
    if kind not in _PROTOCOL_SPECS:
        raise ValueError("Unsupported protocol model version")
    model_factory, profiles = _PROTOCOL_SPECS[kind]
    if not isinstance(development_runs, list) or not development_runs:
        raise ValueError("Register known whole development runs before sealing")
    groups, hashes, canonicals, run_ids = set(), set(), set(), set()
    for run in development_runs:
        if (not isinstance(run, dict) or set(run) != {"run_id", "flight_group", "observation_sha256", "canonical_observations_sha256"}
                or not isinstance(run["run_id"], str) or not run["run_id"]
                or not isinstance(run["flight_group"], str) or not run["flight_group"]
                or not _sha(run["observation_sha256"]) or not _sha(run["canonical_observations_sha256"])):
            raise ValueError("Development run needs run_id, flight_group and raw/canonical observation hashes")
        if run["observation_sha256"] in hashes or run["canonical_observations_sha256"] in canonicals or run["run_id"] in run_ids:
            raise ValueError("Duplicate development run ID or raw/canonical observations")
        hashes.add(run["observation_sha256"])
        canonicals.add(run["canonical_observations_sha256"])
        run_ids.add(run["run_id"])
        groups.add(run["flight_group"])
    if not isinstance(inference_hashes, dict) or not inference_hashes or not all(_sha(value) for value in inference_hashes.values()) or not _sha(scorer_hash):
        raise ValueError("Source hashes required")
    plan = [] if planned_final_runs is None else planned_final_runs
    if not isinstance(plan, list):
        raise ValueError("Planned final runs must be a list")
    planned_ids = set()
    for run in plan:
        if (not isinstance(run, dict) or set(run) != {"run_id", "flight_group", "profile"}
                or any(not isinstance(run[key], str) or not run[key] for key in run)
                or run["profile"] not in profiles or run["run_id"] in planned_ids
                or run["flight_group"] in groups
                or any(item["run_id"] == run["run_id"] for item in development_runs)):
            raise ValueError("Final plan needs unique new run IDs/groups and a predeclared profile")
        planned_ids.add(run["run_id"])
    body = {"schema_version": 1, "protocol_type": kind,
        "model": model_factory(), "detector_thresholds": dict(THRESHOLDS),
        "profile_targets": profiles, "inference_source_sha256": dict(inference_hashes),
        "scorer_sha256": scorer_hash, "development_runs": development_runs,
        "development_flight_groups": sorted(groups), "planned_final_runs": plan,
        "target_semantics": "Expected compatible configurations within the declared model, not unique physical cause ground truth",
        "final_evaluation_requires_new_whole_run_and_flight_group": True,
        "independence_guaranteed": False,
        "rules": ["No model/scorer tuning on final runs; changes require a new protocol and new final data",
                  "Unknown observations remain explicit; do not silently remove insufficient runs",
                  "Joint recipes require both observationally equivalent histories, never a unique initiating label",
                  "Flight groups are operator declarations; metadata alone cannot establish experimental independence"]}
    if model_version == "v2":
        body["prediction_method"] = _TEMPORAL_METHOD
    # Round-trip detaches caller-owned lists and the shared profile constants.
    body = json.loads(json.dumps(body))
    return {**body, "protocol_sha256": _digest(body)}


def validate_protocol(protocol):
    if not isinstance(protocol, dict) or "protocol_sha256" not in protocol:
        raise ValueError("Sealed protocol required")
    body = {key: value for key, value in protocol.items() if key != "protocol_sha256"}
    if _digest(body) != protocol["protocol_sha256"]:
        raise ValueError("Protocol digest mismatch")
    kind = protocol.get("protocol_type")
    if type(protocol.get("schema_version")) is not int or protocol["schema_version"] != 1 or not isinstance(kind, str) or kind not in _PROTOCOL_SPECS:
        raise ValueError("Unsupported sealed protocol")
    model_factory, profiles = _PROTOCOL_SPECS[kind]
    if protocol.get("profile_targets") != profiles or protocol.get("model") != model_factory() or protocol.get("detector_thresholds") != THRESHOLDS:
        raise ValueError("Protocol differs from this model, profiles or detector; use its archived implementation")
    if kind == "bounded_candidate_profile_v2" and protocol.get("prediction_method") != _TEMPORAL_METHOD:
        raise ValueError("Version 2 protocol requires the sealed temporal method")
    return profiles


def score_prediction(report, provenance, target, protocol):
    """Pure post-prediction scoring. No inference, file, network or simulator I/O."""
    profiles = validate_protocol(protocol)
    required = {"schema_version", "run_id", "flight_group", "observation_sha256", "profile", "data_role", "canonical_observations_sha256"}
    if (not isinstance(target, dict) or set(target) != required or type(target["schema_version"]) is not int
            or target["schema_version"] != 1 or not isinstance(target["profile"], str) or target["profile"] not in profiles
            or not isinstance(target["data_role"], str) or target["data_role"] not in {"development", "final"}
            or not _sha(target["observation_sha256"]) or not _sha(target["canonical_observations_sha256"])
            or any(not isinstance(target[key], str) or not target[key] for key in ("run_id", "flight_group"))):
        raise ValueError("Invalid bounded-profile target contract")
    if target["data_role"] == "final":
        if any(run["observation_sha256"] == target["observation_sha256"] or run["canonical_observations_sha256"] == target["canonical_observations_sha256"] or run["run_id"] == target["run_id"] for run in protocol["development_runs"]):
            raise ValueError("Known development run cannot be final evaluation")
        if target["flight_group"] in protocol["development_flight_groups"]:
            raise ValueError("Development flight group cannot be split into final evaluation")
        assignment = {key: target[key] for key in ("run_id", "flight_group", "profile")}
        if assignment not in protocol["planned_final_runs"]:
            raise ValueError("Final run/profile/group was not declared before sealing")
    if (report.get("report_type") != "aerotrace_causal_diagnosis" or report.get("model") != protocol["model"]
            or provenance.get("source_sha256") != protocol["inference_source_sha256"]):
        raise ValueError("Prediction model or executed inference sources differ from sealed protocol")
    if "prediction_method" in protocol and report.get("method") != protocol["prediction_method"]:
        raise ValueError("Prediction method differs from sealed protocol")
    if (provenance.get("observation_file_sha256") != target["observation_sha256"]
            or report.get("input_provenance", {}).get("observation_file_sha256") != target["observation_sha256"]
            or provenance.get("verified_canonical_observations_sha256") != target["canonical_observations_sha256"]):
        raise ValueError("Target and prediction must refer to the same whole observation file")
    result = report["diagnosis"]
    if result.get("cause_identifiable") is not False or result.get("probabilities_computed") is not False:
        raise ValueError("Unexpected physical-cause or probability assertion")
    expected = set(profiles[target["profile"]])
    actual = set(result["candidate_ids"])
    sufficient = result["data_sufficiency"]["status"] == "sufficient"
    return {"schema_version": 1, "run_id": target["run_id"], "flight_group": target["flight_group"],
        "data_role": target["data_role"], "protocol_sha256": protocol["protocol_sha256"],
        "observation_sha256": target["observation_sha256"], "profile": target["profile"],
        "expected_compatible_ids": sorted(expected), "observed_compatible_ids": sorted(actual),
        "plausible_ids": result["plausible_candidate_ids"], "diagnosis_status": result["status"],
        "data_sufficiency": result["data_sufficiency"], "model_fit": result["model_fit"],
        "exact_bounded_profile_match": (actual == expected) if sufficient else None,
        "assessment": ("matched_bounded_profile" if actual == expected else "bounded_profile_mismatch") if sufficient else "insufficient_observations",
        "expected_ids_not_compatible": sorted(expected - actual), "extra_compatible_ids": sorted(actual - expected),
        "current_impact": report["current_impact"], "incident_impact": report["observed_impact"],
        "sample_count": report["sample_count"], "physical_cause_accuracy_measured": False,
        "independent_trials_claimed": False, "target_semantics": protocol["target_semantics"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    seal = sub.add_parser("seal")
    seal.add_argument("--development-runs", type=Path, required=True, help="Explicit JSON registry: run_id, flight_group and observations path")
    seal.add_argument("--planned-final-runs", type=Path, help="Predeclared new run IDs, flight groups and bounded profiles")
    seal.add_argument("--model", choices=("v1", "v2"), default="v1", help="Seal an explicit diagnostic model version")
    seal.add_argument("--output", type=Path, required=True, help="New protocol directory")
    score = sub.add_parser("score")
    score.add_argument("--protocol", type=Path, required=True, help="Sealed protocol directory")
    score.add_argument("--prediction", type=Path, required=True, help="Existing diagnosis CLI output directory")
    score.add_argument("--observations", type=Path, required=True, help="Exact public input used by the prediction, for raw/canonical integrity checks")
    score.add_argument("--target", type=Path, required=True, help="Evaluator-only bounded-profile target JSON")
    score.add_argument("--output", type=Path, required=True, help="New score JSON file")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output must be new; refusing overwrite")
    try:
        scorer = Path(__file__).read_bytes()
        if args.command == "seal":
            sources = _sources()
            runs = json.loads(args.development_runs.read_text(encoding="utf-8"))
            normalized = []
            for run in runs:
                if not isinstance(run, dict) or set(run) != {"run_id", "flight_group", "observations"}:
                    raise ValueError("Development registry needs run_id, flight_group and explicit observations path")
                path = Path(run["observations"])
                raw = path.read_bytes()
                canonical = canonical_observation_hash(iter_profile_observations(path))
                if path.read_bytes() != raw:
                    raise ValueError("Development input changed during sealing")
                normalized.append({"run_id": run["run_id"], "flight_group": run["flight_group"],
                    "observation_sha256": hashlib.sha256(raw).hexdigest(), "canonical_observations_sha256": canonical})
            plan = json.loads(args.planned_final_runs.read_text(encoding="utf-8")) if args.planned_final_runs else None
            protocol = make_protocol(normalized, {key: hashlib.sha256(value).hexdigest() for key, value in sources.items()},
                                     hashlib.sha256(scorer).hexdigest(), plan, model_version=args.model)
            args.output.mkdir(parents=True, exist_ok=False)
            _write_json(args.output / "protocol.json", protocol)
            for name, payload in {**sources, "aircraft_debugger/evaluation.py": scorer}.items():
                path = args.output / "executed-source" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
            print(f"Sealed {len(runs)} declared development runs; no final run has been scored")
        else:
            protocol = json.loads((args.protocol / "protocol.json").read_text(encoding="utf-8"))
            if hashlib.sha256(scorer).hexdigest() != protocol["scorer_sha256"]:
                raise ValueError("Scorer source differs from seal; execute its archived implementation")
            report = json.loads((args.prediction / "report.json").read_text(encoding="utf-8"))
            provenance = json.loads((args.prediction / "provenance.json").read_text(encoding="utf-8"))
            for name, digest in provenance["artifact_sha256"].items():
                relative = Path(name)
                if relative.is_absolute() or not (args.prediction / relative).resolve().is_relative_to(args.prediction.resolve()):
                    raise ValueError("Prediction artifact path escapes its directory")
                if hashlib.sha256((args.prediction / relative).read_bytes()).hexdigest() != digest:
                    raise ValueError("Prediction artifact hash mismatch")
            if "report.json" not in provenance["artifact_sha256"]:
                raise ValueError("Prediction report digest required")
            for name, digest in provenance["source_sha256"].items():
                relative = Path(provenance["executed_source_archives"][name])
                if relative.is_absolute() or not (args.prediction / relative).resolve().is_relative_to(args.prediction.resolve()):
                    raise ValueError("Prediction source archive path escapes its directory")
                if hashlib.sha256((args.prediction / relative).read_bytes()).hexdigest() != digest:
                    raise ValueError("Prediction source archive digest mismatch")
            raw = args.observations.read_bytes()
            if hashlib.sha256(raw).hexdigest() != provenance["observation_file_sha256"]:
                raise ValueError("Public observations do not match prediction")
            provenance["verified_canonical_observations_sha256"] = canonical_observation_hash(iter_profile_observations(args.observations))
            if args.observations.read_bytes() != raw:
                raise ValueError("Public observations changed during scoring")
            target = json.loads(args.target.read_text(encoding="utf-8"))
            value = score_prediction(report, provenance, target, protocol)
            with args.output.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(value, stream, indent=2, allow_nan=False)
                stream.write("\n")
            print(value["assessment"] + ": " + value["data_role"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"AeroTrace evaluation failed: {exc}\n")


if __name__ == "__main__":
    main()
