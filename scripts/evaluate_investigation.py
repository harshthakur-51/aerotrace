"""Compare released v1.2 and active v1.3 using identical public observation files."""

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import platform
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "configs/investigation-evaluation.json"
NATIVE = ROOT / "results/v1.3-investigation-20261107-01/native-independent-pair/observations.jsonl"
_WORKER = """
from hashlib import sha256
import gc
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter
import tracemalloc

sys.path.insert(0, str(Path.cwd()))
from aircraft_debugger.airborne_profile import iter_profile_observations
from aircraft_debugger.sequence_reasoning import analyze_sequences

path, bounds, repetitions = sys.argv[1:]
path = Path(path)
digest = sha256(path.read_bytes()).hexdigest()
rows = list(iter_profile_observations(path))
bounds = json.loads(bounds)
repetitions = int(repetitions)
times = []
for _ in range(repetitions):
    gc.collect()
    started = perf_counter()
    analyze_sequences(rows, response_bounds=bounds)
    times.append(perf_counter() - started)
if repetitions:
    gc.collect()
    tracemalloc.start()
report = analyze_sequences(rows, response_bounds=bounds)
peak = tracemalloc.get_traced_memory()[1] if repetitions else None
tracemalloc.stop()
epoch, = report["epochs"]
investigation = epoch.pop("investigation", None)
epoch.pop("investigation_context", None)
viable = {item["id"]: item for item in epoch["mechanism_sets"]
          if item["history_counts"]["compatible"] or item["history_counts"]["unconfirmed"]}
result = {
    "input_sha256": digest,
    "fit_sha256": sha256(json.dumps(epoch, sort_keys=True).encode()).hexdigest(),
    "samples": len(rows), "median_wall_s": median(times) if times else None,
    "python_peak_bytes": peak, "history_counts": epoch["history_counts"],
    "surviving_sets": {name: item["roots"] for name, item in viable.items()},
    "minimal_possible_sets": epoch["minimal_possible_mechanism_sets"],
    "physical_cause_identifiable": report["physical_cause_identifiable"],
}
if investigation:
    from aircraft_debugger.hypotheses import generated_model
    from aircraft_debugger.investigation import evaluate_counterfactual

    model = generated_model()
    restrictions = [{"only": item["roots"]} for item in epoch["mechanism_sets"]]
    restrictions += [{"exclude": [root]} for root in model["roots"]]
    checked = 0
    for restriction in restrictions:
        answer = evaluate_counterfactual(epoch, model, **restriction)
        expected = [item["id"] for item in viable.values()
                    if (item["roots"] == restriction["only"] if "only" in restriction
                        else restriction["exclude"][0] not in item["roots"])]
        surviving = [item["id"] for item in answer["surviving_explanations"]]
        checked += surviving == expected
    common = investigation["common_cause"]
    result.update({
        "observed": [item["fact"] for item in investigation["observed_abnormalities"]],
        "evidence": investigation["evidence_selection"],
        "possibly_masked": [item["mechanism"] for item in investigation["masking"]["potentially_masked_mechanisms"]],
        "cluster_statuses": [cluster["status"] for cluster in common["clusters"]],
        "unmodelled_common_cause_possibilities": sum(cluster["unmodelled_common_cause_possible"]
                                                  for cluster in common["clusters"]),
        "physical_initiators_claimed": sum(cluster["physical_initiator"] != "unknown"
                                           for cluster in common["clusters"]),
        "model_mismatch": common["model_mismatch"]["status"],
        "unexplained_observations": common["model_mismatch"]["unexplained_observations"],
        "counterfactual_checks": {"agreed": checked, "total": len(restrictions)},
    })
if digest != sha256(path.read_bytes()).hexdigest():
    raise ValueError("Public input changed during evaluation")
print(json.dumps(result))
"""


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _digest(path):
    return sha256(path.read_bytes()).hexdigest()


def _source_hashes(checkout):
    paths = [*checkout.joinpath("aircraft_debugger").glob("*.py"),
             checkout / "aircraft_debugger/assets/sim-panel.html"]
    return {str(path.relative_to(checkout)).replace("\\", "/"): _digest(path) for path in sorted(paths)}


def _write_rows(path, rows):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def _held_out_rows(seed, capture, profiles):
    """Create measurement envelopes without importing the detector or cause graph."""
    tick = 0.0
    for index in range(200):
        if tick > capture["duration_s"]:
            break
        sim_time = round(capture["time_origin_sim_s"] + tick, 5)
        start = round(20000 + tick, 5)
        row = deepcopy(seed)
        row.update(sample_index=index, poll_started_monotonic_s=start, received_monotonic_s=start + 0.08)
        for name, reading in row["readings"].items():
            reading.update(sim_time_s=sim_time, received_monotonic_s=start + 0.04)
            if name in profiles:
                onset, duration, endpoint = profiles[name]
                fraction = min(1, max(0, (tick - onset) / duration))
                reading["value"] = round(reading["value"] * (1 - fraction) + endpoint * fraction, 6)
        row["readings"]["sim_time"]["value"] = sim_time
        yield row
        offsets = capture["offsets_s"]
        tick += offsets[index % len(offsets)]


