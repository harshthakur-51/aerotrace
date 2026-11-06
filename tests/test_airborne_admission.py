"""Airborne eligibility counterexamples; synthetic fixtures, no simulator access."""

import copy
from dataclasses import FrozenInstanceError, replace
import json
import unittest

from aircraft_debugger.airborne_admission import AirborneAdmission, QualificationSettings, READINESS_CHANNELS
from aircraft_debugger.airborne_profile import AIRBORNE_CHANNELS, PROFILE_ID
from aircraft_debugger.flightgear import PropertyReading, TelemetrySnapshot


def sample(index, *, sim_time=None, local_time=None, changes=None):
    simulator = 100.0 + index if sim_time is None else sim_time
    local = 1000.0 + index if local_time is None else local_time
    values = {"aircraft": "A320-200-CFM", "sim_time": simulator, "paused": False,
        "altitude": 10000.0, "airspeed": 250.0, "engine_1_n1": 80.0, "engine_2_n1": 80.0,
        "generator_2_voltage": 115.0, "ac_bus_1": 115.0, "ac_bus_2": 115.0,
        "blue_quantity": 8.0, "blue_pressure": 3000.0,
        "main_gear_1_wow": False, "main_gear_2_wow": False, "height_agl": 7000.0,
        "vertical_speed": 0.0, "bank": 0.0, "autopilot_1": False, "autopilot_2": False, "autothrust": False}
    values.update(changes or {})
    readings = {name: {"path": spec.path, "value": values[name], "valid": True, "error": None,
        "sim_time_s": simulator, "received_monotonic_s": local + .1, "reachable": True, "unit": spec.unit}
        for name, spec in AIRBORNE_CHANNELS.items()}
    record = {"schema_version": 2, "observation_profile": PROFILE_ID, "sample_index": index,
        "poll_started_monotonic_s": local, "received_monotonic_s": local + .2,
        "readings": readings, "connected": True, "complete": True}
    expected = {"startup_in_progress": False, "startup_mismatch_reason": "".join(("X", "X")), "engine_1_running": True, "engine_2_running": True,
                "generator_2_fault": False, "blue_leak_fault": False, "blue_pump_fault": False}
    private = {name: PropertyReading(spec.path, expected[name], True, None, simulator + .1,
               local + .3, True, spec.unit) for name, spec in READINESS_CHANNELS.items()}
    readiness = TelemetrySnapshot(private, True, True, local + .4)
    return record, readiness, local + .5


