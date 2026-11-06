"""Controller ownership/privacy checks with mocked transport and a virtual clock.

Fixture values only select controller branches. They are not a physical aircraft
model and these tests do not replace the connected FlightGear response checks.
"""

from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from aircraft_debugger import cross_system
from aircraft_debugger.flightgear import PropertyReading, TelemetrySnapshot
from aircraft_debugger.observations import CHANNELS, iter_observations
from aircraft_debugger.sim_panel import FAULT_PATHS


class VirtualClock:
    def __init__(self):
        self.now = 100.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class ControllerTransport:
    def __init__(self, clock):
        self.clock = clock
        self.flags = {fault: False for fault in FAULT_PATHS}
        self.effects = set()
        self.poll_count = 0
        self.freeze_clock = False
        self.reset_clock_when_active = False
        self.freeze_clock_when_active = False
        self.last_sim_time = None
        self.ground_contact = True

    def poll(self, channels):
        self.poll_count += 1
        self.clock.now += 0.2
        sim_time = 10.0 if self.freeze_clock else self.clock.now
        if self.reset_clock_when_active and self.effects:
            sim_time = 0.1
        if self.freeze_clock_when_active and self.effects:
            sim_time = self.last_sim_time
        self.last_sim_time = sim_time
        values = {
            "aircraft": "A320-200-CFM", "sim_time": sim_time,
            "paused": False, "altitude": 35.0, "airspeed": 0.0,
            "engine_1_n1": 70.0, "engine_2_n1": 70.0,
            "generator_2_voltage": 0.0 if "generator_2" in self.effects else 115.0,
            "ac_bus_1": 115.0, "ac_bus_2": 115.0, "blue_pressure": 3000.0,
            "blue_quantity": 7.0 if "blue_leak" in self.effects else 8.0,
        }
        readings = {
            name: PropertyReading(spec.path, values[name], True, None, values["sim_time"],
                                  self.clock.now, True, spec.unit)
            for name, spec in channels.items()
        }
        return TelemetrySnapshot(readings, True, True, self.clock.now)

    def read_property(self, path, kind="number", unit=""):
        if path in FAULT_PATHS.values():
            fault = next(name for name, candidate in FAULT_PATHS.items() if candidate == path)
            value = self.flags[fault]
        elif path == "/systems/acconfig/autoconfig-running":
            value = False
        elif path in ("/engines/engine[0]/running", "/engines/engine[1]/running"):
            value = True
        elif path == "/gear/gear[1]/wow":
            value = self.ground_contact
        else:
            raise AssertionError(f"Unexpected private readiness read {path}")
        return PropertyReading(path, value, True, None, self.clock.now, self.clock.now, True, unit)


class ControllerOperator:
    def __init__(self, transport):
        self.transport = transport
        self.calls = []
        self.uncertain_enable = None
        self.external_fault_after_enable = None
        self.reject_cleanup = False

    def command(self, payload):
        fault, enabled = payload["fault"], payload["enabled"]
        self.calls.append((fault, enabled))
        if not enabled and self.reject_cleanup:
            return 502, {"ok": False, "error": "mock native cleanup rejected"}
        self.transport.flags[fault] = enabled
        if enabled:
            self.transport.effects.add(fault)
        else:
            self.transport.effects.discard(fault)
        if enabled and fault == self.uncertain_enable:
            if self.external_fault_after_enable:
                self.transport.flags[self.external_fault_after_enable] = True
            return 502, {"ok": False, "error": "mock acknowledgement lost after write applied"}
        return 200, {"ok": True, "enabled": enabled}


