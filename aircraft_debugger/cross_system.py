"""Record five connected A320 contrasts, keeping interventions in private truth.

This is an experiment controller, never a diagnostic input. It uses only the
panel's two supported native failure inputs, not calculated gauge writes. The
shared and independent paired cases request the same component damage; their
different initiating histories exist only in this controller's private annotation.
No physical debris/zone propagation or unique causal identification is claimed.

Run on a ready, on-ground A320 with panel polling stopped. A new output folder
is required. Every attempted enable is tracked before writing, so an uncertain
acknowledgement still triggers best-effort cleanup. Only this run's flags are
cleared, and cleanup failures are recorded and cause failure of the run.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import time

from .flightgear import FlightGearClient
from .observations import CHANNELS, observation_record, write_observation
from .sim_panel import FAULT_PATHS, PanelState


# These labels never enter an observations file or diagnostic function.
CASES = (
    ("selected_reference", ()),
    ("isolated_generator_2", ("generator_2",)),
    ("isolated_blue_leak", ("blue_leak",)),
    ("synthetic_shared_regional_event", ("generator_2", "blue_leak")),
    ("independent_pair_matched_interventions", ("generator_2", "blue_leak")),
)


def _save(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _values(snapshot) -> dict:
    return {name: reading.value if reading.valid else None
            for name, reading in snapshot.readings.items()}


def _reference_check(client: FlightGearClient) -> dict:
    snapshot = client.poll(CHANNELS)
    values = _values(snapshot)
    if not snapshot.complete:
        raise RuntimeError("Incomplete reference observations; missing values are not healthy")
    if values["aircraft"] != "A320-200-CFM" or values["paused"]:
        raise RuntimeError("A running, unpaused A320-200-CFM is required")
    if (values["airspeed"] >= 20 or values["generator_2_voltage"] <= 100
            or values["ac_bus_1"] <= 100 or values["ac_bus_2"] <= 100
            or values["blue_quantity"] < 7.9 or values["blue_pressure"] < 2500):
        raise RuntimeError("Selected ground reference conditions are not ready")
    for path in ("/systems/acconfig/autoconfig-running",):
        ready = client.read_property(path, "bool")
        if not ready.valid or ready.value is not False:
            raise RuntimeError("Native startup sequence is not complete")
    for index in (0, 1):
        running = client.read_property(f"/engines/engine[{index}]/running", "bool")
        if not running.valid or running.value is not True:
            raise RuntimeError("Both engines must be running for this reference condition")
    ground = client.read_property("/gear/gear[1]/wow", "bool")
    if not ground.valid or ground.value is not True:
        raise RuntimeError("Ground contact must be observed; low airspeed alone is insufficient")
    for fault, path in FAULT_PATHS.items():
        existing = client.read_property(path, "bool")
        if not existing.valid or existing.value is not False:
            raise RuntimeError(f"Native {fault} flag is not clear; it was not changed by this run")
    return values


def run_experiment(output: Path, baseline_s: float = 5.0, active_s: float = 8.0,
                   interval_s: float = 1.0, port: int = 8088) -> dict:
    """Controlled live data collection; return an offline, truth-labelled summary."""
    for name, value, minimum, maximum in (
        ("baseline_s", baseline_s, 3, 60), ("active_s", active_s, 6, 60),
        ("interval_s", interval_s, 0.5, 3),
    ):
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not minimum <= value <= maximum):
            raise ValueError(f"{name} must be finite and between {minimum} and {maximum}")
    client = FlightGearClient(port=port, timeout_s=1.0, max_workers=4)
    # No output folder or simulator change until the initial readiness check passes.
    _reference_check(client)
    output.mkdir(parents=True, exist_ok=False)
    private = output / "private_truth"
    private.mkdir()
    operator = PanelState(client)
    pending: set[str] = set()
    private_log = {"kind": "operator interventions and experiment labels; exclude from inference",
                   "created_utc": datetime.now(timezone.utc).isoformat(), "episodes": [],
                   "actions": [], "cleanup_errors": [], "completed": False}
    summaries = []
    public_episodes = []
    succeeded = False

    def command(fault: str, enabled: bool) -> None:
        if enabled:
            # A write may reach the simulator even if its acknowledgement is lost.
            pending.add(fault)
        started = time.monotonic()
        status, result = operator.command({"fault": fault, "enabled": enabled})
        private_log["actions"].append({"fault": fault, "enabled": enabled,
            "requested_monotonic_s": started, "completed_monotonic_s": time.monotonic(),
            "status": status, "result": result})
        _save(private / "experiment.json", private_log)
        if status != 200:
            raise RuntimeError(f"Native {fault} write was not verified: {result}")
        if not enabled:
            pending.discard(fault)

    try:
        for number, (label, faults) in enumerate(CASES, start=1):
            reference = _reference_check(client)
            episode_id = f"episode-{number:03d}"
            episode_dir = output / episode_id
            episode_dir.mkdir()
            observations_path = episode_dir / "observations.jsonl"
            episode_truth = {"episode_id": episode_id, "label": label,
                "requested_faults": list(faults), "intervention_sequence_identical_to":
                "episode-004" if number == 5 else None,
                "physical_regional_damage_simulated": False}
            private_log["episodes"].append(episode_truth)
            samples = []
            previous_time = None

            with observations_path.open("x", encoding="utf-8") as stream:
                def record_for(duration_s: float) -> None:
                    nonlocal previous_time
                    phase_times = []
                    deadline = time.monotonic() + duration_s
                    while time.monotonic() < deadline:
                        started = time.monotonic()
                        snapshot = client.poll(CHANNELS)
                        record = observation_record(snapshot, len(samples), started)
                        write_observation(stream, record)
                        stream.flush()
                        samples.append(record)
                        values = _values(snapshot)
                        if not snapshot.complete or values["paused"]:
                            raise RuntimeError("Live sampling became unavailable or paused; partial data retained")
                        now_sim = values["sim_time"]
                        if previous_time is not None:
                            if now_sim < previous_time:
                                raise RuntimeError("Simulator clock reset; do not combine epochs")
                        previous_time = now_sim
                        phase_times.append(now_sim)
                        delay = min(interval_s - (time.monotonic() - started),
                                    deadline - time.monotonic())
                        if delay > 0:
                            time.sleep(delay)
                    if len(phase_times) < 2 or phase_times[-1] <= phase_times[0]:
                        raise RuntimeError("Simulator clock did not advance during sampling phase")

                record_for(baseline_s)
                episode_truth["baseline_sample_count"] = len(samples)
                for fault in faults:
                    command(fault, True)
                episode_truth["active_first_sample_index"] = len(samples)
                record_for(active_s)

            final = {name: value["value"] for name, value in samples[-1]["readings"].items()}
            for fault in reversed(faults):
                command(fault, False)
            # Allow native recovery/refill; it is a model reset, never a repair claim.
            time.sleep(2)
            data_hash = hashlib.sha256(observations_path.read_bytes()).hexdigest()
            public_episodes.append({"episode_id": episode_id,
                "observations": f"{episode_id}/observations.jsonl", "samples": len(samples),
                "sha256": data_hash})
            checks = {
                "generator_output_expected": final["generator_2_voltage"] < 20
                    if "generator_2" in faults else final["generator_2_voltage"] > 100,
                "blue_quantity_expected": final["blue_quantity"] < reference["blue_quantity"] - 0.5
                    if "blue_leak" in faults else abs(final["blue_quantity"] - reference["blue_quantity"]) < 0.1,
                "bus_2_retained": final["ac_bus_2"] > 100,
                "blue_pressure_retained_during_brief_window": final["blue_pressure"] > 2500,
            }
            summaries.append({"episode_id": episode_id, "private_label": label,
                "samples": len(samples), "checks": checks, "final_observed": final})
            if not all(checks.values()):
                raise RuntimeError(f"Predicted model response was not observed for {episode_id}; inspect partial results")
            print(f"{episode_id}: {len(samples)} samples; predicted native responses observed", flush=True)
        succeeded = True
    except BaseException as exc:
        private_log["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        for fault in sorted(pending):
            try:
                command(fault, False)
            except Exception as exc:
                private_log["cleanup_errors"].append({"fault": fault, "error": str(exc)})
        # Collection success is not artifact completion: metadata below may fail.
        private_log["collection_completed"] = succeeded
        _save(private / "experiment.json", private_log)
        if succeeded and private_log["cleanup_errors"]:
            raise RuntimeError("Collection completed but native flags could not be cleared; see private truth")

    sources = ("aircraft_debugger/cross_system.py", "aircraft_debugger/observations.py",
               "aircraft_debugger/flightgear.py", "aircraft_debugger/sim_panel.py",
               "aircraft_debugger/__init__.py", "aircraft_debugger/diagnostic_session.py",
               "aircraft_debugger/diagnostic_features.py", "aircraft_debugger/hypotheses.py",
               "aircraft_debugger/airborne_evidence.py", "aircraft_debugger/airborne_profile.py",
               "aircraft_debugger/evidence.py",
               "configs/flightgear-a320.fgfsrc", "configs/flightgear-assets.json")
    hashes = {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in sources}
    commit = subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True,
                            text=True).stdout.strip()
    _save(output / "manifest.json", {"schema_version": 1, "aircraft": "A320-200-CFM",
        "flightgear_version": "2024.1.7", "catalog_revision": 20376,
        "observation_contract": "selected model properties; not validated aircraft sensors",
        "sample_interval_target_s": interval_s, "polls_are_atomic": False,
        "episodes": public_episodes, "source_commit_before_run": commit,
        "source_sha256": hashes})
    summary = {"kind": "offline native-model contrast check; not diagnosis accuracy or debris simulation",
        "episodes": summaries, "private_truth_excluded_from_inference": True,
        "limits": ["Shared and independent cases use matched component interventions; actual sampling jitter differs",
                   "Blue quantity uses unresolved raw units and native clearing can refill",
                   "An engine-initiated event and uncontained damage physics are not implemented",
                   "Cases are sequential ground tests, not independent full simulator resets"]}
    _save(private / "summary.json", summary)
    private_log["completed"] = True
    _save(private / "experiment.json", private_log)
    print(f"Five connected contrasts saved: {output}", flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--baseline-seconds", type=float, default=5.0)
    parser.add_argument("--active-seconds", type=float, default=8.0)
    parser.add_argument("--interval-seconds", type=float, default=1.0)
    parser.add_argument("--port", type=int, default=8088)
    args = parser.parse_args()
    run_experiment(args.output, args.baseline_seconds, args.active_seconds,
                   args.interval_seconds, args.port)


if __name__ == "__main__":
    main()