def _cases(protocol, output, development):
    if development:
        bounds_path = development / "response-bounds.json"
        bounds = _json(bounds_path)
        design = _json(development / "case-design.json")
        if _digest(bounds_path) != design["delay_bounds_sha256"]:
            raise ValueError("Development response bounds differ from the archived design")
        for case in design["cases"]:
            public = development / case["id"] / "observations.jsonl"
            if _digest(public) != case["observation_sha256"]:
                raise ValueError("Development observations differ from the archived design")
            yield {"id": "D" + case["id"], "truth": list(case["onsets"]), "group": "development",
                   "public": public, "bounds": bounds}
    seed_path = ROOT / protocol["seed_recording"]
    if _digest(seed_path) != protocol["seed_sha256"]:
        raise ValueError("Held-out seed differs from the fixed recording")
    with seed_path.open(encoding="utf-8") as stream:
        seed = json.loads(next(stream))
    for case in protocol["held_out"]:
        public = output / (case["id"] + ".jsonl")
        rows = list(_held_out_rows(seed, protocol["synthetic_capture"], case["profiles"]))
        restored = {}
        for channel in case.get("withhold", []):
            path = output / (case["id"] + "-restore-" + channel + ".jsonl")
            subset = [item for item in case["withhold"] if item != channel]
            _write_rows(path, _withheld_rows(rows, subset))
            restored[channel] = path
        _write_rows(public, _withheld_rows(rows, case.get("withhold", [])))
        yield {**case, "group": "held_out_synthetic", "public": public, "bounds": None, "restored": restored}
    if _digest(NATIVE) != _json(NATIVE.with_name("provenance.json"))["observation_sha256"]:
        raise ValueError("Fresh native recording differs from its manifest")
    yield {"id": "N01-independent-native", "group": "fresh_native", "public": NATIVE, "bounds": None,
           "truth": ["generator_2_source_path_fault", "yellow_engine_driven_pump_supply_loss"],
           "independent_control": True}


def _withheld_rows(rows, channels):
    for row in rows:
        if channels:
            row = deepcopy(row)
            row["complete"] = False
            for channel in channels:
                del row["readings"][channel]
        yield row


def _run(checkout, public, bounds, repetitions):
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", _WORKER, str(public.resolve()), json.dumps(bounds), str(repetitions)],
        cwd=checkout, capture_output=True, text=True,
    )
    if result.returncode:
        raise RuntimeError(f"Replay failed for {public.name} in {checkout}:\n{result.stderr}")
    return json.loads(result.stdout)


def _evaluate(case, baseline, repetitions, reverse):
    public, bounds = case["public"], case["bounds"]
    versions = [("v1.2", baseline), ("v1.3", ROOT)]
    if reverse:
        versions.reverse()
    versions = {name: _run(checkout, public, bounds, repetitions) for name, checkout in versions}
    before, after = versions["v1.2"], versions["v1.3"]
    truth = set(case["truth"])
    for result in versions.values():
        survivors = result["surviving_sets"]
        actual = next((name for name, roots in survivors.items() if set(roots) == truth), None)
        result["true_set_retained"] = actual is not None
        result["true_set_minimal"] = actual in result["minimal_possible_sets"]
    outcomes = []
    for test in after["evidence"]["unavailable_discriminators"]:
        channels = test["channels"]
        if len(channels) != 1 or channels[0] not in case.get("restored", {}):
            continue
        restored = _run(ROOT, case["restored"][channels[0]], bounds, 0)
        actual = set(restored["surviving_sets"])
        outcomes.append({
            "channel": channels[0], "restored_sha256": restored["input_sha256"],
            "surviving_sets": sorted(actual),
            "eliminated_by_restoration": len(after["surviving_sets"]) - len(actual),
            "consistent_with_predicted_partitions": bool(actual)
            and any(actual <= set(test["predicted_partitions"][outcome]) for outcome in ("observed", "not_observed")),
        })
    return {
        "case": case["id"], "group": case["group"], "truth": case["truth"],
        "independent_control": case.get("independent_control", False),
        "identical_public_input": before["input_sha256"] == after["input_sha256"],
        "identical_original_fit": before["fit_sha256"] == after["fit_sha256"],
        "restore_experiments": outcomes, **versions,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-checkout", type=Path, required=True)
    parser.add_argument("--development-dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("--repetitions must be positive")
    baseline = args.baseline_checkout.resolve()
    protocol = _json(PROTOCOL)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=baseline, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=baseline, text=True).strip()
    if commit != protocol["baseline_commit"] or dirty:
        parser.error("Expected a clean checkout at the specified public v1.2 commit")
    sources = {"v1.2": _source_hashes(baseline), "v1.3": _source_hashes(ROOT)}
    args.output.mkdir(parents=True, exist_ok=False)
    results = []
    for index, case in enumerate(_cases(protocol, args.output, args.development_dir)):
        result = _evaluate(case, baseline, args.repetitions, reverse=bool(index % 2))
        results.append(result)
        print(case["id"], "input parity", result["identical_public_input"],
              "fit parity", result["identical_original_fit"], flush=True)
    if sources != {"v1.2": _source_hashes(baseline), "v1.3": _source_hashes(ROOT)}:
        raise RuntimeError("Executed source changed during comparison")
    document = {
        "baseline_commit": commit, "protocol_sha256": _digest(PROTOCOL), "python": platform.python_version(),
        "platform": platform.platform(), "repetitions": args.repetitions,
        "executed_source_sha256": sources, "evaluation_script_sha256": _digest(Path(__file__)),
        "timing_scope": "analyze_sequences on preloaded rows, median wall time, alternating version order",
        "memory_scope": "peak traced Python allocations in a separate run, excluding preloaded rows",
        "cases": results,
    }
    (args.output / "comparison.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    if not all(row["identical_public_input"] and row["identical_original_fit"] for row in results):
        raise SystemExit("Original fit or public input differs; see comparison.json")


if __name__ == "__main__":
    main()
