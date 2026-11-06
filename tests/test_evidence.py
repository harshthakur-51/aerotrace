"""Behavioural counterexamples for the observation-only replay demonstrator."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from aircraft_debugger.evidence import analyze_observations
from aircraft_debugger.observations import CHANNELS, iter_observations


def sample(index, *, generator=115.0, quantity=8.0, pressure=3000.0, bus=115.0,
           sim_time=None, paused=False, missing=(), channel_times=None):
    sim_time = float(index + 100) if sim_time is None else sim_time
    local_time = 1000.0 + index
    values = {"aircraft": "A320-200-CFM", "sim_time": sim_time, "paused": paused,
              "altitude": 30000.0, "airspeed": 250.0, "engine_1_n1": 80.0, "engine_2_n1": 80.0,
              "generator_2_voltage": generator, "ac_bus_1": 115.0, "ac_bus_2": bus,
              "blue_pressure": pressure, "blue_quantity": quantity}
    readings = {}
    for name, spec in CHANNELS.items():
        if name in missing:
            continue
        readings[name] = {"path": spec.path, "value": values[name], "valid": True, "error": None,
            "sim_time_s": (channel_times or {}).get(name, sim_time), "received_monotonic_s": local_time + .1,
            "reachable": True, "unit": spec.unit}
    return {"schema_version": 1, "sample_index": index, "poll_started_monotonic_s": local_time,
            "received_monotonic_s": local_time + .2, "readings": readings,
            "connected": bool(readings), "complete": not missing}


def paired_trace():
    return [sample(0), sample(1), sample(2, generator=0, quantity=7.75),
            sample(3, generator=0, quantity=7.5), sample(4, generator=0, quantity=7.25)]


class EvidenceTests(unittest.TestCase):
    def test_matching_observations_under_different_private_causes_stay_ambiguous(self):
        # Replay paths and sibling private histories differ; observable bytes do
        # not. The cause answer must be identical and must not read those labels.
        Path("work").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir="work") as temporary:
            root = Path(temporary)
            reports = []
            for name, label in (("shared-regional", "shared regional damage"), ("independent", "independent faults")):
                episode = root / name
                episode.mkdir()
                (episode / "private_truth.json").write_text(json.dumps({"cause": label}))
                observations = episode / "observations.jsonl"
                observations.write_text("".join(json.dumps(row) + "\n" for row in paired_trace()))
                output = root / (name + "-report")
                completed = subprocess.run([sys.executable, "-B", "-m", "aircraft_debugger.evidence",
                    "--observations", str(observations), "--output", str(output)], capture_output=True, text=True)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                reports.append(json.loads((output / "report.json").read_text()))
            self.assertEqual(reports[0], reports[1])
            report = reports[0]
            self.assertEqual(report["assessment"]["category"], "multiple_system_anomalies")
            self.assertFalse(report["assessment"]["cause_identifiable"])
            self.assertEqual({item["hypothesis"] for item in report["explanations"]},
                             {"shared regional damage", "independent electrical/hydraulic faults"})
            self.assertEqual({item["compatibility"] for item in report["explanations"]}, {"equally_compatible"})

    def test_zero_source_output_with_retained_bus_is_not_total_bus_loss(self):
        report = analyze_observations([sample(0), sample(1), sample(2, generator=0), sample(3, generator=-.01)])
        self.assertEqual(report["assessment"]["category"], "isolated_electrical_anomaly")
        self.assertEqual(report["current_state"]["ac_bus_2"]["status"], "supply_retained")
        self.assertIn("total bus loss is not observed", report["impact"][0]["remaining_capability"])
        event = next(item for item in report["ledger"] if item["kind"] == "generator_2_source_unavailable")
        self.assertEqual(event["onset"]["sim_time_s"], 102)
        self.assertEqual(event["confirmation"]["sim_time_s"], 103)

    def test_inventory_loss_can_precede_pressure_change_and_missing_pressure_does_not_erase_it(self):
        trace = [sample(0), sample(1), sample(2, quantity=7.75), sample(3, quantity=7.4)]
        report = analyze_observations(trace)
        self.assertEqual(report["assessment"]["category"], "hydraulic_depletion")
        self.assertEqual(report["current_state"]["blue_pressure"]["status"], "pressure_retained")
        trace.append(sample(4, quantity=7.2, missing=("blue_pressure",)))
        report = analyze_observations(trace)
        self.assertEqual(report["assessment"]["category"], "hydraulic_depletion")
        self.assertEqual(report["current_state"]["blue_inventory"]["status"], "inventory_loss_observed")
        self.assertFalse(report["assessment"]["complete_current_assessment"])
        self.assertIn("unknown", report["impact"][0]["remaining_capability"])

    def test_missing_paused_frozen_and_reset_final_data_are_not_healthy(self):
        stale = sample(5)
        stale["received_monotonic_s"] += 3
        for final in [sample(5, missing=("generator_2_voltage", "blue_quantity")),
                      sample(5, paused=True), sample(5, sim_time=104), sample(5, sim_time=0), stale]:
            with self.subTest(final=final["readings"]["sim_time"]["value"]):
                report = analyze_observations(paired_trace() + [final])
                self.assertEqual(report["assessment"]["category"], "insufficient_current_evidence")
                self.assertTrue(any(item["kind"] == "blue_inventory_loss" for item in report["ledger"]))
                self.assertFalse(report["assessment"]["complete_current_assessment"])

    def test_per_reading_clock_freeze_prevents_confirmation_even_when_global_time_advances(self):
        trace = [sample(0), sample(1), sample(2, generator=0),
                 sample(3, generator=0, channel_times={"generator_2_voltage": 102})]
        report = analyze_observations(trace)
        self.assertFalse(any(item["kind"] == "generator_2_source_unavailable" for item in report["ledger"]))
        self.assertEqual(report["current_state"]["generator_2"]["status"], "insufficient_evidence")

    def test_recovery_preserves_original_quantity_reference_and_history(self):
        trace = [sample(0), sample(1), sample(2, quantity=7.2), sample(3, quantity=8), sample(4, quantity=7.3)]
        report = analyze_observations(trace)
        losses = [item for item in report["ledger"] if item["kind"] == "blue_inventory_loss"]
        self.assertEqual(len(losses), 2)
        self.assertEqual(report["current_state"]["blue_inventory"]["reference"]["value_raw"], 8)
        self.assertTrue(any(item["kind"] == "blue_quantity_returned_to_reference" for item in report["ledger"]))

    def test_refilled_inventory_with_lagging_pressure_is_an_observed_anomaly(self):
        trace = [sample(0), sample(1), sample(2, quantity=0, pressure=0),
                 sample(3, quantity=8, pressure=500), sample(4, quantity=8, pressure=2000)]
        for end in (4, 5):
            report = analyze_observations(trace[:end])
            with self.subTest(end=end):
                self.assertEqual(report["assessment"]["category"], "hydraulic_pressure_anomaly")
                self.assertTrue(report["assessment"]["complete_current_assessment"])
                self.assertFalse(report["assessment"]["cause_identifiable"])
                self.assertFalse(report["assessment"]["probabilities_computed"])
                self.assertEqual(report["current_state"]["blue_inventory"]["status"], "near_observed_reference")
                self.assertEqual(report["current_state"]["blue_pressure"]["status"], "pressure_degraded")
                self.assertIn("initiating cause", report["explanations"][0]["reason"])
                self.assertEqual([item["kind"] for item in report["ledger"]],
                                 ["blue_inventory_loss", "blue_quantity_returned_to_reference"])
                self.assertIn("Blue pressure", report["impact"][0]["observation"])
        recovered = analyze_observations(trace + [sample(5)])
        self.assertEqual(recovered["assessment"]["category"], "no_fault_observed")

    def test_pressure_only_with_missing_inventory_retains_evidence_and_incomplete_assessment(self):
        report = analyze_observations([sample(0), sample(1),
                                      sample(2, pressure=1000, missing=("blue_quantity",))])
        self.assertEqual(report["assessment"]["category"], "hydraulic_pressure_anomaly")
        self.assertFalse(report["assessment"]["complete_current_assessment"])
        self.assertFalse(report["assessment"]["cause_identifiable"])
        self.assertEqual(report["current_state"]["blue_inventory"]["status"], "insufficient_evidence")
        self.assertEqual(report["current_state"]["blue_pressure"]["status"], "pressure_degraded")
        self.assertEqual(report["current_state"]["blue_pressure"]["value_psi"], 1000)
        self.assertEqual(report["ledger"], [])
        self.assertIn("Pressure degradation is observed", report["impact"][0]["remaining_capability"])

    def test_concurrent_electrical_and_pressure_only_anomalies_remain_ambiguous(self):
        for electrical in ({"generator": 0}, {"bus": 0}):
            with self.subTest(electrical=electrical):
                report = analyze_observations([sample(0), sample(1),
                    sample(2, pressure=1000, **electrical), sample(3, pressure=500, **electrical)])
                self.assertEqual(report["assessment"]["category"], "multiple_system_anomalies")
                self.assertTrue(report["assessment"]["complete_current_assessment"])
                self.assertFalse(report["assessment"]["cause_identifiable"])
                self.assertEqual(report["current_state"]["blue_inventory"]["status"], "near_observed_reference")
                self.assertEqual({item["hypothesis"] for item in report["explanations"]},
                                 {"shared regional damage", "independent electrical/hydraulic faults"})
                self.assertEqual({item["compatibility"] for item in report["explanations"]}, {"equally_compatible"})
                self.assertTrue(all("hydraulic-pressure" in item["reason"] for item in report["explanations"]))
                self.assertTrue(any(item["system"] == "hydraulic" for item in report["impact"]))

    def test_unavailable_pressure_does_not_reuse_a_previous_pressure_anomaly_or_become_healthy(self):
        stale = sample(2, pressure=1000)
        stale["poll_started_monotonic_s"] -= 3
        stale["readings"]["blue_pressure"]["received_monotonic_s"] -= 3
        endings = [sample(2, pressure=1000, missing=("blue_pressure",)),
                   sample(2, pressure=1000, paused=True),
                   sample(2, pressure=1000, channel_times={"blue_pressure": 101}), stale]
        for number, final in enumerate(endings):
            with self.subTest(number=number):
                report = analyze_observations([sample(0), sample(1, pressure=1000), final])
                self.assertEqual(report["assessment"]["category"], "insufficient_current_evidence")
                self.assertFalse(report["assessment"]["complete_current_assessment"])
                self.assertEqual(report["current_state"]["blue_pressure"]["status"], "insufficient_evidence")
                self.assertFalse(any(item["system"] == "hydraulic" for item in report["impact"]))

    def test_five_saved_ground_reports_preserve_exact_legacy_dictionaries(self):
        base = Path(__file__).resolve().parents[1] / "results" / "cross-system-20261026-01"
        for number in range(1, 6):
            name = f"episode-{number:03d}"
            with self.subTest(episode=name):
                saved = json.loads((base / "analysis" / name / "report.json").read_text(encoding="utf-8"))
                replayed = analyze_observations(iter_observations(base / name / "observations.jsonl"))
                self.assertEqual(replayed, saved)

    def test_privileged_fields_are_rejected_instead_of_becoming_evidence(self):
        record = sample(0)
        contaminated = copy.deepcopy(record)
        contaminated["initiating_cause"] = "shared regional damage"
        with self.assertRaises(ValueError):
            analyze_observations([contaminated])
        self.assertEqual(analyze_observations([record, sample(1)])["assessment"]["category"], "no_fault_observed")


if __name__ == "__main__":
    unittest.main()