class AirborneAdmissionTests(unittest.TestCase):
    def qualify(self, gate=None):
        gate = gate or AirborneAdmission()
        result = None
        for index in range(16):
            result = gate.update(*sample(index))
            if index < 15:
                self.assertFalse(result["qualified"])
        self.assertTrue(result["qualified"])
        return gate, result

    def test_advancing_fifteen_second_reference_qualifies_with_observed_automation_off(self):
        _, result = self.qualify()
        self.assertEqual(result["window_elapsed_sim_s"], 15)
        self.assertEqual(result["window_start"]["sample_index"], 0)
        self.assertEqual(result["window_end"]["sample_index"], 15)
        self.assertEqual(result["reasons"], [])

    def test_ground_contact_terrain_clearance_and_flight_bands_are_independent_checks(self):
        counterexamples = [
            {"main_gear_1_wow": True}, {"main_gear_2_wow": True},
            {"height_agl": 5}, {"altitude": 0}, {"altitude": 15000},
            {"airspeed": 100}, {"bank": 10}, {"vertical_speed": 10},
            {"aircraft": "A320neo-CFM"}, {"blue_quantity": 7.5}, {"ac_bus_1": 0},
        ]
        for changes in counterexamples:
            with self.subTest(changes=changes):
                gate = AirborneAdmission()
                for index in range(17):
                    result = gate.update(*sample(index, changes=changes))
                self.assertFalse(result["qualified"])
                self.assertFalse(result["eligible_current_sample"])
        # Non-zero terrain is expected; negative terrain elevation is possible.
        result = AirborneAdmission().update(*sample(0, changes={"height_agl": 10500}))
        self.assertTrue(result["eligible_current_sample"])

    def test_unknown_or_numeric_boolean_flags_cannot_enable_qualification(self):
        cases = []
        record, readiness, evaluated = sample(0)
        record["readings"].pop("main_gear_1_wow")
        record["complete"] = False
        cases.append((record, readiness, evaluated))
        record, readiness, evaluated = sample(0)
        record["readings"]["main_gear_1_wow"]["value"] = 0
        cases.append((record, readiness, evaluated))
        for name in READINESS_CHANNELS:
            record, readiness, evaluated = sample(0)
            readiness.readings[name] = replace(readiness.readings[name], value=0)
            cases.append((record, readiness, evaluated))
        record, readiness, evaluated = sample(0)
        readiness.readings.pop("generator_2_fault")
        cases.append((record, replace(readiness, complete=False), evaluated))
        for case in cases:
            with self.subTest(case=cases.index(case)):
                self.assertFalse(AirborneAdmission().update(*case)["eligible_current_sample"])

    def test_failed_sample_revokes_previous_qualification_and_keeps_inputs_read_only(self):
        gate, _ = self.qualify()
        args = sample(16, changes={"main_gear_2_wow": True})
        original_record, original_readiness = copy.deepcopy(args[0]), copy.deepcopy(args[1])
        result = gate.update(*args)
        self.assertFalse(result["qualified"])
        self.assertIsNone(result["window_start"])
        self.assertEqual(args[0], original_record)
        self.assertEqual(args[1], original_readiness)
        self.assertEqual(gate.update(*sample(17))["window_elapsed_sim_s"], 0)

    def test_pauses_global_and_per_channel_freezes_and_resets_restart_the_window(self):
        for case in ("paused", "global_frozen", "channel_frozen", "reset", "private_frozen"):
            gate, _ = self.qualify()
            record, readiness, evaluated = sample(16)
            if case == "paused":
                record["readings"]["paused"]["value"] = True
            elif case == "global_frozen":
                record["readings"]["sim_time"]["value"] = 115
            elif case == "channel_frozen":
                record["readings"]["height_agl"]["sim_time_s"] = 115
            elif case == "reset":
                record, readiness, evaluated = sample(16, sim_time=1)
            else:
                name = "engine_1_running"
                readiness.readings[name] = replace(readiness.readings[name], sim_time_s=115.1)
            with self.subTest(case=case):
                result = gate.update(record, readiness, evaluated)
                self.assertFalse(result["qualified"])
                self.assertFalse(result["eligible_current_sample"])

    def test_stale_data_skew_excessive_poll_spans_and_gaps_never_bridge_a_window(self):
        for case in ("stale", "private_stale", "skew", "poll_span", "sim_gap", "local_gap", "index_gap", "completion_future"):
            gate = AirborneAdmission()
            gate.update(*sample(0))
            record, readiness, evaluated = sample(1)
            if case == "stale":
                evaluated += 3
            elif case == "private_stale":
                name = "engine_2_running"
                readiness.readings[name] = replace(readiness.readings[name], received_monotonic_s=998)
            elif case == "skew":
                record["readings"]["height_agl"]["sim_time_s"] = 104
            elif case == "poll_span":
                record["poll_started_monotonic_s"] -= 3
            elif case == "sim_gap":
                record, readiness, evaluated = sample(1, sim_time=104)
            elif case == "local_gap":
                record, readiness, evaluated = sample(1, local_time=1004)
            elif case == "index_gap":
                record["sample_index"] = 2
            else:
                # Every individual reading is in the past; only the reported
                # observation completion claims to be after evaluation.
                record["received_monotonic_s"] = evaluated + .1
            with self.subTest(case=case):
                result = gate.update(record, readiness, evaluated)
                self.assertFalse(result["eligible_current_sample"])
                self.assertEqual(result["window_elapsed_sim_s"], 0)
                if case == "completion_future":
                    self.assertIn("observation_clock_invalid", result["reasons"])

    def test_automation_change_restarts_the_context_without_requiring_engagement(self):
        gate, _ = self.qualify()
        result = gate.update(*sample(16, changes={"autopilot_1": True, "autothrust": True}))
        self.assertFalse(result["qualified"])
        self.assertIn("automation_context_changed", result["reasons"])
        for index in range(17, 33):
            result = gate.update(*sample(index, changes={"autopilot_1": True, "autothrust": True}))
        self.assertTrue(result["qualified"])

    def test_initialization_failures_return_only_generic_public_eligibility(self):
        for name in READINESS_CHANNELS:
            record, readiness, evaluated = sample(0)
            wrong = not readiness.readings[name].value if READINESS_CHANNELS[name].kind == "bool" else "configuration aborted"
            readiness.readings[name] = replace(readiness.readings[name], value=wrong)
            result = AirborneAdmission().update(record, readiness, evaluated)
            encoded = json.dumps(result)
            self.assertFalse(result["eligible_current_sample"])
            for private_name, spec in READINESS_CHANNELS.items():
                self.assertNotIn(private_name, encoded)
                self.assertNotIn(spec.path, encoded)

    def test_finished_or_aborted_initialization_with_mismatch_cannot_remain_qualified(self):
        gate, _ = self.qualify()
        record, readiness, evaluated = sample(16)
        # All other checks pass, including startup-in-progress=false. That flag
        # alone also follows native abort paths, so mismatch must be checked too.
        readiness.readings["startup_mismatch_reason"] = replace(readiness.readings["startup_mismatch_reason"], value="Initialization mismatch")
        result = gate.update(record, readiness, evaluated)
        self.assertFalse(result["qualified"])
        self.assertIn("initialization_reference_not_ready", result["reasons"])
        self.assertNotIn("Initialization mismatch", json.dumps(result))

    def test_settings_are_frozen_finite_and_reject_boolean_numeric_options(self):
        for changes in ({"altitude_target_ft": True}, {"maximum_sim_gap_s": float("nan")},
                        {"maximum_reading_age_s": float("inf")}, {"qualification_duration_sim_s": 0},
                        {"maximum_abs_bank_deg": -1}, {"airspeed_tolerance_kt": 251}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                QualificationSettings(**changes)
        settings = QualificationSettings()
        with self.assertRaises(FrozenInstanceError):
            settings.altitude_target_ft = 9000


if __name__ == "__main__":
    unittest.main()
