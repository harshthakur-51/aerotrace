"""Observation/protocol fixtures test software semantics, not aircraft physics."""

import copy
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from aircraft_debugger.airborne_evidence import analyze_airborne_observations, main
from aircraft_debugger.airborne_profile import AIRBORNE_CHANNELS, PROFILE_ID, iter_profile_observations
from aircraft_debugger.evidence import analyze_observations
from aircraft_debugger.observations import CHANNELS


def sample(index, *, generator=115.0, quantity=8.0, sim_time=None, changes=None):
    simulator = 100.0 + index if sim_time is None else sim_time
    local = 1000.0 + index
    values = {"aircraft": "A320-200-CFM", "sim_time": simulator, "paused": False,
        "altitude": 10000.0, "airspeed": 250.0, "engine_1_n1": 80.0, "engine_2_n1": 80.0,
        "generator_2_voltage": generator, "ac_bus_1": 115.0, "ac_bus_2": 115.0,
        "blue_quantity": quantity, "blue_pressure": 3000.0,
        "main_gear_1_wow": False, "main_gear_2_wow": False, "height_agl": 7000.0,
        "vertical_speed": 0.0, "bank": 0.0, "autopilot_1": False, "autopilot_2": False, "autothrust": False}
    values.update(changes or {})
    readings = {name: {"path": spec.path, "value": values[name], "valid": True, "error": None,
        "sim_time_s": simulator, "received_monotonic_s": local + .1, "reachable": True, "unit": spec.unit}
        for name, spec in AIRBORNE_CHANNELS.items()}
    return {"schema_version": 2, "observation_profile": PROFILE_ID, "sample_index": index,
        "poll_started_monotonic_s": local, "received_monotonic_s": local + .2,
        "readings": readings, "connected": True, "complete": True}


def trace(kind="pair"):
    electrical, hydraulic = kind in ("generator", "pair"), kind in ("hydraulic", "pair")
    return [sample(0), sample(1), sample(2, generator=0 if electrical else 115, quantity=7.75 if hydraulic else 8),
            sample(3, generator=0 if electrical else 115, quantity=7.4 if hydraulic else 8)]


