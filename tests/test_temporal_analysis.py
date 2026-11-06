"""Timing regressions. The generated rows exercise evidence logic only."""
from pathlib import Path
import unittest

from aircraft_debugger.airborne_profile import iter_profile_observations
from aircraft_debugger.temporal_analysis import analyze_timing
from test_diagnosis import sample


BOUNDS = {"generator_source_anomaly": [0, 3], "blue_pressure_loss": [0, 10]}
ROOT = Path(__file__).resolve().parents[1]


class TemporalAnalysisTests(unittest.TestCase):
    def test_near_synchronous_native_effects_preserve_both_candidates(self):
        path = ROOT / "results/pressure-pair-20261106-01/pair/observations.jsonl"
        incident, = analyze_timing(iter_profile_observations(path), response_bounds=BOUNDS)["incidents"]
        self.assertEqual(incident["shared_trigger"]["status"], "consistent")
        fit = [item for item in incident["candidates"] if item["status"] == "compatible"]
        self.assertEqual({item["id"] for item in fit},
                         {"independent_pressure_pair", "grouped_pressure_joint_event"})
        self.assertTrue(all(item["evidence_support"]["percent"] == 100 for item in fit))

    def test_separated_onsets_exclude_bounded_trigger_unless_coverage_is_missing(self):
        for missing in ((), ("blue_pressure",)):
            with self.subTest(missing=missing):
                rows = [sample(i, generator=0 if i >= 2 else 115,
                               pressure=1000 if i >= 20 else 3000,
                               missing=missing if i == 10 else ()) for i in range(25)]
                incident, = analyze_timing(rows, response_bounds=BOUNDS)["incidents"]
                timing = incident["shared_trigger"]
                self.assertEqual(timing["status"], "unknown" if missing else "contradicted")
                grouped = next(item for item in incident["candidates"] if item["id"] == "grouped_pressure_joint_event")
                self.assertEqual(grouped["evidence_support"]["percent"], 75 if missing else None)
                self.assertEqual(grouped["status"], "unconfirmed_timing" if missing else "contradicted_under_response_bounds")

    def test_recovered_source_and_later_pressure_loss_are_separate_incidents(self):
        rows = [sample(i, generator=0 if 2 <= i <= 4 else 115,
                       pressure=1000 if 9 <= i <= 12 else 3000) for i in range(15)]
        incidents = analyze_timing(rows, response_bounds=BOUNDS)["incidents"]
        self.assertEqual([item["v2_compatible_ids"] for item in incidents],
                         [["generator_2_source_path_fault"], ["blue_pressure_supply_loss"]])
        self.assertTrue(all(item["scope"]["closed"] for item in incidents))
        self.assertTrue(all(window["state"] != "both_degraded"
                            for item in incidents for window in item["joint_windows"]))
