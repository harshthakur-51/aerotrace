"""Experiment-controller boundaries, using transport fixtures and a virtual clock.

Numbers select software branches only: this is not a model of aircraft response.
No test talks to FlightGear or sends native HTTP writes.
"""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aircraft_debugger import airborne_experiment as experiment
from aircraft_debugger.airborne_admission import QualificationSettings, READINESS_CHANNELS
from aircraft_debugger.airborne_profile import AIRBORNE_CHANNELS, iter_profile_observations
from aircraft_debugger.flightgear import PropertyReading, TelemetrySnapshot
from aircraft_debugger.sim_panel import FAULT_PATHS


class Clock:
    def __init__(self):
        self.now = 100.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Transport:
    def __init__(self, clock):
        self.clock = clock
        self.flags = {name: False for name in FAULT_PATHS}
        self.polls = []
        self.public_count = 0
        self.freeze_after_enable = False
        self.reset_after_enable = False
        self.frozen_at = None
        self.bad_final = False
        self.initial_mismatch = "XX"
        self.transient_invalid = 0
        self.always_invalid_active = False
        self.stuck_generator_timestamp = False
        self.generator_timestamp = None
        self.timestamp_jump = False
        self.aircraft = "A320-200-CFM"

    def poll(self, channels):
        self.polls.append(tuple(channels))
        self.clock.now += 0.15
        active = any(self.flags.values())
        sim = self.clock.now
        if active and self.freeze_after_enable:
            if self.frozen_at is None:
                self.frozen_at = sim
            sim = self.frozen_at
        if active and self.reset_after_enable:
            sim = 1.0
        if active and self.timestamp_jump:
            sim += 20.0
        values = {
            "aircraft": self.aircraft, "sim_time": sim, "paused": False,
            "altitude": 10000.0, "airspeed": 250.0,
            "engine_1_n1": 70.0, "engine_2_n1": 70.0,
            "generator_2_voltage": 0.0 if self.flags["generator_2"] else 115.0,
            "ac_bus_1": 115.0, "ac_bus_2": 115.0,
            "blue_pressure": 3000.0, "blue_quantity": 7.0 if self.flags["blue_leak"] else 8.0,
            "main_gear_1_wow": False, "main_gear_2_wow": False,
            "height_agl": 9000.0, "vertical_speed": 0.0,
            "bank": 30.0 if active else 0.0,
            "autopilot_1": True, "autopilot_2": False, "autothrust": True,
            "startup_in_progress": False, "startup_mismatch_reason": self.initial_mismatch,
            "engine_1_running": True, "engine_2_running": True,
            "generator_2_fault": self.flags["generator_2"], "blue_leak_fault": self.flags["blue_leak"], "blue_pump_fault": self.flags["blue_pump"],
        }
        if set(channels) == set(AIRBORNE_CHANNELS):
            self.public_count += 1
            if self.bad_final and self.public_count >= 17:
                values["bank"] = 20.0
        readings = {
            name: PropertyReading(spec.path, values[name], True, None, sim, self.clock.now, True, spec.unit)
            for name, spec in channels.items()
        }
        if active and "generator_2_voltage" in readings and self.stuck_generator_timestamp:
            if self.generator_timestamp is None:
                self.generator_timestamp = sim
            spec = AIRBORNE_CHANNELS["generator_2_voltage"]
            readings["generator_2_voltage"] = PropertyReading(spec.path, values["generator_2_voltage"], True, None,
                self.generator_timestamp, self.clock.now, True, spec.unit)
        if active and "generator_2_voltage" in channels and (self.always_invalid_active or self.transient_invalid):
            spec = AIRBORNE_CHANNELS["generator_2_voltage"]
            readings["generator_2_voltage"] = PropertyReading(spec.path, None, False, "timeout", None,
                                                            self.clock.now, False, spec.unit)
            if self.transient_invalid:
                self.transient_invalid -= 1
        return TelemetrySnapshot(readings, True, all(item.valid for item in readings.values()), self.clock.now)

    def read_property(self, path, kind="number", unit=""):
        fault = next(name for name, candidate in FAULT_PATHS.items() if path == candidate)
        self.clock.now += 0.05
        return PropertyReading(path, self.flags[fault], True, None, self.clock.now, self.clock.now, True, unit)


