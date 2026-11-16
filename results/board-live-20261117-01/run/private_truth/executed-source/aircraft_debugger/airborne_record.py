"""Read-only recording of an airborne experiment's reference qualification.

No simulator commands or fault writes exist in this module. It records twenty
public observations and separate private initialization checks. Passing qualifies
only the final recorded experiment window, not current or real-aircraft safety.
The legacy diagnostic analyzer does not yet accept this schema-2 context.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import time

from .airborne_admission import AirborneAdmission, QualificationSettings, READINESS_CHANNELS
from .airborne_profile import (
    AIRBORNE_CHANNELS, PROFILE_ID, airborne_observation_record,
    write_airborne_observation,
)
from .flightgear import FlightGearClient


def _json_file(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


def load_settings(path: Path | None) -> QualificationSettings:
    if path is None:
        return QualificationSettings()
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("qualification settings must be a JSON object")
    try:
        return QualificationSettings(**payload)
    except TypeError as exc:
        raise ValueError(f"Unknown qualification setting: {exc}") from exc


def _archive_sources(output: Path) -> dict:
    """Archive the actual Python/configuration bytes before collecting samples."""
    project = Path(__file__).resolve().parents[1]
    sources = (
        "aircraft_debugger/airborne_record.py", "aircraft_debugger/airborne_profile.py",
        "aircraft_debugger/airborne_admission.py", "aircraft_debugger/observations.py",
        "aircraft_debugger/flightgear.py", "configs/flightgear-assets.json",
        "configs/flightgear-a320.fgfsrc",
    )
    hashes, archives = {}, {}
    for name in sources:
        payload = (project / name).read_bytes()
        relative = Path("private_truth") / "executed-source" / name
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
        pass  # An archived source copy may have no .git; byte provenance still exists.
    return {"source_commit_before_run": commit, "source_sha256": hashes,
            "executed_source_archives": archives,
            "runtime_pins_are_expected_configuration_not_live_build_verification": True}


def collect_reference(
    output: Path, settings: QualificationSettings | None = None, *,
    max_wait_s: float = 120.0, interval_s: float = 1.0, port: int = 8088,
    client: FlightGearClient | None = None,
) -> dict:
    """Record until the first qualifying window, timeout or interruption.

    The optional client supports read-only transport fixtures. All public polls
    use AIRBORNE_CHANNELS; private startup/flag reads use READINESS_CHANNELS.
    A timeout is a preserved unqualified result, never a manufactured baseline.
    """
    for name, value, lower, upper in (
        ("max_wait_s", max_wait_s, 0.1, 3600.0),
        ("interval_s", interval_s, 0.05, 10.0),
    ):
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not lower <= value <= upper):
            raise ValueError(f"{name} must be finite and between {lower} and {upper}")
    settings = settings if settings is not None else QualificationSettings()
    if not isinstance(settings, QualificationSettings):
        raise ValueError("settings must be QualificationSettings")
    reader = client if client is not None else FlightGearClient(port=port, timeout_s=1.0, max_workers=4)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    private = output / "private_truth"
    private.mkdir()
    provenance = _archive_sources(output)
    settings_path = private / "settings.json"
    _json_file(settings_path, asdict(settings))
    provenance["qualification_settings"] = "private_truth/settings.json"
    provenance["qualification_settings_sha256"] = hashlib.sha256(settings_path.read_bytes()).hexdigest()
    gate = AirborneAdmission(settings)
    samples = 0
    last_gate = None
    previous_reason = None
    status = "not_qualified"
    failure = None
    started = time.monotonic()
    observation_path = output / "observations.jsonl"
    qualification_path = private / "qualification.jsonl"
    try:
        with observation_path.open("x", encoding="utf-8", newline="\n") as stream, \
                qualification_path.open("x", encoding="utf-8", newline="\n") as checks:
            while time.monotonic() - started < max_wait_s:
                poll_started = time.monotonic()
                snapshot = reader.poll(AIRBORNE_CHANNELS)
                record = airborne_observation_record(snapshot, samples, poll_started)
                write_airborne_observation(stream, record)
                samples += 1
                readiness_started = time.monotonic()
                readiness = reader.poll(READINESS_CHANNELS)
                evaluated = time.monotonic()
                last_gate = gate.update(record, readiness, evaluated)
                checks.write(json.dumps({
                    "sample_index": record["sample_index"], "gate": last_gate,
                    "readiness_poll_started_monotonic_s": readiness_started,
                    "evaluated_monotonic_s": evaluated, "readiness": readiness.to_dict(),
                }, allow_nan=False) + "\n")
                checks.flush()
                reason = tuple(last_gate["reasons"])
                if reason != previous_reason:
                    print("Reference check: " + (", ".join(reason) if reason else "eligible samples accumulating"), flush=True)
                    previous_reason = reason
                if last_gate["qualified"]:
                    status = "qualified_recorded_window"
                    break
                delay = min(interval_s - (time.monotonic() - poll_started),
                            max_wait_s - (time.monotonic() - started))
                if delay > 0:
                    time.sleep(delay)
    except BaseException as exc:
        status = "aborted"
        failure = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        elapsed = time.monotonic() - started
        summary = {
            "kind": "operator qualification result; not diagnostic input or flight safety advice",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "status": status, "artifacts_complete": False, "samples": samples,
            "elapsed_local_s": elapsed, "maximum_wait_local_s": max_wait_s,
            "poll_interval_target_s": interval_s, "settings": asdict(settings),
            "last_gate": last_gate, "failure": failure,
            "simulator_writes_performed": False, "faults_injected": False,
            "limits": [
                "Qualification applies to this recorded window and may cease immediately afterward",
                "Passing selected checks does not prove whole-aircraft health, loaded terrain validity or real-aircraft safety",
                "Selected autopilot engagement/autothrust states are observed; all automation modes and pilot inputs are not recorded",
                "No diagnostic cause ranking, controlled airborne fault injection or ground-to-flight validation is performed",
            ],
        }
        _json_file(private / "summary.json", summary)
        manifest = {
            "manifest_schema_version": 1, "observation_schema_version": 2,
            "observation_profile": PROFILE_ID,
            "kind": "read-only reference collection; qualification metadata is private",
            "observations": "observations.jsonl", "samples": samples,
            "sha256": hashlib.sha256(observation_path.read_bytes()).hexdigest() if observation_path.exists() else None,
            "qualification_checks": "private_truth/qualification.jsonl",
            "qualification_checks_sha256": hashlib.sha256(qualification_path.read_bytes()).hexdigest() if qualification_path.exists() else None,
            "polls_are_atomic": False, "partial_collection": status == "aborted",
            "channels": {name: asdict(spec) for name, spec in AIRBORNE_CHANNELS.items()},
            **provenance,
        }
        _json_file(output / "manifest.json", manifest)
        summary["artifacts_complete"] = True
        _json_file(private / "summary.json", summary)
    print(f"{status}: {samples} observation polls saved to {output.resolve()}", flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--config", type=Path, help="Optional JSON qualification settings; defaults are provisional project choices")
    parser.add_argument("--max-wait-seconds", type=float, default=120.0)
    parser.add_argument("--interval-seconds", type=float, default=1.0)
    parser.add_argument("--port", type=int, default=8088)
    args = parser.parse_args()
    result = collect_reference(args.output, load_settings(args.config), max_wait_s=args.max_wait_seconds,
                               interval_s=args.interval_seconds, port=args.port)
    if result["status"] != "qualified_recorded_window":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
