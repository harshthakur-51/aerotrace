"""One controlled airborne native-model experiment, with private interventions.

This command can change allowlisted failure flags. The operator must stop
competing collectors/controllers and notify the spectator before injection. No
approval prompt is added here. Fresh admission is required even after an earlier
qualified flight. These experiments do not establish real-aircraft fidelity or
diagnostic probabilities; paired cases are synthetic matched interventions.
"""

from __future__ import annotations

import argparse
import copy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import time
import threading
from typing import Callable

from .airborne_admission import (
    AirborneAdmission, QualificationSettings, PROPULSION_FAULTS, READINESS_CHANNELS, _EXPECTED_READINESS,
)
from .airborne_profile import (
    AIRBORNE_CHANNELS, PROFILE_ID, PROPULSION_PROFILE_ID, airborne_observation_record, write_airborne_observation,
)
from .airborne_record import load_settings
from .flightgear import FlightGearClient
from .sim_panel import FAULT_PATHS, PanelState, ObservationPanelState, make_server


CASES = {
    "selected_reference": (),
    "isolated_generator_2": ("generator_2",),
    "isolated_blue_leak": ("blue_leak",),
    "synthetic_shared_regional_event": ("generator_2", "blue_leak"),
    "independent_pair_matched_interventions": ("generator_2", "blue_leak"),
    "isolated_blue_pressure_supply": ("blue_pump",),
    "source_and_pressure_supply_pair": ("generator_2", "blue_pump"),
}
_READINESS_FAULTS = {"generator_2": "generator_2_fault", "blue_leak": "blue_leak_fault", "blue_pump": "blue_pump_fault"}
PROPULSION_CASES = {
    "engine_2_cutoff": ("engine_2_cutoff",),
    "independent_generator_2_and_yellow_edp": ("generator_2", "yellow_edp"),
}


def _save(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _archive_sources(output: Path) -> dict:
    project = Path(__file__).resolve().parents[1]
    sources = (
        "aircraft_debugger/__init__.py", "aircraft_debugger/airborne_experiment.py",
        "aircraft_debugger/airborne_record.py", "aircraft_debugger/airborne_profile.py",
        "aircraft_debugger/airborne_admission.py", "aircraft_debugger/observations.py",
        "aircraft_debugger/flightgear.py", "aircraft_debugger/sim_panel.py",
        "aircraft_debugger/candidate_support.py", "aircraft_debugger/assets/sim-panel.html",
        "aircraft_debugger/diagnostic_session.py", "aircraft_debugger/diagnostic_features.py",
        "aircraft_debugger/hypotheses.py", "aircraft_debugger/airborne_evidence.py",
        "aircraft_debugger/evidence.py",
        "configs/flightgear-assets.json", "configs/flightgear-a320.fgfsrc",
    )
    hashes, archives = {}, {}
    for name in sources:
        payload = (project / name).read_bytes()
        relative = Path("private_truth/executed-source") / name
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        hashes[name] = hashlib.sha256(payload).hexdigest()
        archives[name] = relative.as_posix()
    commit = None
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=project,
                             check=True, capture_output=True, text=True).stdout.strip()
        if Path(top).resolve() == project:
            commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=project,
                                    check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        pass
    return {"source_commit_before_run": commit, "source_sha256": hashes,
            "executed_source_archives": archives,
            "runtime_pins_are_expected_configuration_not_live_build_verification": True}


def _clear_initial_flags(snapshot, fault_paths) -> None:
    for fault, path in fault_paths.items():
        reading = snapshot.readings.get(f"{fault}_fault")
        if (reading is None or reading.path != path
                or reading.valid is not True or reading.reachable is not True
                or reading.error is not None or reading.value is not False):
            raise RuntimeError(f"Native {fault} flag is not confirmed clear; no flags were changed")