class Operator:
    def __init__(self, transport):
        self.transport = transport
        self.calls = []
        self.lose_enable_ack = False
        self.raise_after_enable = False
        self.reject_cleanup = False
        self.false_cleanup_ack = False
        self.external_fault = None
        self.first_enable_public_count = None
        self.prewrite_delay = 0.0
        self.delay_second_enable = False
        self.posts = []
        self.aircraft = "A320-200-CFM"
        self.enable_aircraft_requirements = []
        self.change_variant_after_enable = False

    def command(self, payload, *, before_write_check=None, required_aircraft=None):
        fault, enabled = payload["fault"], payload["enabled"]
        self.calls.append((fault, enabled))
        self.transport.clock.now += 0.1
        if required_aircraft is not None and self.aircraft != required_aircraft:
            return 409, {"ok": False, "error": "fixture aircraft variant changed"}
        if enabled:
            self.enable_aircraft_requirements.append(required_aircraft)
            if not self.delay_second_enable or any(value for value in self.transport.flags.values()):
                self.transport.clock.now += self.prewrite_delay
            if before_write_check is not None:
                before_write_check()
        self.posts.append((fault, enabled))
        if not enabled and self.reject_cleanup:
            return 502, {"ok": False}
        if not (not enabled and self.false_cleanup_ack):
            self.transport.flags[fault] = enabled
        if enabled:
            self.first_enable_public_count = self.transport.public_count
            if self.external_fault:
                self.transport.flags[self.external_fault] = True
            if self.raise_after_enable:
                raise OSError("fixture response lost after enable applied")
            if self.lose_enable_ack:
                return 502, {"ok": False, "error": "fixture uncertain acknowledgement"}
            if self.change_variant_after_enable:
                self.aircraft = self.transport.aircraft = "A320-200-IAE"
                # The replacement aircraft's clear flag is not evidence that
                # the original aircraft's attempted intervention was cleared.
                self.transport.flags[fault] = False
        return 200, {"ok": True}