class AirborneEvidenceTests(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get("AIRCRAFT_DEBUGGER_TEST_TMP", "work/tests"))
        base.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def test_selected_detectors_keep_generator_inventory_and_pair_ambiguity_with_all_context(self):
        for kind, expected in (("generator", "isolated_electrical_anomaly"), ("hydraulic", "hydraulic_depletion"), ("pair", "multiple_system_anomalies")):
            rows = trace(kind)
            original = copy.deepcopy(rows)
            report = analyze_airborne_observations(iter(rows))
            with self.subTest(kind=kind):
                self.assertEqual(report["assessment"]["category"], expected)
                self.assertEqual(report["observation_profile"], PROFILE_ID)
                self.assertEqual(report["airborne_context"]["retained_observations"], original)
                self.assertEqual(rows, original)
                self.assertEqual(len(report["airborne_context"]["latest_channels"]), 20)
                self.assertEqual(report["current_state"]["blue_pressure"]["status"], "pressure_retained")
        self.assertEqual({item["hypothesis"] for item in report["explanations"]},
                         {"shared regional damage", "independent electrical/hydraulic faults"})
        self.assertEqual({item["compatibility"] for item in report["explanations"]}, {"equally_compatible"})
        self.assertFalse(report["assessment"]["probabilities_computed"])

    def test_missing_and_invalid_context_remain_unknown_without_erasing_inventory_evidence(self):
        rows = trace("hydraulic")
        rows[-1]["readings"].pop("autopilot_1")
        height = rows[-1]["readings"]["height_agl"]
        height.update(value=None, valid=False, error="missing_property", sim_time_s=None)
        rows[-1]["complete"] = False
        report = analyze_airborne_observations(rows)
        context = report["airborne_context"]
        self.assertEqual(report["assessment"]["category"], "hydraulic_depletion")
        self.assertFalse(report["assessment"]["complete_current_assessment"])
        self.assertIsNone(context["automation"]["values"]["autopilot_1"])
        self.assertFalse(context["automation"]["complete"])
        self.assertIsNone(context["latest_channels"]["height_agl"]["value"])
        self.assertEqual(context["latest_channels"]["height_agl"]["status"], "unknown")
        self.assertEqual(context["airborne_indications"], "unknown")

    def test_post_change_motion_and_automation_departures_are_retained_without_stability_filtering(self):
        rows = trace()
        rows.append(sample(4, generator=0, quantity=7.1,
            changes={"bank": 18, "altitude": 10750, "vertical_speed": 20, "autopilot_1": True, "autothrust": True}))
        report = analyze_airborne_observations(rows)
        context = report["airborne_context"]
        self.assertEqual(report["assessment"]["category"], "multiple_system_anomalies")
        self.assertEqual(report["sample_count"], 5)
        self.assertFalse(context["stability_filter_applied"])
        self.assertFalse(context["qualification_evaluated"])
        self.assertEqual(context["latest_channels"]["bank"]["value"], 18)
        self.assertEqual(context["latest_channels"]["altitude"]["value"], 10750)
        changes = {item.get("channel") for item in context["changes"] if item["kind"] == "observed_value_changed"}
        self.assertTrue({"bank", "altitude", "vertical_speed", "autopilot_1", "autothrust"}.issubset(changes))
        self.assertTrue(context["automation"]["values"]["autopilot_1"])

    def test_paused_frozen_and_reset_final_samples_are_historical_not_current_healthy_context(self):
        endings = [sample(4, changes={"paused": True}), sample(4, sim_time=103), sample(4, sim_time=0)]
        for ending in endings:
            with self.subTest(ending=ending["readings"]["sim_time"]["value"]):
                report = analyze_airborne_observations(trace() + [ending])
                self.assertEqual(report["assessment"]["category"], "insufficient_current_evidence")
                self.assertFalse(report["airborne_context"]["quality"]["time_progressing"])
                self.assertIsNone(report["airborne_context"]["latest_channels"]["bank"]["value"])
                self.assertTrue(any(event["kind"] == "blue_inventory_loss" for event in report["ledger"]))
                self.assertEqual(len(report["airborne_context"]["retained_observations"]), 5)
        self.assertEqual(report["airborne_context"]["quality"]["epoch"], 1)

    def test_stale_or_nonadvancing_automation_is_unknown_while_other_evidence_remains(self):
        for stale in (False, True):
            rows = trace()
            rows[-1]["readings"]["autopilot_1"]["sim_time_s"] = 102
            if stale:
                rows[-1]["poll_started_monotonic_s"] -= 3
                rows[-1]["readings"]["autopilot_1"]["received_monotonic_s"] -= 3
            report = analyze_airborne_observations(rows)
            self.assertIsNone(report["airborne_context"]["automation"]["values"]["autopilot_1"])
            self.assertFalse(report["assessment"]["complete_current_assessment"])
            self.assertEqual(report["assessment"]["category"], "multiple_system_anomalies")

    def test_legacy_and_airborne_apis_remain_explicit_and_private_extras_are_rejected(self):
        row = sample(0)
        legacy = {key: value for key, value in row.items() if key != "observation_profile"}
        legacy["schema_version"] = 1
        legacy["readings"] = {name: value for name, value in row["readings"].items() if name in CHANNELS}
        with self.assertRaises(ValueError):
            analyze_airborne_observations([legacy])
        with self.assertRaises(ValueError):
            analyze_observations([row])
        for modification in ("private_top", "private_channel", "numeric_bool"):
            contaminated = copy.deepcopy(row)
            if modification == "private_top":
                contaminated["initiating_cause"] = "shared regional damage"
            elif modification == "private_channel":
                contaminated["readings"]["blue_leak_fault"] = contaminated["readings"]["paused"]
            else:
                contaminated["readings"]["autopilot_1"]["value"] = 0
            with self.subTest(modification=modification), self.assertRaises(ValueError):
                analyze_airborne_observations([contaminated])

    def test_cli_reads_only_the_named_observations_and_preserves_exact_file_hash(self):
        observations = self.directory / "observations.jsonl"
        observations.write_text("".join(json.dumps(row) + "\n" for row in trace()), encoding="utf-8")
        (self.directory / "private_truth").mkdir()
        (self.directory / "private_truth" / "manifest.json").write_text('{"cause":"must not be read"}', encoding="utf-8")
        (self.directory / "manifest.json").write_text("not diagnostic input", encoding="utf-8")
        output = self.directory / "report"
        original_open = Path.open
        reads = []

        def guarded_open(path, mode="r", *args, **kwargs):
            if "r" in mode:
                self.assertEqual(path.resolve(), observations.resolve(), "Unexpected adjacent/private file read")
                reads.append(path)
            return original_open(path, mode, *args, **kwargs)

        with patch.object(Path, "open", new=guarded_open), patch.object(sys, "argv", ["airborne_evidence", "--observations", str(observations), "--output", str(output)]):
            with redirect_stdout(io.StringIO()):
                main()
        self.assertGreaterEqual(len(reads), 1)
        report = json.loads((output / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["input_provenance"]["observation_file_sha256"], hashlib.sha256(observations.read_bytes()).hexdigest())
        self.assertTrue((output / "report.md").is_file())
        for name in ("report.json", "report.md"):
            self.assertNotIn(b"\r\n", (output / name).read_bytes())
        with patch.object(sys, "argv", ["airborne_evidence", "--observations", str(observations), "--output", str(output)]), self.assertRaises(SystemExit):
            with redirect_stderr(io.StringIO()):
                main()

    def test_saved_native_reference_replays_offline_without_becoming_a_fault_validation_claim(self):
        observations = Path(__file__).resolve().parents[1] / "results" / "airborne-reference-20261027-01" / "observations.jsonl"
        report = analyze_airborne_observations(iter_profile_observations(observations))
        repeated = analyze_airborne_observations(iter_profile_observations(observations))
        self.assertEqual(report, repeated)
        self.assertGreater(report["sample_count"], 1)
        self.assertEqual(report["assessment"]["category"], "no_fault_observed")
        self.assertEqual(report["airborne_context"]["airborne_indications"], "airborne_indications_observed")
        self.assertFalse(report["airborne_context"]["qualification_evaluated"])
        self.assertEqual(len(report["airborne_context"]["channel_specs"]), 20)

    def test_native_blue_refill_prefixes_keep_known_pressure_anomaly_with_complete_context(self):
        observations = Path(__file__).resolve().parents[1] / "results" / "airborne-contrast-20261029-01" / "observations.jsonl"
        # Only explicit public observations enter inference; no phase/action or
        # private case file is read to label the pressure-only recovery interval.
        rows = list(iter_profile_observations(observations))
        for last in range(71, 76):
            with self.subTest(last_sample=last):
                with patch.object(Path, "open", side_effect=AssertionError("Inference must not read adjacent files")):
                    report = analyze_airborne_observations(rows[:last + 1])
                self.assertEqual(report["assessment"]["category"], "hydraulic_pressure_anomaly")
                self.assertTrue(report["assessment"]["complete_current_assessment"])
                self.assertFalse(report["assessment"]["cause_identifiable"])
                self.assertEqual(report["current_state"]["blue_inventory"]["value_raw"], 8)
                self.assertEqual(report["current_state"]["blue_pressure"]["status"], "pressure_degraded")
                self.assertTrue(report["airborne_context"]["quality"]["all_twenty_current_usable"])
                self.assertEqual(report["airborne_context"]["retained_observations"], rows[:last + 1])
                self.assertEqual([event["kind"] for event in report["ledger"]],
                                 ["blue_inventory_loss", "blue_quantity_returned_to_reference"])
        self.assertEqual(analyze_airborne_observations(rows[:71])["assessment"]["category"], "hydraulic_depletion")
        self.assertEqual(analyze_airborne_observations(rows)["assessment"]["category"], "no_fault_observed")


if __name__ == "__main__":
    unittest.main()
