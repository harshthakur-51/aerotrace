"""Read-only release checks using native captures and the original stress inputs."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
from aircraft_debugger.airborne_profile import iter_profile_observations
from aircraft_debugger.sequence_reasoning import analyze_sequences
from aircraft_debugger.investigation import evaluate_counterfactual
from aircraft_debugger.hypotheses import generated_model

GEN = "generator_2_source_path_fault"
ENGINE = "engine_2_power_loss"
YELLOW = "yellow_engine_driven_pump_supply_loss"
BLUE = "blue_pressure_supply_loss"
LEAK = "blue_fluid_loss_mechanism"
model = generated_model()
checks = []
samples = []

def check(condition, name):
    checks.append({"check": name, "passed": bool(condition)})
    if not condition:
        print("FAILED", name, flush=True)

def viable(epoch):
    return {item["id"] for item in epoch["mechanism_sets"]
            if item["history_counts"]["compatible"] or item["history_counts"]["unconfirmed"]}

def run(name, rows, bounds=None):
    report = analyze_sequences(rows, response_bounds=bounds)
    check(all(sum(epoch["history_counts"].values()) == 1082 for epoch in report["epochs"]),
          name + " accounts for every catalogue history")
    return report

native_paths = {
    "native-engine": "results/engine-drive-20261106-01/engine-auto/observations.jsonl",
    "native-independent-pair": "results/engine-drive-20261106-01/pair-auto/observations.jsonl",
    "native-local-yellow": "results/yellow-edp-isolated-20261106-01/run/observations.jsonl",
    "fresh-independent-pair": "results/v1.3-investigation-20261107-01/native-independent-pair/observations.jsonl",
}
expected = {
    "native-engine": [ENGINE],
    "native-independent-pair": [GEN + "+" + YELLOW],
    "native-local-yellow": [YELLOW],
    "fresh-independent-pair": [GEN + "+" + YELLOW],
}
for name, relative in native_paths.items():
    path = ROOT / relative
    digest = sha256(path.read_bytes()).hexdigest()
    rows = list(iter_profile_observations(path))
    report = run(name, rows)
    epoch, = report["epochs"]
    baseline = viable(epoch)
    check(epoch["minimal_possible_mechanism_sets"] == expected[name], name + " expected minimal sets")
    for channels in (
        ("engine_2_n2", "engine_2_fuel_flow"),
        ("generator_2_voltage",),
        ("yellow_edp_pressure",),
        ("blue_quantity",),
        ("blue_pressure",),
    ):
        withheld = deepcopy(rows)
        for row in withheld:
            for channel in channels:
                row["readings"].pop(channel, None)
            row["complete"] = False
        absent, = run(name + " withheld " + "/".join(channels), withheld)["epochs"]
        check(baseline <= viable(absent), name + " withholding cannot eliminate an existing fit " + "/".join(channels))
        actions = absent["investigation"]["evidence_selection"]["recommended_measurements"]
        check(not any(set(item["channels"]) & set(channels) for item in actions),
              name + " absent channels never actionable " + "/".join(channels))
    gappy = rows[:8] + rows[9:]
    gap_epoch, = run(name + " gap", gappy)["epochs"]
    check(baseline <= viable(gap_epoch), name + " observation gap preserves original root sets")
    healthy, = run(name + " nominal-prefix", rows[:10])["epochs"]
    check(healthy["minimal_possible_mechanism_sets"] == ["selected_reference"], name + " nominal prefix")
    check(not healthy["investigation"]["observed_abnormalities"], name + " nominal prefix has no abnormal effects")
    check(path.read_bytes() and sha256(path.read_bytes()).hexdigest() == digest, name + " original bytes preserved")
    samples.append({"case": name, "input_sha256": digest, "counts": epoch["history_counts"],
                    "minimal": epoch["minimal_possible_mechanism_sets"],
                    "root_sets": len(baseline),
                    "possibly_masked": [item["mechanism"] for item in epoch["investigation"]["masking"]["potentially_masked_mechanisms"]],
                    "common": [cluster["status"] for cluster in epoch["investigation"]["common_cause"]["clusters"]]})

bundle_path = ROOT / "results/v1.3-investigation-20261107-01/development-fixtures.zip"
with ZipFile(bundle_path) as bundle:
    bounds = json.loads(bundle.read("response-bounds.json"))
    for number, counts in enumerate(((42, 0), (20, 0), (3, 0), (0, 87), (88, 0)), 1):
        rows = [json.loads(line) for line in bundle.read(f"{number:02}/observations.jsonl").splitlines()]
        name = f"stress-{number:02}"
        epoch, = run(name, rows, bounds)["epochs"]
        check((epoch["history_counts"]["compatible"], epoch["history_counts"]["unconfirmed"]) == counts,
              name + " original stress-history counts")
        query = evaluate_counterfactual(epoch, model, require=[GEN], exclude=[ENGINE])
        check(all(GEN in item["roots"] and ENGINE not in item["roots"] for item in query["surviving_explanations"]),
              name + " combined counterfactual restrictions")
        if number == 2:
            query = evaluate_counterfactual(epoch, model, only=[ENGINE])
            check(query["status"] == "excluded", name + " earlier local generator cannot be rewritten")
        if number == 5:
            hidden = {item["mechanism"] for item in epoch["investigation"]["masking"]["potentially_masked_mechanisms"]}
            check(BLUE in hidden, name + " additional Blue pressure root remains possible")
            check(not epoch["investigation"]["evidence_selection"]["recommended_measurements"],
                  name + " no invented discriminator")
        samples.append({"case": name, "counts": epoch["history_counts"],
                        "minimal": epoch["minimal_possible_mechanism_sets"],
                        "root_sets": len(viable(epoch)),
                        "possibly_masked": [item["mechanism"] for item in epoch["investigation"]["masking"]["potentially_masked_mechanisms"]],
                        "common": [cluster["status"] for cluster in epoch["investigation"]["common_cause"]["clusters"]]})

output = ROOT / "work/v13-shipping-audit.json"
output.parent.mkdir(parents=True, exist_ok=True)
result = {"source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
          "checks": checks, "samples": samples,
          "passed": sum(item["passed"] for item in checks), "total": len(checks)}
output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(f"{result['passed']}/{result['total']} release checks", flush=True)
raise SystemExit(0 if result["passed"] == result["total"] else 1)