class AirborneExperimentTests(unittest.TestCase):
    def setUp(self):
        root = Path(os.environ.get("AIRCRAFT_DEBUGGER_TEST_TMP", "Z:/aircraft-debugger/work/tests"))
        root.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name) / "new-experiment"
        self.clock = Clock()
        self.client = Transport(self.clock)
        self.operator = Operator(self.client)

    def run_controller(self, case="isolated_generator_2", **kwargs):
        return experiment.run_experiment(self.output, case, QualificationSettings(),
            client=self.client, operator=self.operator, monotonic=self.clock.monotonic,
            sleep=self.clock.sleep, **kwargs)

    def summary(self):
        return json.loads((self.output / "private_truth/summary.json").read_text())

    def records(self):
        return list(iter_profile_observations(self.output / "observations.jsonl"))

    def actions(self):
        return [json.loads(line) for line in (self.output / "private_truth/actions.jsonl").read_text().splitlines()]

    def test_complete_case_qualifies_freshly_and_records_out_of_band_active_and_recovery(self):
        result = self.run_controller()
        self.assertTrue(result["completed"])
        self.assertTrue(result["artifacts_complete"])
        self.assertEqual(self.operator.calls, [("generator_2", True), ("generator_2", False)])
        self.assertGreaterEqual(self.operator.first_enable_public_count, 17)
        rows = self.records()
        baseline = result["baseline_end_sample_index_exclusive"]
        self.assertGreaterEqual(rows[baseline - 1]["readings"]["sim_time"]["value"] - rows[0]["readings"]["sim_time"]["value"], 16)
        private_checks = [json.loads(line) for line in (self.output / "private_truth/qualification.jsonl").read_text().splitlines()]
        self.assertEqual(private_checks[-1]["phase"], "final_pre_intervention")
        self.assertTrue(private_checks[-1]["gate"]["qualified"])
        self.assertEqual([row["sample_index"] for row in rows], list(range(len(rows))))
        self.assertTrue(all(set(row["readings"]) == set(AIRBORNE_CHANNELS) for row in rows))
        active, recovery = result["phases"]
        self.assertGreaterEqual(active["elapsed_sim_s"], 8)
        self.assertGreaterEqual(recovery["elapsed_sim_s"], 5)
        self.assertTrue(all(row["readings"]["bank"]["value"] == 30 for row in rows[active["first_sample_index"]:active["end_sample_index_exclusive"]]))
        self.assertEqual(rows[-1]["readings"]["generator_2_voltage"]["value"], 115)
        self.assertTrue(all(not value for value in self.client.flags.values()))

    def test_archived_operator_imports_without_access_to_active_checkout(self):
        import subprocess
        import sys
        self.run_controller()
        archive = self.output / 'private_truth/executed-source'
        program = ("import sys; from pathlib import Path; "
                   "sys.path.insert(0, sys.argv[1]); "
                   "from aircraft_debugger.sim_panel import PanelState; "
                   "import aircraft_debugger.sim_panel as panel_module; "
                   "assert Path(panel_module.__file__).is_relative_to(Path(sys.argv[1])); "
                   "assert PanelState(None)._diagnostic_session.count == 0")
        result = subprocess.run([sys.executable, '-I', '-B', '-c', program, str(archive.resolve())],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_live_observer_gets_exact_public_records_without_control_metadata(self):
        from aircraft_debugger.sim_panel import ObservationPanelState
        from aircraft_debugger.diagnosis import analyze_diagnosis
        observer=ObservationPanelState()
        received=[]
        def accept(row):
            received.append(row)
            observer.accept(row)
        self.run_controller(on_observation=accept)
        rows=self.records()
        self.assertEqual(received,rows)
        self.assertEqual(observer.get_state()['diagnosis']['result'],analyze_diagnosis(rows)['diagnosis'])
        self.assertTrue(observer.get_state()['read_only'])
        self.assertEqual(observer.command({'fault':'generator_2','enabled':True})[0],409)
        self.assertFalse(any('phase' in row or 'requested_faults' in row for row in received))

    def test_observer_mutation_cannot_rewrite_control_or_recorded_evidence(self):
        def mutate(row):
            row['readings']['aircraft']['value']='mutated'
            row['sample_index']=-1
        result=self.run_controller(on_observation=mutate)
        self.assertTrue(result['completed'])
        self.assertTrue(all(row['readings']['aircraft']['value']=='A320-200-CFM' for row in self.records()))
        self.assertEqual([r['sample_index'] for r in self.records()],list(range(result['samples'])))

    def test_observer_failure_after_enable_keeps_native_cleanup_guarantee(self):
        def fail_active(row):
            if self.client.flags['generator_2']:
                raise RuntimeError('observer fixture unavailable')
        with self.assertRaisesRegex(RuntimeError,'observer fixture unavailable'):
            self.run_controller(on_observation=fail_active)
        self.assertEqual(self.operator.calls,[('generator_2',True),('generator_2',False)])
        self.assertFalse(any(self.client.flags.values()))
        self.assertEqual(self.summary()['status'],'aborted')
        self.assertTrue(self.records())

    def test_non_callable_observer_is_rejected_before_simulator_access(self):
        with self.assertRaises(ValueError):self.run_controller(on_observation=True)
        self.assertEqual(self.client.polls,[])

    def test_pressure_supply_case_keeps_pump_commands_private_and_cleans_owned_flag(self):
        received=[]
        result=self.run_controller('isolated_blue_pressure_supply',on_observation=received.append)
        self.assertTrue(result['completed'])
        self.assertEqual(self.operator.calls,[('blue_pump',True),('blue_pump',False)])
        self.assertFalse(any(self.client.flags.values()))
        self.assertTrue(all('blue_pump_fault' not in row['readings'] for row in received))

    def test_preexisting_pump_failure_is_not_adopted_or_cleared(self):
        self.client.flags['blue_pump']=True
        with self.assertRaises(RuntimeError):self.run_controller('isolated_blue_pressure_supply')
        self.assertEqual(self.operator.calls,[])
        self.assertTrue(self.client.flags['blue_pump'])

    def test_public_stream_and_manifest_exclude_private_phase_case_and_commands(self):
        self.run_controller("synthetic_shared_regional_event")
        public = (self.output / "observations.jsonl").read_text()
        manifest_text = (self.output / "manifest.json").read_text()
        for token in ("synthetic_shared_regional_event", '"phase"', '"enabled"', '"qualified"'):
            self.assertNotIn(token, public)
            self.assertNotIn(token, manifest_text)
        for spec in READINESS_CHANNELS.values():
            self.assertNotIn(spec.path, public)
            self.assertNotIn(spec.path, manifest_text)
        manifest = json.loads(manifest_text)
        for path_key, hash_key in (("observations", "sha256"), ("qualification_checks", "qualification_checks_sha256"),
                                   ("operator_actions", "operator_actions_sha256"), ("qualification_settings", "qualification_settings_sha256")):
            self.assertEqual(hashlib.sha256((self.output / manifest[path_key]).read_bytes()).hexdigest(), manifest[hash_key])
        for source, digest in manifest["source_sha256"].items():
            self.assertEqual(hashlib.sha256((self.output / manifest["executed_source_archives"][source]).read_bytes()).hexdigest(), digest)

    def test_existing_folder_and_preexisting_fault_are_never_changed(self):
        self.output.mkdir()
        sentinel = self.output / "keep.txt"
        sentinel.write_text("preserve")
        with self.assertRaises(FileExistsError):
            self.run_controller()
        self.assertEqual(self.client.polls, [])
        self.assertEqual(sentinel.read_text(), "preserve")
        self.output = self.output.parent / "refused-fault"
        self.client.flags["blue_leak"] = True
        with self.assertRaisesRegex(RuntimeError, "blue_leak flag"):
            self.run_controller()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.operator.calls, [])
        self.assertTrue(self.client.flags["blue_leak"])

    def test_timeout_retains_baseline_and_never_enables_with_bad_native_mismatch(self):
        self.client.initial_mismatch = "not ready"
        result = self.run_controller(max_wait_s=18)
        self.assertEqual(result["status"], "not_qualified")
        self.assertFalse(result["completed"])
        self.assertTrue(result["artifacts_complete"])
        self.assertGreater(len(self.records()), 1)
        self.assertEqual(self.operator.calls, [])

    def test_final_new_sample_failure_revokes_qualified_baseline_before_any_enable(self):
        self.client.bad_final = True
        with self.assertRaisesRegex(RuntimeError, "Fresh final admission failed"):
            self.run_controller()
        self.assertEqual(self.operator.calls, [])
        self.assertFalse(self.summary()["last_gate"]["qualified"])
        self.assertEqual(self.records()[-1]["readings"]["bank"]["value"], 20)

    def test_uncertain_applied_enable_cleans_only_owned_fault_for_status_and_exception(self):
        for exception in (False, True):
            with self.subTest(exception=exception):
                self.output = self.output.parent / ("uncertain-exception" if exception else "uncertain-status")
                self.client = Transport(self.clock)
                self.operator = Operator(self.client)
                self.operator.lose_enable_ack = not exception
                self.operator.raise_after_enable = exception
                self.operator.external_fault = "blue_leak"
                with self.assertRaises((RuntimeError, OSError)):
                    self.run_controller()
                self.assertEqual(self.operator.calls, [("generator_2", True), ("generator_2", False)])
                self.assertFalse(self.client.flags["generator_2"])
                self.assertTrue(self.client.flags["blue_leak"])
                self.assertEqual(self.summary()["pending_faults_unverified_clear"], [])
                self.assertFalse(self.summary()["completed"])
                self.assertEqual(self.actions()[0]["stage"], "attempt")

    def test_false_cleanup_ack_is_independently_detected_and_retained_as_partial(self):
        self.operator.false_cleanup_ack = True
        with self.assertRaisesRegex(RuntimeError, "cleanup was not verified"):
            self.run_controller()
        result = self.summary()
        self.assertFalse(result["completed"])
        self.assertEqual(result["pending_faults_unverified_clear"], ["generator_2"])
        self.assertTrue(result["cleanup_errors"])
        self.assertTrue(self.client.flags["generator_2"])
        self.assertTrue((self.output / "manifest.json").exists())

    def test_admission_expiry_is_checked_after_delayed_operator_prechecks_before_post(self):
        self.operator.prewrite_delay = 2.1
        with self.assertRaisesRegex(RuntimeError, "expired before native POST"):
            self.run_controller()
        self.assertFalse(any(enabled for _, enabled in self.operator.posts))
        self.assertFalse(any(self.client.flags.values()))
        self.assertFalse(self.summary()["completed"])

    def test_paired_second_enable_also_requires_unexpired_prepost_deadline(self):
        self.operator.prewrite_delay = 2.1
        self.operator.delay_second_enable = True
        with self.assertRaisesRegex(RuntimeError, "expired before native POST"):
            self.run_controller("synthetic_shared_regional_event")
        self.assertEqual([fault for fault, enabled in self.operator.posts if enabled], ["generator_2"])
        self.assertFalse(any(self.client.flags.values()))
        self.assertEqual(self.summary()["pending_faults_unverified_clear"], [])

    def test_aircraft_change_after_enable_refuses_cleanup_post_and_keeps_ownership_uncertain(self):
        self.operator.change_variant_after_enable = True
        with self.assertRaisesRegex(RuntimeError, "Observed aircraft changed"):
            self.run_controller()
        self.assertEqual(self.operator.enable_aircraft_requirements, ["A320-200-CFM"])
        self.assertEqual(self.operator.posts, [("generator_2", True)])
        self.assertFalse(self.client.flags["generator_2"])
        result = self.summary()
        self.assertEqual(result["status"], "aborted")
        self.assertFalse(result["completed"])
        self.assertEqual(result["pending_faults_unverified_clear"], ["generator_2"])
        self.assertEqual([item["fault"] for item in result["cleanup_errors"]], ["generator_2"])

    def test_qualification_timeout_during_final_poll_never_enables(self):
        with self.assertRaisesRegex(RuntimeError, "Qualification local deadline exceeded"):
            self.run_controller(max_wait_s=16.2)
        self.assertEqual(self.operator.calls, [])
        self.assertFalse(self.summary()["completed"])

    def test_frozen_and_reset_active_clocks_abort_with_observations_and_cleanup(self):
        for reset in (False, True):
            with self.subTest(reset=reset):
                self.output = self.output.parent / ("clock-reset" if reset else "clock-freeze")
                self.client = Transport(self.clock)
                self.operator = Operator(self.client)
                self.client.reset_after_enable = reset
                self.client.freeze_after_enable = not reset
                with self.assertRaisesRegex(RuntimeError, "clock reset|time stopped advancing|clock stopped advancing"):
                    self.run_controller()
                self.assertFalse(self.client.flags["generator_2"])
                self.assertFalse(self.summary()["completed"])
                self.assertGreater(len(self.records()), self.summary()["baseline_end_sample_index_exclusive"])
                self.assertEqual(self.operator.calls[-1], ("generator_2", False))

    def test_transient_invalid_postfault_values_are_preserved_then_collection_can_continue(self):
        self.client.transient_invalid = 2
        result = self.run_controller()
        invalid = [row for row in self.records() if not row["readings"]["generator_2_voltage"]["valid"]]
        self.assertEqual(len(invalid), 2)
        self.assertTrue(all(row["readings"]["generator_2_voltage"]["value"] is None for row in invalid))
        self.assertTrue(result["completed"])

    def test_stuck_required_channel_timestamp_and_large_clock_jump_cannot_complete(self):
        for jump in (False, True):
            with self.subTest(jump=jump):
                self.output = self.output.parent / ("timestamp-jump" if jump else "stuck-channel")
                self.client = Transport(self.clock)
                self.operator = Operator(self.client)
                self.client.stuck_generator_timestamp = not jump
                self.client.timestamp_jump = jump
                with self.assertRaisesRegex(RuntimeError, "time stopped advancing|timestamp gap|unavailable"):
                    self.run_controller()
                self.assertFalse(self.summary()["collection_completed"])
                self.assertFalse(self.client.flags["generator_2"])
                self.assertTrue(self.records()[-1]["complete"])

    def test_persistent_transport_failure_and_whole_postfault_deadline_are_bounded(self):
        self.client.always_invalid_active = True
        with self.assertRaisesRegex(RuntimeError, "unavailable|time stopped advancing"):
            self.run_controller()
        self.assertFalse(self.client.flags["generator_2"])
        self.assertTrue(any(not row["complete"] for row in self.records()))
        self.output = self.output.parent / "whole-deadline"
        self.client = Transport(self.clock)
        self.operator = Operator(self.client)
        with self.assertRaisesRegex(RuntimeError, "local deadline"):
            self.run_controller(maximum_postfault_local_s=1)
        self.assertFalse(self.client.flags["generator_2"])
        self.assertFalse(self.summary()["completed"])

    def test_artifact_failure_after_cleanup_does_not_mark_completed(self):
        original = experiment._save

        def fail_manifest(path, value):
            if path.name == "manifest.json":
                raise OSError("fixture disk artifact failure")
            return original(path, value)

        with patch.object(experiment, "_save", side_effect=fail_manifest), self.assertRaises(OSError):
            self.run_controller()
        self.assertFalse(self.client.flags["generator_2"])
        result = self.summary()
        self.assertTrue(result["collection_completed"])
        self.assertFalse(result["completed"])
        self.assertFalse(result["artifacts_complete"])

    def test_selected_reference_writes_no_faults_and_short_qualification_is_rejected(self):
        result = self.run_controller("selected_reference")
        self.assertTrue(result["completed"])
        self.assertEqual(self.operator.calls, [])
        with self.assertRaisesRegex(ValueError, "at least 15"):
            experiment.run_experiment(self.output.parent / "bad-duration", settings=QualificationSettings(qualification_duration_sim_s=1),
                                      client=self.client, operator=self.operator)


if __name__ == "__main__":
    unittest.main()
