"""Native replay contrasts and explicit missing/contradictory-evidence fixtures."""

from pathlib import Path
import unittest

from aircraft_debugger.airborne_profile import iter_profile_observations, validate_propulsion_observation
from aircraft_debugger.diagnosis import analyze_diagnosis
from aircraft_debugger.diagnostic_session import DiagnosisSession
from aircraft_debugger.hypotheses import propulsion_model
from aircraft_debugger.observations import ObservationFormatError
from aircraft_debugger.propulsion_study import _ablate
from aircraft_debugger.sim_panel import validate_command


STUDY = Path(__file__).resolve().parents[1] / "results/engine-drive-20261106-01"
ENGINE = "engine_2_power_loss"
PAIR = "independent_generator_yellow_pump_loss"
SUPPLY = "yellow_pressure_follows_measured_supply"


def recording(name):
    return list(iter_profile_observations(STUDY / name / "observations.jsonl"))


class PropulsionTests(unittest.TestCase):
    def test_native_shared_drive_and_separate_source_losses_are_distinguished(self):
        for name, candidate in (("engine-auto", ENGINE), ("pair-auto", PAIR)):
            with self.subTest(name=name):
                rows = recording(name)
                model = propulsion_model()
                offline = analyze_diagnosis(rows, model=model)
                self.assertEqual(offline["diagnosis"]["candidate_ids"], [candidate])
                self.assertEqual(offline["diagnosis"]["status"], "single_compatible_candidate")
                self.assertEqual(offline["candidate_evidence_support"][candidate]["percent"], 100)
                self.assertEqual(offline["temporal_relations"][SUPPLY]["status"], "consistent")
                self.assertEqual(offline["evidence"]["yellow_line_pressure_loss"]["state"], "not_observed")
                session = DiagnosisSession(model=model)
                for row in rows:
                    live = session.advance(row)
                self.assertEqual(live["result"], offline["diagnosis"])

    def test_missing_drive_readings_preserve_both_causal_alternatives(self):
        rows = _ablate(recording("engine-auto"), ("engine_2_n2", "engine_2_fuel_flow"))
        report = analyze_diagnosis(rows, model=propulsion_model())
        self.assertEqual(report["diagnosis"]["candidate_ids"], [])
        self.assertEqual(set(report["diagnosis"]["plausible_candidate_ids"]), {ENGINE, PAIR})
        self.assertEqual(report["candidate_evidence_support"][ENGINE]["percent"], 71)

    def test_yellow_low_pressure_is_expected_with_the_backup_inhibited(self):
        rows = recording("engine-off")
        report = analyze_diagnosis(rows, model=propulsion_model())
        self.assertEqual(report["diagnosis"]["candidate_ids"], [ENGINE])
        self.assertEqual(report["evidence"]["yellow_line_pressure_loss"]["state"], "observed")
        self.assertIn("without measured backup", report["temporal_relations"][SUPPLY]["reason"])
        missing_backup = _ablate(rows, ("yellow_electric_pressure", "yellow_transfer_pressure"))
        unresolved = analyze_diagnosis(missing_backup, model=propulsion_model())
        self.assertEqual(unresolved["temporal_relations"][SUPPLY]["status"], "unknown")
        self.assertEqual(unresolved["candidate_evidence_support"][ENGINE]["percent"], 86)

    def test_retained_line_with_no_measured_supply_contradicts_the_settled_prediction(self):
        rows = recording("engine-off")
        # Evidence-only counterexample. No simulator output or native archive is modified.
        for row in rows:
            row["readings"]["yellow_pressure"]["value"] = 3000.0
        report = analyze_diagnosis(rows, model=propulsion_model())
        self.assertEqual(report["temporal_relations"][SUPPLY]["status"], "contradicted")
        self.assertEqual(report["diagnosis"]["status"], "poor_model_fit")

    def test_additional_blue_loss_requires_a_second_path(self):
        rows = recording("engine-auto")
        for row in rows:
            if row["readings"]["engine_2_n2"]["value"] < 20:
                row["readings"]["blue_pressure"]["value"] = 0.0
        diagnosis = analyze_diagnosis(rows, model=propulsion_model())["diagnosis"]
        self.assertEqual(set(diagnosis["candidate_ids"]),
                         {"independent_engine_blue_pressure_loss", "grouped_engine_blue_pressure_loss"})
        engine_only = next(item for item in diagnosis["candidates"] if item["id"] == ENGINE)
        self.assertEqual(engine_only["status"], "contradicted")

    def test_propulsion_checks_require_the_pinned_airborne_context(self):
        for channel, value in (("aircraft", "A320neo-CFM"), ("main_gear_1_wow", True)):
            with self.subTest(channel=channel):
                rows = recording("engine-off")[-2:]
                for row in rows:
                    row["readings"][channel]["value"] = value
                report = analyze_diagnosis(rows, model=propulsion_model())
                self.assertEqual(report["evidence"]["engine_2_core_speed_loss"]["state"], "unknown")
                self.assertNotIn(ENGINE, report["diagnosis"]["candidate_ids"])

    def test_propulsion_profile_rejects_native_operator_flags(self):
        row = recording("engine-auto")[0]
        with self.assertRaisesRegex(ObservationFormatError, "require schema 1 or 2"):
            analyze_diagnosis([row])
        row["readings"]["engine_2_cutoff_fault"] = row["readings"]["ptu_selected"]
        with self.assertRaisesRegex(ObservationFormatError, "unknown channels"):
            validate_propulsion_observation(row)
        with self.assertRaisesRegex(ValueError, "Unknown fault"):
            validate_command({"fault": "engine_2_cutoff", "enabled": True})
