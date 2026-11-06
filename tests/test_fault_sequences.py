"""Verify the private plan and public generated diagnoses independently."""

from pathlib import Path
import unittest
from unittest.mock import patch

from aircraft_debugger.airborne_profile import iter_profile_observations
from aircraft_debugger.diagnosis import analyze_diagnosis
from aircraft_debugger.diagnostic_session import DiagnosisSession
from aircraft_debugger.hypotheses import generated_model
from aircraft_debugger.sequence_plan import FAULTS, make_plan, onset_groups


RESULTS = Path(__file__).resolve().parents[1] / "results"
YELLOW = "yellow_engine_driven_pump_supply_loss"
GENERATOR = "generator_2_source_path_fault"
ENGINE = "engine_2_power_loss"


def recording(relative):
    return list(iter_profile_observations(RESULTS / relative / "observations.jsonl"))


class FaultSequenceTests(unittest.TestCase):
    def test_all_onset_groupings_are_unique_and_planned_timing_is_consistent(self):
        orders = list(onset_groups())
        self.assertEqual(len(orders), 1081)
        self.assertEqual(len(set(orders)), len(orders))
        self.assertEqual(len({frozenset(fault for group in order for fault in group) for order in orders}), 31)
        self.assertTrue(all(sum(map(len, order)) == len(set().union(*order)) for order in orders))
        self.assertIn((FAULTS,), orders)
        plan = make_plan(hold_s=20, overlap_spacing_s=3, clear_gap_s=7)
        self.assertEqual(plan["strict_order_count"], 325)
        self.assertEqual(plan["trial_count"], 2131)
        self.assertEqual(plan["run_permission"], "planning_only")
        for trial in plan["trials"]:
            for left, right in zip(trial["onsets"], trial["onsets"][1:]):
                delta = right["enable_offset_sim_s"] - left["release_offset_sim_s"]
                self.assertEqual(delta, -17 if trial["timing"] == "overlap" else 7)

    def test_generated_catalogue_finds_isolated_pump_from_public_rows(self):
        rows = recording("yellow-edp-isolated-20261106-01/run")
        model = generated_model()
        self.assertEqual(len({frozenset(item["roots"]) for item in model["candidates"]}), 32)
        with patch("builtins.open", side_effect=AssertionError("Diagnosis must use only supplied rows")):
            report = analyze_diagnosis(rows, model=model)
        self.assertEqual(report["diagnosis"]["minimal_candidate_ids"], [YELLOW])
        self.assertEqual(report["diagnosis"]["additional_compatible_ids"], [])
        self.assertEqual(report["candidate_evidence_support"][YELLOW]["percent"], 100)
        session = DiagnosisSession(model=model)
        for row in rows:
            live = session.advance(row)
        self.assertEqual(live["result"], report["diagnosis"])

    def test_native_engine_cascade_retains_masked_alternatives(self):
        rows = recording("engine-drive-20261106-01/engine-off")
        result = analyze_diagnosis(rows, model=generated_model())["diagnosis"]
        self.assertEqual(result["minimal_candidate_ids"], [ENGINE])
        self.assertEqual(len(result["additional_compatible_ids"]), 3)
        self.assertFalse(result["cause_identifiable"])

    def test_early_generator_loss_requires_an_additional_path_in_one_incident(self):
        rows = recording("engine-drive-20261106-01/engine-off")
        # Constructed timing contrast from copied observations, for software verification.
        for row in rows[8:]:
            row["readings"]["generator_2_voltage"]["value"] = 0.0
        report = analyze_diagnosis(rows, model=generated_model())
        self.assertEqual(report["diagnosis"]["minimal_candidate_ids"], [f"{GENERATOR}+{ENGINE}"])
        self.assertEqual(report["temporal_relations"]["generator_loss_with_drive_retained"]["status"], "contradicted")
        self.assertEqual(len(report["incidents"]), 1)

    def test_earlier_blue_pressure_loss_can_have_its_own_path(self):
        rows = recording("yellow-edp-isolated-20261106-01/run")
        for row in rows[7:]:
            row["readings"]["blue_pressure"]["value"] = 1000.0
        for row in rows[15:]:
            row["readings"]["blue_quantity"]["value"] = 7.0
        report = analyze_diagnosis(rows, model=generated_model())
        expected = f"blue_fluid_loss_mechanism+blue_pressure_supply_loss+{YELLOW}"
        self.assertEqual(report["diagnosis"]["minimal_candidate_ids"], [expected])
        self.assertEqual(report["temporal_relations"]["inventory_before_pressure"]["status"], "contradicted")

    def test_recovery_separates_observed_incidents(self):
        rows = recording("yellow-edp-isolated-20261106-01/run")
        for row in rows[4:8]:
            row["readings"]["generator_2_voltage"]["value"] = 0.0
        report = analyze_diagnosis(rows, model=generated_model())
        self.assertEqual([item["minimal_candidate_ids"] for item in report["incidents"]], [[GENERATOR], [YELLOW]])
        self.assertTrue(all(item["scope"]["closed"] for item in report["incidents"]))
