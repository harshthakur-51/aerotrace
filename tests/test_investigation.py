import unittest
from pathlib import Path

from aircraft_debugger.airborne_profile import iter_profile_observations
from aircraft_debugger.diagnostic_session import DiagnosisSession
from aircraft_debugger.hypotheses import generated_model
from aircraft_debugger.investigation import evaluate_counterfactual, select_evidence
from aircraft_debugger.replay_panel import ReplayPanelState
from aircraft_debugger.sequence_reasoning import analyze_sequences


_ENGINE = "engine_2_power_loss"
_GEN = "generator_2_source_path_fault"
_YELLOW = "yellow_engine_driven_pump_supply_loss"
_BLUE_SUPPLY = "blue_pressure_supply_loss"
_BLUE_INVENTORY = "blue_fluid_loss_mechanism"
_ARCHIVE = (Path(__file__).resolve().parents[1] / "results"
            / "engine-drive-20261106-01/engine-auto/observations.jsonl")


class InvestigationTests(unittest.TestCase):
    def setUp(self):
        self.model = generated_model()
        self.rows = list(iter_profile_observations(_ARCHIVE))

    def test_counterfactual_uses_actual_exclusions_and_observations(self):
        epoch, = analyze_sequences(self.rows, counterfactual={"only": [_GEN]})["epochs"]
        queries = epoch["investigation"]["counterfactuals"]
        without = next(item for item in queries if item["exclude"] == [_ENGINE])
        self.assertEqual(without["status"], "excluded")
        only = queries[-1]
        self.assertEqual(only["status"], "excluded")
        self.assertEqual(len(only["rejected_explanations"]), 1)
        facts = {item["fact"] for item in only["rejected_explanations"][0]["contradictions"] if "fact" in item}
        self.assertIn("engine_2_fuel_flow_loss", facts)
        self.assertIn("yellow_edp_output_loss", facts)
        with self.assertRaises(ValueError):
            evaluate_counterfactual(epoch, self.model, only=[_GEN], exclude=[_GEN])

    def test_withheld_drive_channels_split_explanations_but_are_not_actionable(self):
        original, = analyze_sequences(self.rows)["epochs"]
        for row in self.rows:
            row["readings"].pop("engine_2_n2")
            row["readings"].pop("engine_2_fuel_flow")
            row["complete"] = False
        epoch, = analyze_sequences(self.rows)["epochs"]
        investigation = epoch["investigation"]
        evidence = investigation["evidence_selection"]
        self.assertEqual(evidence["status"], "no_actionable_discriminator")
        self.assertEqual(evidence["recommended_measurements"], [])
        self.assertEqual([len(group) for group in evidence["currently_indistinguishable_groups"]],
                         [evidence["candidate_count"]])
        self.assertEqual({item["fact"] for item in evidence["unavailable_discriminators"]},
                         {"engine_2_core_speed_loss", "engine_2_fuel_flow_loss"})
        for item in evidence["unavailable_discriminators"]:
            partitions = item["predicted_partitions"]
            self.assertEqual(item["availability"], "unavailable_or_unusable")
            self.assertEqual(len(partitions["unknown"]), evidence["candidate_count"])
            self.assertTrue(all(_ENGINE in candidate.split("+") for candidate in partitions["observed"]))
            self.assertTrue(all(_ENGINE not in candidate.split("+") for candidate in partitions["not_observed"]))
            self.assertGreater(item["minimum_eliminated_if_conclusive"], 0)
            actual = {candidate["id"] for candidate in original["mechanism_sets"] if candidate["history_counts"]["compatible"]}
            self.assertTrue(actual <= set(partitions["observed"]))
        without = evaluate_counterfactual(epoch, self.model, exclude=[_ENGINE])
        self.assertEqual(without["status"], "unconfirmed")
        self.assertIn(f"{_GEN}+{_YELLOW}", [item["id"] for item in without["surviving_explanations"]])

    def test_conditional_effect_survives_both_outcomes_and_gap_blocks_action(self):
        ids = ("selected_reference", _GEN)
        candidate_roots = ([], [_GEN])
        fact = "bus_supply_loss"
        epoch = {
            "facts": {name: {"state": "unknown" if name == fact else "not_observed"} for name in self.model["facts"]},
            "mechanism_sets": [{"id": name, "roots": roots, "history_counts": {"compatible": 0, "unconfirmed": 1}}
                               for name, roots in zip(ids, candidate_roots)],
            "investigation_context": {"usable_channels": ["ac_bus_2"]},
        }
        result = select_evidence(epoch, self.model)
        item, = result["recommended_measurements"]
        self.assertEqual(item["predicted_partitions"]["observed"], [_GEN])
        self.assertEqual(item["predicted_partitions"]["not_observed"], list(ids))
        self.assertEqual(item["minimum_eliminated_if_conclusive"], 0)
        epoch["facts"][fact]["coverage"] = {"unavailable_sample_indices": [2]}
        self.assertEqual(select_evidence(epoch, self.model)["recommended_measurements"], [])

    def test_archived_cascade_retains_locals_and_measured_backup_as_distinct_forms_of_masking(self):
        epoch, = analyze_sequences(self.rows)["epochs"]
        investigation = epoch["investigation"]
        masking = investigation["masking"]
        self.assertEqual(masking["minimal_compatible_explanations"], [_ENGINE])
        self.assertEqual(len(masking["additional_compatible_fault_sets"]), 3)
        self.assertEqual({item["mechanism"] for item in masking["potentially_masked_mechanisms"]}, {_GEN, _YELLOW})
        yellow = next(item for item in masking["conditional_downstream_effects"]
                      if item["downstream_effect"] == "yellow_line_pressure_loss")
        self.assertEqual(yellow["status"], "measured_retention_with_backup")
        self.assertEqual(yellow["downstream_observation"], "not_observed")
        self.assertTrue(yellow["alternate_supply_witness"])
        self.assertTrue(any(_ENGINE in cluster["known_shared_paths"]
                            for cluster in investigation["common_cause"]["clusters"]))
        self.assertFalse(any(cluster["unmodelled_common_cause_possible"]
                             for cluster in investigation["common_cause"]["clusters"]))

    def test_earlier_source_failure_remains_supported_after_engine_drive_drops(self):
        for row in self.rows[6:25]:
            row["readings"]["generator_2_voltage"]["value"] = 0
        epoch, = analyze_sequences(self.rows)["epochs"]
        masking = epoch["investigation"]["masking"]
        self.assertEqual(masking["minimal_compatible_explanations"], [f"{_GEN}+{_ENGINE}"])
        local = next(root for candidate in masking["candidate_observability"] for root in candidate["mechanisms"]
                     if root["mechanism"] == _GEN)
        self.assertIn("generator_loss_with_drive_retained", local["exclusive_witness_ids"])
        self.assertEqual(evaluate_counterfactual(epoch, self.model, only=[_ENGINE])["status"], "excluded")
        self.assertNotIn(_GEN, [item["mechanism"] for item in masking["potentially_masked_mechanisms"]])

    def test_blue_supply_fault_remains_possible_with_earlier_inventory_decline(self):
        rows = self.rows[:14]
        for row in rows[5:]:
            row["readings"]["blue_quantity"]["value"] = 7.0
        for row in rows[10:]:
            row["readings"]["blue_pressure"]["value"] = 2300.0
        epoch, = analyze_sequences(rows)["epochs"]
        masking = epoch["investigation"]["masking"]
        self.assertEqual(masking["minimal_compatible_explanations"], [_BLUE_INVENTORY])
        hidden, = masking["potentially_masked_mechanisms"]
        self.assertEqual(hidden["mechanism"], _BLUE_SUPPLY)
        discriminator = masking["blue_supply_discrimination"]
        self.assertEqual(discriminator["inventory_pressure_relation"]["status"], "consistent")
        witness = discriminator["quantity_at_first_observed_pressure_loss"]
        self.assertEqual(witness["indicated_quantity"]["value"], 7.0)
        self.assertEqual(witness["quantity_reference"]["value_raw"], 8.0)
        self.assertIn("no depletion threshold", discriminator["limitation"])

    def test_close_effects_do_not_override_timing_exclusions(self):
        rows = self.rows[:14]
        for row in rows[6:]:
            row["readings"]["generator_2_voltage"]["value"] = 0
        for row in rows[8:]:
            row["readings"]["blue_pressure"]["value"] = 0
        exact = {_GEN: {"generator_source_anomaly": [0, 0]}, _BLUE_SUPPLY: {"blue_pressure_loss": [0, 0]}}
        bounded, = analyze_sequences(rows, response_bounds=exact)["epochs"]
        cluster, = bounded["investigation"]["common_cause"]["clusters"]
        self.assertEqual(cluster["status"], "distinct_mechanism_onsets_required")
        self.assertFalse(cluster["unmodelled_common_cause_possible"])
        self.assertEqual(cluster["physical_initiator"], "unknown")
        unconstrained, = analyze_sequences(rows)["epochs"]
        cluster, = unconstrained["investigation"]["common_cause"]["clusters"]
        self.assertEqual(cluster["status"], "shared_origin_unresolved")
        self.assertTrue(cluster["surviving_sets_retained"])
        self.assertFalse(cluster["distinctive_shared_evidence"])

    def test_inconsistent_bus_loss_keeps_model_residual_instead_of_inventing_a_cause(self):
        rows = self.rows[:14]
        for row in rows[6:]:
            row["readings"]["ac_bus_2"]["value"] = 0
        epoch, = analyze_sequences(rows)["epochs"]
        mismatch = epoch["investigation"]["common_cause"]["model_mismatch"]
        self.assertEqual(mismatch["status"], "no_joint_model_fit")
        self.assertIn("bus_supply_loss", [item["fact"] for item in mismatch["unexplained_observations"]])
        self.assertEqual(epoch["investigation"]["masking"]["minimal_possible_explanations"], [])

    def test_live_replay_and_offline_investigate_the_same_public_prefix(self):
        rows = self.rows[:25]
        replay = ReplayPanelState(rows, model=self.model, pilot=True, investigation=True)
        session = DiagnosisSession(model=self.model, pilot=True, investigation=True)
        for position, row in enumerate(rows):
            payload = session.advance(row)
            if position in (0, len(rows) - 1):
                replay.seek({"position": position})
                current = replay.get_state()["diagnosis"]
                self.assertEqual(current["investigation"], payload["investigation"])
                self.assertEqual(current["pilot_display"], payload["pilot_display"])
        offline, = analyze_sequences(rows)["epochs"]
        self.assertEqual(payload["investigation"], offline["investigation"])
        self.assertIn("WHAT TO INVESTIGATE NEXT", payload["pilot_display"])
        self.assertIn("Model-check support", payload["pilot_display"])

    def test_available_pending_measurement_ranks_a_real_prefix_and_new_poll_fits_its_partition(self):
        path = _ARCHIVE.parent.parent / "pair-auto/observations.jsonl"
        rows = list(iter_profile_observations(path))[20:22]
        epoch, = analyze_sequences(rows[:1])["epochs"]
        selection = epoch["investigation"]["evidence_selection"]
        self.assertEqual(selection["status"], "passive_discriminator_available")
        top = selection["recommended_measurements"][0]
        self.assertEqual(top["fact"], "blue_inventory_loss")
        self.assertEqual(top["minimum_eliminated_if_conclusive"], 12)
        self.assertTrue(top["passive"])
        ranks = [(item["worst_case_remaining"], item["best_case_remaining"], item["fact"])
                 for item in selection["recommended_measurements"]]
        self.assertEqual(ranks, sorted(ranks))
        # Hold the other unresolved measurements unavailable in the next poll.
        unknown_channels = {channel for name, fact in epoch["facts"].items()
                            if fact["state"] == "unknown" and name != top["fact"]
                            for channel in self.model["facts"][name]["channels"]}
        for channel in unknown_channels:
            rows[1]["readings"].pop(channel, None)
        rows[1]["complete"] = False
        updated, = analyze_sequences(rows)["epochs"]
        fits = {item["id"] for item in updated["mechanism_sets"]
                if item["history_counts"]["compatible"] or item["history_counts"]["unconfirmed"]}
        self.assertTrue(fits)
        self.assertLessEqual(fits, set(top["predicted_partitions"]["not_observed"]))
        self.assertEqual(selection["candidate_count"] - len(fits), 12)
