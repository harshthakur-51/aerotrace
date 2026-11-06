"""Measure the read-only v2 adapter on a synthetic extension of a native trace."""
import copy
import hashlib
import json
from pathlib import Path
import platform
import statistics
import time

from aircraft_debugger.airborne_profile import iter_profile_observations
from aircraft_debugger.diagnosis import _sources
from aircraft_debugger.diagnostic_session import SessionLimitReached
from aircraft_debugger.hypotheses import pressure_supply_model
from aircraft_debugger.sim_panel import ObservationPanelState


RUN = Path("results/pressure-pair-20261106-01/pair")
INPUT = RUN / "observations.jsonl"
OUTPUT = Path("results/pressure-v2-load-optimized-20261106-01")
LIMIT = 1200


def main():
    raw = INPUT.read_bytes()
    rows = list(iter_profile_observations(INPUT))
    summary = json.loads((RUN / "private_truth/summary.json").read_text(encoding="utf-8"))
    recovery_start = next(phase["first_sample_index"] for phase in summary["phases"]
                          if phase["name"] == "recovery")
    fixture = rows[:recovery_start]
    held = fixture[-1]
    while len(fixture) <= LIMIT:
        row = copy.deepcopy(held)
        row["sample_index"] = len(fixture)
        offset_s = row["sample_index"] - held["sample_index"]
        row["poll_started_monotonic_s"] += offset_s
        row["received_monotonic_s"] += offset_s
        for name, reading in row["readings"].items():
            reading["sim_time_s"] += offset_s
            reading["received_monotonic_s"] += offset_s
            if name == "sim_time":
                reading["value"] += offset_s
        fixture.append(row)
    panel = ObservationPanelState(model=pressure_supply_model(), diagnosis_limit=LIMIT)
    timings = []
    for row in fixture[:LIMIT]:
        started = time.perf_counter()
        panel.accept(row)
        timings.append(time.perf_counter() - started)
    last = panel.get_state()["diagnosis"]
    assert last["result"]["status"] == "causal_ambiguity"
    try:
        panel.accept(fixture[LIMIT])
    except SessionLimitReached:
        overflow = panel.get_state()["diagnosis"]
        assert overflow["availability"] == "error"
    else:
        raise RuntimeError("Read-only experiment adapter did not stop at its limit")
    assert INPUT.read_bytes() == raw
    OUTPUT.mkdir()
    sources = _sources()
    for name in ("aircraft_debugger/sim_panel.py", "aircraft_debugger/diagnostic_session.py"):
        sources[name] = Path(name).read_bytes()
    (OUTPUT / "executed-helper.py").write_bytes(Path(__file__).read_bytes())
    result = {
        "scope": "Host wall time for read-only v2 accept including feature evaluation and snapshot copy",
        "fixture": "Native development prefix then held active measured values with advancing synthetic timestamps",
        "exclusions": "Native polling and HTTP or browser presentation excluded",
        "platform": platform.platform(), "python": platform.python_version(),
        "input_sha256": hashlib.sha256(raw).hexdigest(),
        "native_prefix_polls": recovery_start, "accepted_polls": len(timings),
        "last_sample_index": last["sample_index"], "last_result": last["result"]["status"],
        "limit_exception_on_poll_1201": True,
        "mean_update_ms": statistics.mean(timings) * 1000,
        "p95_update_ms": statistics.quantiles(timings, n=100, method="inclusive")[94] * 1000,
        "maximum_update_ms": max(timings) * 1000,
        "source_sha256": {name: hashlib.sha256(body).hexdigest() for name, body in sources.items()},
        "elapsed_seconds_per_update": timings,
    }
    (OUTPUT / "measurements.json").write_text(json.dumps(result, indent=2) + "\n",
                                              encoding="utf-8", newline="\n")
    print(json.dumps({k: result[k] for k in ("accepted_polls", "mean_update_ms", "p95_update_ms",
                                           "maximum_update_ms", "limit_exception_on_poll_1201")}))


if __name__ == "__main__":
    main()

