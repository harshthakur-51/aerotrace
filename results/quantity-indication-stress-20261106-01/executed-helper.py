"""Development replay substitutions. The simulator and its recording are unchanged."""
import copy
import hashlib
import json
from pathlib import Path

from aircraft_debugger.airborne_profile import iter_profile_observations
from aircraft_debugger.diagnosis import _sources, analyze_diagnosis
from aircraft_debugger.hypotheses import pressure_supply_model


PARENT = Path("results/pressure-v2-native-20261103-01/pump-only/observations.jsonl")
OUT = Path("results/quantity-indication-stress-20261106-01")
SUBSTITUTIONS = {
    "early_quantity_decline": {17: 7.75, 18: 7.4, 19: 7.1, **dict.fromkeys(range(20, 43), 6.8)},
    "late_quantity_decline": {30: 7.75, 31: 7.4, 32: 7.1, **dict.fromkeys(range(33, 43), 6.8)},
}
EXPECTED = {
    "original": ("blue_pressure_supply_loss", "blue_pressure_supply_loss"),
    "early_quantity_decline": ("blue_inventory_loss", "blue_inventory_loss"),
    "late_quantity_decline": ("blue_inventory_loss", None),
}


def main():
    raw = PARENT.read_bytes()
    original = list(iter_profile_observations(PARENT))
    OUT.mkdir()
    results = []
    for name, replacements in {"original": {}, **SUBSTITUTIONS}.items():
        rows = copy.deepcopy(original)
        for row in rows:
            index = row["sample_index"]
            if index in replacements:
                row["readings"]["blue_quantity"]["value"] = replacements[index]
        path = PARENT
        if replacements:
            path = OUT / (name + ".jsonl")
            with path.open("x", encoding="utf-8", newline="\n") as stream:
                for row in rows:
                    stream.write(json.dumps(row, allow_nan=False, separators=(",", ":")) + "\n")
        for mode_index, temporal in enumerate((False, True)):
            report = analyze_diagnosis(iter_profile_observations(path), temporal=temporal,
                                       model=pressure_supply_model())
            result = report["diagnosis"]
            expected = EXPECTED[name][mode_index]
            results.append({
                "variant": name, "mode": "temporal" if temporal else "dependency",
                "public_file": path.as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "expected_candidate_ids": [expected] if expected else [],
                "actual_candidate_ids": result["candidate_ids"], "status": result["status"],
                "data_sufficiency": result["data_sufficiency"]["status"],
                "inventory_before_pressure": report["temporal_relations"]["inventory_before_pressure"],
                "incident_impact": report["observed_impact"],
                "matches_prediction": (result["candidate_ids"] == ([expected] if expected else [])
                                       and (expected is not None or result["status"] == "poor_model_fit")),
            })
    assert PARENT.read_bytes() == raw
    sources = _sources()
    for name, contents in sources.items():
        path = OUT / "executed-source" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
    (OUT / "executed-helper.py").write_bytes(Path(__file__).read_bytes())
    value = {
        "data_role": "development software substitutions of one native pump-only recording",
        "parent_sha256": hashlib.sha256(raw).hexdigest(), "parent_samples": len(original),
        "substituted_channel": "blue_quantity", "substitutions_by_sample": SUBSTITUTIONS,
        "source_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in sources.items()},
        "results": results,
    }
    (OUT / "stress-results.json").write_text(json.dumps(value, indent=2, allow_nan=False) + "\n",
                                             encoding="utf-8", newline="\n")
    print(json.dumps([{k: r[k] for k in ("variant", "mode", "actual_candidate_ids",
                                         "status", "matches_prediction")} for r in results]))
    if not all(result["matches_prediction"] for result in results):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