def validate_schedule(schedule: object) -> list[dict]:
    """Validate ordered private phases of supported native flag configurations."""
    if not isinstance(schedule, list) or not 1 <= len(schedule) <= 8:
        raise ValueError("A timed schedule requires one to eight phases")
    supported = {frozenset(faults) for faults in CASES.values()}
    phases = []
    for phase in schedule:
        if not isinstance(phase, dict) or set(phase) != {"faults", "duration_sim_s"}:
            raise ValueError("A phase requires faults and duration_sim_s")
        faults, duration = phase["faults"], phase["duration_sim_s"]
        if (not isinstance(faults, list) or any(not isinstance(fault, str) for fault in faults)
                or len(faults) != len(set(faults)) or frozenset(faults) not in supported):
            raise ValueError("A phase must use one supported set of distinct native faults")
        if type(duration) not in (int, float) or not 0.1 <= duration <= 60:
            raise ValueError("Phase duration must be between 0.1 and 60 simulator seconds")
        phases.append({"faults": list(faults), "duration_sim_s": float(duration)})
    if not phases[0]["faults"] or sum(phase["duration_sim_s"] for phase in phases) > 120:
        raise ValueError("A schedule must start with an intervention and span at most 120 simulator seconds")
    return phases


def _transition_expiry(reader, record, pending, settings, monotonic):
    """Fresh continuation clearance after a fully observed phase."""
    readings = record["readings"]
    values = {name: reading["value"] for name, reading in readings.items()}
    if (not record["complete"] or values["aircraft"] != "A320-200-CFM" or values["paused"]
            or values["main_gear_1_wow"] or values["main_gear_2_wow"]
            or values["height_agl"] < settings.minimum_height_agl_ft
            or abs(values["altitude"] - settings.altitude_target_ft) > settings.altitude_tolerance_ft
            or abs(values["airspeed"] - settings.airspeed_target_kt) > settings.airspeed_tolerance_kt
            or abs(values["bank"]) > settings.maximum_abs_bank_deg
            or abs(values["vertical_speed"]) > settings.maximum_abs_vertical_speed_fps):
        raise RuntimeError("Timed transition requires a fresh, stable airborne observation")
    readiness = reader.poll(READINESS_CHANNELS)
    expected = {**_EXPECTED_READINESS, **{name: fault in pending for fault, name in _READINESS_FAULTS.items()}}
    if not readiness.complete or readiness.readings.keys() != expected.keys():
        raise RuntimeError("Timed transition readiness incomplete")
    receipts = [reading["received_monotonic_s"] for reading in readings.values()]
    times = [reading["sim_time_s"] for reading in readings.values()]
    for name, reading in readiness.readings.items():
        if (not reading.valid or not reading.reachable or reading.error is not None
                or reading.path != READINESS_CHANNELS[name].path
                or type(reading.value) is not type(expected[name]) or reading.value != expected[name]
                or reading.sim_time_s is None):
            raise RuntimeError("Timed transition readiness or owned flags differ from the schedule")
        receipts.append(reading.received_monotonic_s)
        times.append(reading.sim_time_s)
    now = monotonic()
    expiry = min(receipts) + settings.maximum_reading_age_s
    if now > expiry or max(receipts) > now or max(times) - min(times) > settings.maximum_timestamp_skew_s:
        raise RuntimeError("Timed transition readings are stale or span different simulator times")
    return expiry, readiness