class CrossSystemControllerTests(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get("AIRCRAFT_DEBUGGER_TEST_TMP", "Z:/aircraft-debugger/work/tests"))
        base.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "new-run"
        self.clock = VirtualClock()
        self.transport = ControllerTransport(self.clock)
        self.operator = ControllerOperator(self.transport)
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.client_factory = self.patches.enter_context(patch.object(
            cross_system, "FlightGearClient", return_value=self.transport
        ))
        self.panel_factory = self.patches.enter_context(patch.object(
            cross_system, "PanelState", return_value=self.operator
        ))
        self.patches.enter_context(patch.object(cross_system.time, "monotonic", self.clock.monotonic))
        self.patches.enter_context(patch.object(cross_system.time, "sleep", self.clock.sleep))
        self.patches.enter_context(patch.object(
            cross_system.subprocess, "run", return_value=SimpleNamespace(stdout="fixture-commit\n")
        ))

    def run_controller(self):
        return cross_system.run_experiment(self.output, baseline_s=3, active_s=6, interval_s=1)

    def private_log(self):
        return json.loads((self.output / "private_truth" / "experiment.json").read_text(encoding="utf-8"))

    def test_preexisting_native_fault_is_refused_without_files_or_changes(self):
        # Healthy-looking selected gauges do not authorize clearing a native flag.
        self.transport.flags["blue_leak"] = True
        with self.assertRaisesRegex(RuntimeError, "blue_leak flag is not clear"):
            self.run_controller()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.operator.calls, [])
        self.panel_factory.assert_not_called()
        self.assertEqual(self.transport.flags, {"generator_2": False, "blue_leak": True, "blue_pump": False})

    def test_existing_output_folder_is_preserved_without_operator_commands(self):
        self.output.mkdir()
        sentinel = self.output / "preserve-me.txt"
        sentinel.write_text("existing approved result\n", encoding="utf-8")
        before = hashlib.sha256(sentinel.read_bytes()).hexdigest()
        with self.assertRaises(FileExistsError):
            self.run_controller()
        self.assertEqual(hashlib.sha256(sentinel.read_bytes()).hexdigest(), before)
        self.assertEqual(list(self.output.iterdir()), [sentinel])
        self.assertEqual(self.operator.calls, [])
        self.panel_factory.assert_not_called()

    def test_low_airspeed_without_observed_ground_contact_is_refused(self):
        self.transport.ground_contact = False
        with self.assertRaisesRegex(RuntimeError, "Ground contact must be observed"):
            self.run_controller()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.operator.calls, [])
        self.panel_factory.assert_not_called()

    def test_applied_write_with_lost_acknowledgement_cleans_only_owned_attempt(self):
        self.patches.enter_context(patch.object(cross_system, "CASES", (
            ("isolated_generator_2", ("generator_2",)),
        )))
        self.operator.uncertain_enable = "generator_2"
        self.operator.external_fault_after_enable = "blue_leak"
        with self.assertRaisesRegex(RuntimeError, "write was not verified"):
            self.run_controller()
        self.assertEqual(self.operator.calls, [("generator_2", True), ("generator_2", False)])
        self.assertFalse(self.transport.flags["generator_2"])
        self.assertTrue(self.transport.flags["blue_leak"])
        log = self.private_log()
        self.assertFalse(log["completed"])
        self.assertEqual(log["cleanup_errors"], [])
        self.assertEqual(log["actions"][0]["status"], 502)
        records = list(iter_observations(self.output / "episode-001" / "observations.jsonl"))
        self.assertGreater(len(records), 1)
        self.assertFalse((self.output / "manifest.json").exists())

    def test_cleanup_failure_is_recorded_without_clearing_unowned_faults(self):
        self.patches.enter_context(patch.object(cross_system, "CASES", (
            ("isolated_generator_2", ("generator_2",)),
        )))
        self.operator.uncertain_enable = "generator_2"
        self.operator.reject_cleanup = True
        with self.assertRaisesRegex(RuntimeError, "write was not verified"):
            self.run_controller()
        self.assertTrue(self.transport.flags["generator_2"])
        self.assertEqual(self.operator.calls, [("generator_2", True), ("generator_2", False)])
        log = self.private_log()
        self.assertFalse(log["completed"])
        self.assertEqual([error["fault"] for error in log["cleanup_errors"]], ["generator_2"])

    def test_nonadvancing_baseline_keeps_partial_observations_without_enabling_faults(self):
        self.transport.freeze_clock = True
        with self.assertRaisesRegex(RuntimeError, "clock did not advance"):
            self.run_controller()
        self.assertEqual(self.operator.calls, [])
        self.assertFalse(self.private_log()["completed"])
        records = list(iter_observations(self.output / "episode-001" / "observations.jsonl"))
        self.assertGreater(len(records), 1)

    def test_simulator_epoch_reset_during_active_sampling_cleans_owned_fault(self):
        self.patches.enter_context(patch.object(cross_system, "CASES", (
            ("isolated_generator_2", ("generator_2",)),
        )))
        self.transport.reset_clock_when_active = True
        with self.assertRaisesRegex(RuntimeError, "Simulator clock reset"):
            self.run_controller()
        self.assertEqual(self.operator.calls, [("generator_2", True), ("generator_2", False)])
        self.assertFalse(self.transport.flags["generator_2"])
        self.assertFalse(self.private_log()["completed"])
        records = list(iter_observations(self.output / "episode-001" / "observations.jsonl"))
        self.assertEqual(records[-1]["readings"]["sim_time"]["value"], 0.1)
        self.assertGreater(records[-2]["readings"]["sim_time"]["value"], 0.1)

    def test_clock_freeze_after_advancing_baseline_rejects_active_phase_and_cleans_fault(self):
        self.patches.enter_context(patch.object(cross_system, "CASES", (
            ("isolated_generator_2", ("generator_2",)),
        )))
        self.transport.freeze_clock_when_active = True
        with self.assertRaisesRegex(RuntimeError, "clock did not advance during sampling phase"):
            self.run_controller()
        self.assertEqual(self.operator.calls, [("generator_2", True), ("generator_2", False)])
        self.assertFalse(self.transport.flags["generator_2"])
        log = self.private_log()
        self.assertFalse(log["completed"])
        records = list(iter_observations(self.output / "episode-001" / "observations.jsonl"))
        baseline_count = log["episodes"][0]["baseline_sample_count"]
        baseline_times = [row["readings"]["sim_time"]["value"] for row in records[:baseline_count]]
        active_times = [row["readings"]["sim_time"]["value"] for row in records[baseline_count:]]
        self.assertGreater(baseline_times[-1], baseline_times[0])
        self.assertGreater(len(active_times), 1)
        self.assertEqual(len(set(active_times)), 1)

    def test_artifact_metadata_failure_does_not_mark_collection_as_completed_run(self):
        self.patches.enter_context(patch.object(cross_system, "CASES", (
            ("selected_reference", ()),
        )))
        original_save = cross_system._save

        def fail_summary_save(path, value):
            if path.name == "summary.json":
                raise OSError("mock summary artifact unavailable")
            return original_save(path, value)

        for stage in ("git_metadata", "summary_artifact"):
            with self.subTest(stage=stage), ExitStack() as patches:
                self.output = self.root / stage
                if stage == "git_metadata":
                    patches.enter_context(patch.object(cross_system.subprocess, "run", side_effect=OSError("mock git unavailable")))
                else:
                    patches.enter_context(patch.object(cross_system, "_save", side_effect=fail_summary_save))
                with self.assertRaises(OSError):
                    self.run_controller()
                log = self.private_log()
                self.assertTrue(log["collection_completed"])
                self.assertFalse(log["completed"])
                self.assertTrue(all(not flag for flag in self.transport.flags.values()))
                self.assertFalse((self.output / "private_truth" / "summary.json").exists())

    def test_successful_collection_keeps_labels_and_actions_out_of_public_artifacts(self):
        result = self.run_controller()
        self.assertEqual(len(result["episodes"]), 5)
        self.assertTrue(self.private_log()["completed"])
        self.assertTrue(all(not flag for flag in self.transport.flags.values()))
        manifest = json.loads((self.output / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["episodes"]), 5)
        self.assertIn('aircraft_debugger/diagnostic_session.py', manifest['source_sha256'])
        for name, digest in manifest['source_sha256'].items():
            self.assertEqual(hashlib.sha256(Path(name).read_bytes()).hexdigest(), digest)
        forbidden = ("private_label", "requested_faults", "operator interventions",
                     "synthetic_shared_regional_event", "independent_pair_matched_interventions")
        for episode in manifest["episodes"]:
            path = self.output / episode["observations"]
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), episode["sha256"])
            records = list(iter_observations(path))
            self.assertTrue(all(set(row["readings"]) == set(CHANNELS) for row in records))
            self.assertEqual([row["sample_index"] for row in records], list(range(len(records))))
            for label in forbidden:
                self.assertNotIn(label, path.read_text(encoding="utf-8"))
        public_manifest = (self.output / "manifest.json").read_text(encoding="utf-8")
        for label in forbidden:
            self.assertNotIn(label, public_manifest)


if __name__ == "__main__":
    unittest.main()