def run_experiment(
    output: Path, case: str = "isolated_generator_2",
    settings: QualificationSettings | None = None, *, active_s: float = 8.0,
    recovery_s: float = 5.0, interval_s: float = 1.0, max_wait_s: float = 120.0,
    maximum_postfault_local_s: float = 60.0, port: int = 8088,
    client: FlightGearClient | None = None, operator: PanelState | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    on_observation: Callable[[dict], None] | None = None,
    schedule: list[dict] | None = None,
    ptu_selected: bool | None = None,
) -> dict:
    """Collect one case; injected dependencies permit tests without simulator IO.

    Durations active_s/recovery_s are measured simulator seconds between phase
    observations. Local deadlines bound stalls/transport failure and the whole
    post-admission period. Invalid readings are written before stop decisions.
    The caller must ensure exclusive simulator ownership: no distributed lock
    can prevent a separate cockpit/operator changing the same native flag.
    """
    if not isinstance(case, str) or case not in (CASES | PROPULSION_CASES):
        raise ValueError("Unknown airborne experiment case")
    propulsion = case in PROPULSION_CASES
    if propulsion and (type(ptu_selected) is not bool or schedule is not None):
        raise ValueError("Propulsion trials require an explicit PTU setting and one fixed intervention")
    if not propulsion and ptu_selected is not None:
        raise ValueError("The PTU study setting applies only to propulsion trials")
    timed_phases = validate_schedule(schedule) if schedule is not None else None
    if on_observation is not None and not callable(on_observation):
        raise ValueError("on_observation must be callable or None")
    settings = settings if settings is not None else QualificationSettings()
    if not isinstance(settings, QualificationSettings):
        raise ValueError("settings must be QualificationSettings")
    if settings.qualification_duration_sim_s < 15:
        raise ValueError("Controlled experiments require at least 15 advancing simulator seconds of qualification")
    for name, value, lower, upper in (
        ("active_s", active_s, 0.1, 60), ("recovery_s", recovery_s, 0.1, 60),
        ("interval_s", interval_s, 0.05, 3), ("max_wait_s", max_wait_s, 0.1, 3600),
        ("maximum_postfault_local_s", maximum_postfault_local_s, 1, 300),
    ):
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not lower <= value <= upper):
            raise ValueError(f"{name} must be finite and between {lower} and {upper}")
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"Refusing existing experiment folder: {output}")
    reader = client if client is not None else FlightGearClient(port=port, timeout_s=1.0, max_workers=4)
    gate = AirborneAdmission(settings, ptu_selected=ptu_selected)
    channels = gate.channels
    fault_paths = {**FAULT_PATHS, **PROPULSION_FAULTS} if propulsion else FAULT_PATHS
    # A pre-existing fault is never adopted, cleared, or overwritten by this run.
    _clear_initial_flags(reader.poll(gate.readiness_channels), fault_paths)
    output.mkdir(parents=True, exist_ok=False)
    private = output / "private_truth"
    private.mkdir()
    faults = (tuple(dict.fromkeys(fault for phase in timed_phases for fault in phase["faults"]))
              if timed_phases else (CASES | PROPULSION_CASES)[case])
    controller = operator if operator is not None else PanelState(reader, fault_paths=fault_paths)
    pending: set[str] = set()
    summary = {
        "kind": "controlled native-model experiment; private truth, not diagnostic input",
        "created_utc": datetime.now(timezone.utc).isoformat(), "case": "timed_schedule" if timed_phases else case,
        "requested_faults": list(faults), "physical_regional_damage_simulated": False,
        "status": "preparing", "completed": False, "artifacts_complete": False,
        "collection_completed": False, "samples": 0, "phases": [],
        "cleanup_errors": [], "failure": None, "last_gate": None,
        "settings": asdict(settings), "active_duration_target_sim_s": active_s,
        "recovery_duration_target_sim_s": recovery_s, "interval_target_local_s": interval_s,
        "qualification_maximum_local_s": max_wait_s,
        "postfault_maximum_local_s": maximum_postfault_local_s,
        "limits": ["One declared operating condition; no whole-aircraft or real-aircraft validation",
                   "Autopilot or backup supplies may mask motion or bus consequences",
                   "Clearing a blue leak may refill native quantity; it is not physical repair",
                   "Shared and independent paired recipes request identical supported component flags",
                   "Exclusive collector/control ownership is an operational prerequisite, not an interprocess guarantee",
                   "No probabilistic diagnosis or causal identification is computed"],
    }
    if timed_phases:
        summary["timed_schedule"] = timed_phases
        summary["active_duration_target_sim_s"] = None
    if propulsion:
        summary["reference_ptu_selected"] = ptu_selected
        summary["limits"].append("Cutoff exercises simulated engine power loss. Releasing the cutoff input does not establish relight or restoration of engine power.")
    summary_path = private / "summary.json"
    _save(summary_path, summary)
    provenance = _archive_sources(output)
    settings_path = private / "settings.json"
    _save(settings_path, asdict(settings))
    observation_path = output / "observations.jsonl"
    qualification_path = private / "qualification.jsonl"
    action_path = private / "actions.jsonl"
    previous_sim: dict[str, float] = {}
    previous_receipt: dict[str, float] = {}
    channel_last_advance: dict[str, float] = {}
    previous_observed_sim: float | None = None
    failure: BaseException | None = None
    action_number = 0
    started = monotonic()
    post_deadline: float | None = None
    last_record = None

    with observation_path.open("x", encoding="utf-8", newline="\n") as observations, \
            qualification_path.open("x", encoding="utf-8", newline="\n") as checks, \
            action_path.open("x", encoding="utf-8", newline="\n") as actions:

        def journal(value: dict) -> None:
            actions.write(json.dumps(value, allow_nan=False) + "\n")
            actions.flush()

        def command(fault: str, enabled: bool, expires_at: float | None = None) -> None:
            nonlocal action_number
            action_number += 1
            action = {"action_id": action_number, "stage": "attempt",
                      "fault": fault, "enabled": enabled, "requested_monotonic_s": monotonic()}
            if enabled:
                pending.add(fault)  # Must precede any call that may send a write.
            logging_error = None
            try:
                journal(action)
            except BaseException as exc:
                if enabled:
                    pending.discard(fault)  # Certainly no command was called.
                    raise
                logging_error = exc  # Failed disk logging must never prevent cleanup.
            if enabled and expires_at is not None and monotonic() > expires_at:
                pending.discard(fault)
                journal({**action, "stage": "cancelled_before_write", "reason": "admission_expired"})
                raise RuntimeError("Fresh admission expired before this enable; earlier attempts still require cleanup")
            command_error = None
            status, result = None, None
            try:
                if enabled:
                    def before_write_check() -> None:
                        # PanelState invokes this after its prerequisite HTTP
                        # reads, immediately before POST sends any request bytes.
                        if expires_at is None or monotonic() > expires_at:
                            raise RuntimeError("Fresh admission expired before native POST")
                        if post_deadline is not None and monotonic() > post_deadline:
                            raise RuntimeError("Post-intervention local deadline exceeded before native POST")
                    status, result = controller.command({"fault": fault, "enabled": True},
                                                        before_write_check=before_write_check,
                                                        required_aircraft="A320-200-CFM")
                else:
                    status, result = controller.command({"fault": fault, "enabled": False},
                                                        required_aircraft="A320-200-CFM")
            except BaseException as exc:
                command_error = exc
            readback = None
            if not enabled:
                try:
                    reading = reader.read_property(fault_paths[fault], "bool")
                    readback = asdict(reading)
                    # A false flag on a replacement aircraft cannot establish
                    # cleanup of the aircraft whose enable this run attempted.
                    # PanelState's verified 200 also requires pinned identity.
                    if (status == 200 and reading.path == fault_paths[fault] and reading.valid is True
                            and reading.reachable is True and reading.error is None and reading.value is False):
                        pending.discard(fault)
                except BaseException as exc:
                    readback = {"error": type(exc).__name__, "message": str(exc)}
            journal({**action, "stage": "result", "completed_monotonic_s": monotonic(),
                     "status": status, "result": result, "readback": readback,
                     "exception": None if command_error is None else {"type": type(command_error).__name__, "message": str(command_error)}})
            if logging_error is not None:
                raise logging_error
            if command_error is not None:
                raise command_error
            if status != 200 or (not enabled and fault in pending):
                raise RuntimeError(f"Native {fault} {'enable' if enabled else 'cleanup'} was not verified")

        def sample() -> dict:
            nonlocal last_record
            poll_started = monotonic()
            snapshot = reader.poll(channels)
            record = airborne_observation_record(snapshot, summary["samples"], poll_started, propulsion=propulsion)
            write_airborne_observation(observations, record)
            summary["samples"] += 1
            last_record = record
            if on_observation is not None:
                # Only the exact public stream crosses this boundary. A copy
                # prevents an observer from changing recorded/control evidence.
                on_observation(copy.deepcopy(record))
            return record

        def qualified_sample(phase: str) -> tuple[dict, float]:
            record = sample()
            readiness_started = monotonic()
            readiness = reader.poll(gate.readiness_channels)
            evaluated = monotonic()
            outcome = gate.update(record, readiness, evaluated)
            summary["last_gate"] = outcome
            checks.write(json.dumps({"sample_index": record["sample_index"], "phase": phase,
                "gate": outcome, "readiness_poll_started_monotonic_s": readiness_started,
                "evaluated_monotonic_s": evaluated, "readiness": readiness.to_dict()}, allow_nan=False) + "\n")
            checks.flush()
            receipts = [item["received_monotonic_s"] for item in record["readings"].values()]
            receipts.extend(item.received_monotonic_s for item in readiness.readings.values())
            return record, min(receipts) + settings.maximum_reading_age_s

        def pace(poll_started: float, deadline: float) -> None:
            delay = min(interval_s - (monotonic() - poll_started), deadline - monotonic())
            if delay > 0:
                sleep(delay)

        def record_phase(name: str, duration_s: float) -> None:
            nonlocal previous_observed_sim
            phase_started = monotonic()
            deadline = min(post_deadline, phase_started + max(15.0, duration_s * 3 + 5))
            phase = {"name": name, "first_sample_index": summary["samples"],
                     "started_monotonic_s": phase_started, "duration_target_sim_s": duration_s,
                     "completed": False}
            summary["phases"].append(phase)
            first_sim = None
            first_channel_sim: dict[str, float] = {}
            last_advance_local = phase_started
            unavailable_since = None
            count = 0
            try:
                while monotonic() < deadline:
                    poll_started = monotonic()
                    record = sample()  # Preserve invalid/out-of-band consequences first.
                    count += 1
                    readings = record["readings"]
                    for channel, reading in readings.items():
                        at = reading["sim_time_s"]
                        if reading["valid"] and at is not None:
                            if channel in previous_sim and at < previous_sim[channel]:
                                raise RuntimeError("Simulator clock reset; partial observations retained")
                            if channel in previous_sim and at - previous_sim[channel] > settings.maximum_sim_gap_s:
                                raise RuntimeError("Required simulator timestamp gap exceeded; partial observations retained")
                            if channel not in previous_sim or at > previous_sim[channel]:
                                channel_last_advance[channel] = monotonic()
                            previous_sim[channel] = at
                            first_channel_sim.setdefault(channel, at)
                        receipt = reading["received_monotonic_s"]
                        if receipt < previous_receipt.get(channel, receipt):
                            raise RuntimeError("Required local receipt clock moved backwards; partial observations retained")
                        previous_receipt[channel] = receipt
                        if monotonic() - channel_last_advance.get(channel, phase_started) >= settings.maximum_local_gap_s:
                            raise RuntimeError("Required channel time stopped advancing; partial observations retained")
                    aircraft = readings.get("aircraft", {})
                    if aircraft.get("valid") and aircraft["value"] != "A320-200-CFM":
                        raise RuntimeError("Observed aircraft changed during collection")
                    paused = readings.get("paused", {})
                    if paused.get("valid") and paused["value"] is True:
                        raise RuntimeError("Simulator paused during collection")
                    # Stability bands deliberately do not apply after intervention.
                    timestamps = [item["sim_time_s"] for item in readings.values() if item["valid"] and item["sim_time_s"] is not None]
                    fresh = (record["complete"]
                        and record["received_monotonic_s"] - record["poll_started_monotonic_s"] <= settings.maximum_poll_span_s
                        and len(timestamps) == len(channels)
                        and max(timestamps) - min(timestamps) <= settings.maximum_timestamp_skew_s
                        and all(
                        item["sim_time_s"] is not None and 0 <= monotonic() - item["received_monotonic_s"] <= settings.maximum_reading_age_s
                        for item in readings.values()))
                    unavailable_since = None if fresh else unavailable_since if unavailable_since is not None else monotonic()
                    if unavailable_since is not None and monotonic() - unavailable_since >= settings.maximum_local_gap_s:
                        raise RuntimeError("Post-intervention telemetry unavailable or stale; partial observations retained")
                    clock = readings.get("sim_time", {})
                    now_sim = clock.get("value") if clock.get("valid") else None
                    if now_sim is not None:
                        if previous_observed_sim is not None and now_sim < previous_observed_sim:
                            raise RuntimeError("Simulator clock reset; partial observations retained")
                        if previous_observed_sim is not None and now_sim - previous_observed_sim > settings.maximum_sim_gap_s:
                            raise RuntimeError("Observed simulator clock gap exceeded; partial observations retained")
                        previous_observed_sim = now_sim
                        prior = phase.get("last_sim_time_s")
                        if prior is not None and now_sim < prior:
                            raise RuntimeError("Simulator clock reset; partial observations retained")
                        if first_sim is None:
                            first_sim = now_sim
                            phase["first_sim_time_s"] = now_sim
                        if prior is None or now_sim > prior:
                            last_advance_local = monotonic()
                        phase["last_sim_time_s"] = now_sim
                        phase["elapsed_sim_s"] = now_sim - first_sim
                        phase["minimum_required_channel_elapsed_sim_s"] = min(
                            (previous_sim[name] - first_channel_sim[name] for name in channels),
                            default=0.0,
                        ) if first_channel_sim.keys() == channels.keys() else 0.0
                        if monotonic() > deadline:
                            raise RuntimeError("Post-intervention local deadline exceeded; partial observations retained")
                        if (count >= 2 and now_sim - first_sim >= duration_s and fresh
                                and phase["minimum_required_channel_elapsed_sim_s"] >= duration_s):
                            phase["completed"] = True
                            return
                    if monotonic() - last_advance_local >= settings.maximum_local_gap_s:
                        raise RuntimeError("Simulator clock stopped advancing; partial observations retained")
                    pace(poll_started, deadline)
                raise RuntimeError("Post-intervention local deadline exceeded; partial observations retained")
            finally:
                phase["end_sample_index_exclusive"] = summary["samples"]
                phase["ended_monotonic_s"] = monotonic()

        try:
            deadline = monotonic() + max_wait_s
            summary["status"] = "qualifying"
            qualified = False
            while monotonic() < deadline:
                poll_started = monotonic()
                record, expires_at = qualified_sample("qualification")
                if summary["last_gate"]["qualified"]:
                    # One new advancing sample, not the cached qualified result.
                    pace(poll_started, deadline)
                    if monotonic() >= deadline:
                        break
                    record, expires_at = qualified_sample("final_pre_intervention")
                    if not summary["last_gate"]["qualified"]:
                        raise RuntimeError("Fresh final admission failed; no faults were enabled")
                    if monotonic() > deadline:
                        raise RuntimeError("Qualification local deadline exceeded before intervention; no faults were enabled")
                    qualified = True
                    break
                pace(poll_started, deadline)
            summary["baseline_end_sample_index_exclusive"] = summary["samples"]
            if not qualified:
                summary["status"] = "not_qualified"
            else:
                _save(summary_path, summary)
                previous_sim.update({name: item["sim_time_s"] for name, item in record["readings"].items()
                                     if item["sim_time_s"] is not None})
                channel_last_advance.update({name: monotonic() for name in previous_sim})
                previous_receipt.update({name: item["received_monotonic_s"] for name, item in record["readings"].items()})
                previous_observed_sim = record["readings"]["sim_time"]["value"]
                post_deadline = monotonic() + maximum_postfault_local_s
                print(f"CONTROLLED EXPERIMENT: {summary['case']}; spectator notification must precede native fault injection.", flush=True)
                summary["status"] = "active"
                phases = timed_phases or [{"faults": faults, "duration_sim_s": active_s}]
                for index, phase in enumerate(phases):
                    for fault in reversed(faults):
                        if fault in pending and fault not in phase["faults"]:
                            command(fault, False)
                    enabling = [fault for fault in phase["faults"] if fault not in pending]
                    if index and enabling:
                        expires_at, readiness = _transition_expiry(reader, last_record, pending, settings, monotonic)
                        journal({"stage": "timed_transition_clearance", "phase": index + 1,
                                 "sample_index": last_record["sample_index"], "expires_monotonic_s": expires_at,
                                 "readiness": readiness.to_dict()})
                    for fault in enabling:
                        command(fault, True, expires_at)
                    phase_name = f"timed_phase_{index + 1}" if timed_phases else "active"
                    record_phase(phase_name, phase["duration_sim_s"])
                for fault in reversed(faults):
                    if fault not in pending:
                        continue
                    command(fault, False)
                summary["status"] = "recovery"
                record_phase("recovery", recovery_s)
                summary["collection_completed"] = True
                summary["status"] = "completed"
        except BaseException as exc:
            failure = exc
            summary["status"] = "aborted"
            summary["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        finally:
            for fault in sorted(pending):
                try:
                    command(fault, False)
                except BaseException as exc:
                    summary["cleanup_errors"].append({"fault": fault, "type": type(exc).__name__, "message": str(exc)})
            summary["pending_faults_unverified_clear"] = sorted(pending)
            if summary["cleanup_errors"] or pending:
                summary["status"] = "aborted"
            summary["elapsed_local_s"] = monotonic() - started
            _save(summary_path, summary)

    # Immutable streams are closed before hashing. Artifact completion remains
    # false if a manifest/summary write fails after successful native cleanup.
    try:
        manifest = {
            "manifest_schema_version": 1, "observation_schema_version": 3 if propulsion else 2,
            "observation_profile": PROPULSION_PROFILE_ID if propulsion else PROFILE_ID, "observations": "observations.jsonl",
            "sha256": _hash(observation_path), "samples": summary["samples"],
            "polls_are_atomic": False, "partial_collection": not summary["collection_completed"],
            "channels": {name: asdict(spec) for name, spec in channels.items()},
            "qualification_checks": "private_truth/qualification.jsonl",
            "qualification_checks_sha256": _hash(qualification_path),
            "operator_actions": "private_truth/actions.jsonl", "operator_actions_sha256": _hash(action_path),
            "qualification_settings": "private_truth/settings.json", "qualification_settings_sha256": _hash(settings_path),
            **provenance,
        }
        _save(output / "manifest.json", manifest)
        summary["artifacts_complete"] = True
        summary["completed"] = summary["status"] == "completed" and not pending and not summary["cleanup_errors"]
        _save(summary_path, summary)
    except BaseException as exc:
        summary["completed"] = summary["artifacts_complete"] = False
        summary["artifact_failure"] = {"type": type(exc).__name__, "message": str(exc)}
        try:
            _save(summary_path, summary)
        except BaseException:
            pass
        if failure is None:
            failure = exc
    if failure is not None:
        raise failure
    if summary["cleanup_errors"] or pending:
        raise RuntimeError("Native fault cleanup could not be verified; inspect private truth")
    print(f"{summary['status']}: {summary['samples']} public observation polls saved to {output.resolve()}", flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    recipe = parser.add_mutually_exclusive_group()
    recipe.add_argument("--case", choices=tuple(CASES | PROPULSION_CASES), default="isolated_generator_2")
    recipe.add_argument("--schedule", type=Path, help="JSON array of timed native phases")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--ptu", choices=("auto", "off"), help="Required observed PTU switch setting for propulsion trials")
    parser.add_argument("--active-seconds", type=float, default=8.0)
    parser.add_argument("--recovery-seconds", type=float, default=5.0)
    parser.add_argument("--interval-seconds", type=float, default=1.0)
    parser.add_argument("--max-wait-seconds", type=float, default=120.0)
    parser.add_argument("--maximum-postfault-local-seconds", type=float, default=60.0)
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument("--live-panel-port", type=int, help="Read-only inspector using the recorder's exact public stream")
    parser.add_argument("--diagnostic-model", choices=("v1", "v2"), default="v1",
                        help="Independent public model selection; never inferred from the private intervention case")
    args = parser.parse_args()
    schedule = validate_schedule(json.loads(args.schedule.read_text(encoding="utf-8"))) if args.schedule else None
    panel = server = thread = None
    if args.live_panel_port is not None:
        from .hypotheses import pressure_supply_model
        panel = ObservationPanelState(interval_s=args.interval_seconds,
                                      model=pressure_supply_model() if args.diagnostic_model == "v2" else None)
        server = make_server(panel, args.live_panel_port)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print(f"Read-only experiment inspector: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        result = run_experiment(args.output, args.case, load_settings(args.config),
            active_s=args.active_seconds, recovery_s=args.recovery_seconds,
            interval_s=args.interval_seconds, max_wait_s=args.max_wait_seconds,
            maximum_postfault_local_s=args.maximum_postfault_local_seconds, port=args.port,
            on_observation=panel.accept if panel is not None else None, schedule=schedule,
            ptu_selected=None if args.ptu is None else args.ptu == "auto")
        if panel is not None:
            _save(args.output / "live-inspector-final.json", panel.get_state())
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
    if not result["completed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
