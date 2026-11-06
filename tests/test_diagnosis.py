"""Causal replay counterexamples and public-input boundary regressions.

Synthetic rows are protocol/diagnosis fixtures, not additional aircraft trials.
The saved native cases are development evidence rather than an accuracy dataset.
"""

import builtins
import copy
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from aircraft_debugger.airborne_profile import AIRBORNE_CHANNELS, PROFILE_ID, iter_profile_observations
from aircraft_debugger.diagnosis import analyze_diagnosis, main
from aircraft_debugger.hypotheses import default_model
from aircraft_debugger.observations import CHANNELS


PAIR = {"independent_pair", "grouped_joint_event"}
ROOT = Path(__file__).resolve().parents[1]


def sample(index, *, generator=115.0, quantity=8.0, pressure=3000.0,
           bus=115.0, sim_time=None, missing=(), paused=False):
    simulator = 100.0 + index if sim_time is None else sim_time
    local = 1000.0 + index
    values = {
        "aircraft": "A320-200-CFM", "sim_time": simulator, "paused": paused,
        "altitude": 10000.0, "airspeed": 250.0, "engine_1_n1": 80.0,
        "engine_2_n1": 80.0, "generator_2_voltage": generator,
        "ac_bus_1": 115.0, "ac_bus_2": bus, "blue_quantity": quantity,
        "blue_pressure": pressure, "main_gear_1_wow": False,
        "main_gear_2_wow": False, "height_agl": 7000.0,
        "vertical_speed": 0.0, "bank": 0.0, "autopilot_1": True,
        "autopilot_2": False, "autothrust": True,
    }
    readings = {
        name: {"path": spec.path, "value": values[name], "valid": True,
               "error": None, "sim_time_s": simulator,
               "received_monotonic_s": local + .1, "reachable": True,
               "unit": spec.unit}
        for name, spec in AIRBORNE_CHANNELS.items() if name not in missing
    }
    return {
        "schema_version": 2, "observation_profile": PROFILE_ID,
        "sample_index": index, "poll_started_monotonic_s": local,
        "received_monotonic_s": local + .2, "readings": readings,
        "connected": True, "complete": not missing,
    }


def trace(kind="pair", *, recovered=False):
    electrical = kind in {"generator", "pair"}
    hydraulic = kind in {"blue", "pair"}
    rows = [sample(0), sample(1)]
    rows.extend([
        sample(2, generator=0 if electrical else 115,
               quantity=7.75 if hydraulic else 8),
        sample(3, generator=0 if electrical else 115,
               quantity=7.2 if hydraulic else 8),
        sample(4, generator=0 if electrical else 115,
               quantity=6.9 if hydraulic else 8,
               pressure=1000 if hydraulic else 3000),
    ])
    if recovered:
        rows.extend([sample(5, pressure=1200 if hydraulic else 3000),
                     sample(6, pressure=2300 if hydraulic else 3000),
                     sample(7), sample(8)])
    return rows


def candidates(report):
    return {item["id"]: item for item in report["diagnosis"]["candidates"]}


class DiagnosisTests(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get("AIRCRAFT_DEBUGGER_TEST_TMP", "work/tests"))
        base.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def test_reference_excludes_selected_fault_configurations(self):
        report = analyze_diagnosis([sample(0), sample(1), sample(2)])
        self.assertEqual(report["diagnosis"]["status"], "no_selected_anomaly")
        self.assertEqual(report["diagnosis"]["candidate_ids"], ["selected_reference"])
        self.assertFalse(report["diagnosis"]["cause_identifiable"])
        self.assertEqual(report["current_impact"], [])

    def test_source_loss_does_not_manufacture_bus_loss(self):
        report = analyze_diagnosis(trace("generator"))
        self.assertEqual(report["diagnosis"]["candidate_ids"], ["generator_2_source_path_fault"])
        self.assertEqual(report["diagnosis"]["status"], "single_compatible_candidate")
        self.assertFalse(report["diagnosis"]["cause_identifiable"])
        self.assertEqual(report["current_state"]["ac_bus_2"]["status"], "supply_retained")
        self.assertTrue(all(item["observation"] != "AC bus 2 voltage is unavailable."
                            for item in report["current_impact"]))
        inspector = candidates(report)["generator_2_source_path_fault"]
        self.assertTrue(inspector["supporting_evidence"])
        self.assertTrue(inspector["dependency_paths"])
        self.assertEqual(inspector["contradicting_evidence"], [])

    def test_changed_dependency_prediction_changes_fit_without_changing_observations(self):
        rows = trace("generator")
        original_rows = copy.deepcopy(rows)
        model = default_model()
        changed = copy.deepcopy(model)
        edge = next(item for item in changed["edges"]
                    if item["from"] == "generator_source_anomaly" and item["to"] == "bus_supply_loss")
        edge["necessity"] = "required"
        ordinary = analyze_diagnosis(rows, model=model)
        counterfactual = analyze_diagnosis(rows, model=changed)
        self.assertEqual(ordinary["diagnosis"]["candidate_ids"], ["generator_2_source_path_fault"])
        self.assertEqual(counterfactual["diagnosis"]["status"], "poor_model_fit")
        self.assertEqual(counterfactual["diagnosis"]["candidate_ids"], [])
        self.assertEqual(ordinary["evidence"], counterfactual["evidence"])
        self.assertEqual(rows, original_rows)
        self.assertEqual(model, default_model())

    def test_inventory_loss_is_explained_while_pressure_is_retained(self):
        report = analyze_diagnosis(trace("blue")[:4])
        self.assertEqual(report["diagnosis"]["candidate_ids"], ["blue_inventory_loss"])
        self.assertEqual(report["current_state"]["blue_pressure"]["status"], "pressure_retained")
        self.assertTrue(candidates(report)["blue_inventory_loss"]["supporting_evidence"])
        self.assertEqual(candidates(report)["blue_inventory_loss"]["contradicting_evidence"], [])

    def test_joint_effects_exclude_single_roots_and_keep_two_inspectable_alternatives(self):
        report = analyze_diagnosis(trace())
        diagnosis = report["diagnosis"]
        self.assertEqual(diagnosis["status"], "causal_ambiguity")
        self.assertEqual(set(diagnosis["candidate_ids"]), PAIR)
        self.assertFalse(diagnosis["cause_identifiable"])
        panels = candidates(report)
        self.assertEqual(panels["generator_2_source_path_fault"]["status"], "contradicted")
        self.assertEqual(panels["blue_inventory_loss"]["status"], "contradicted")
        for name in PAIR:
            item = panels[name]
            self.assertEqual(item["status"], "compatible")
            self.assertTrue(item["supporting_evidence"])
            self.assertTrue(item["dependency_paths"])
            self.assertEqual(item["contradicting_evidence"], [])
            self.assertIn(next(iter(PAIR - {name})), item["alternative_candidate_ids"])
            for field in ("predicted_consequences", "missing_evidence"):
                self.assertIn(field, item)

    def test_recovered_native_pairs_preserve_incident_cause_sets_and_history(self):
        base = ROOT / "results" / "airborne-pairs-20261029-01"
        for folder, count in (("grouped-recipe", 80), ("matched-independent-recipe", 81)):
            with self.subTest(recording=folder):
                rows = list(iter_profile_observations(base / folder / "observations.jsonl"))
                report = analyze_diagnosis(rows)
                self.assertEqual(report["sample_count"], count)
                self.assertEqual(set(report["diagnosis"]["candidate_ids"]), PAIR)
                self.assertEqual(report["diagnosis"]["status"], "causal_ambiguity")
                self.assertEqual(report["current_state"]["generator_2"]["status"], "energized_output_observed")
                self.assertEqual(report["current_state"]["blue_inventory"]["status"], "near_observed_reference")
                self.assertEqual(report["current_state"]["blue_pressure"]["status"], "pressure_retained")
                self.assertEqual(report["current_impact"], [])
                self.assertTrue(report["observed_impact"])
                self.assertEqual(len(report["timeline"]), count)
                self.assertTrue(any(row["current_impact"] for row in report["timeline"]))

    def test_refill_pressure_lag_remains_known_impact_of_the_same_incident(self):
        report = analyze_diagnosis(trace("blue", recovered=True)[:6])
        self.assertEqual(report["diagnosis"]["candidate_ids"], ["blue_inventory_loss"])
        self.assertEqual(report["current_state"]["blue_inventory"]["status"], "near_observed_reference")
        self.assertEqual(report["current_state"]["blue_pressure"]["status"], "pressure_degraded")
        self.assertTrue(any(item["system"] == "hydraulic" for item in report["current_impact"]))

    def test_complete_unmodelled_pressure_or_bus_anomaly_is_poor_fit_not_missing_data(self):
        for fields in ({"pressure": 1000}, {"bus": 0}):
            with self.subTest(fields=fields):
                report = analyze_diagnosis([sample(0), sample(1), sample(2, **fields), sample(3, **fields)])
                self.assertEqual(report["diagnosis"]["status"], "poor_model_fit")
                self.assertEqual(report["diagnosis"]["candidate_ids"], [])
                self.assertTrue(report["current_impact"])
                self.assertTrue(all(item["status"] == "contradicted" for item in candidates(report).values()))

    def test_missing_discriminators_keep_plausibility_distinct_from_compatibility(self):
        cases = [
            ([sample(0), sample(1), sample(2, quantity=7.75, missing=("generator_2_voltage",)),
              sample(3, quantity=7.2, missing=("generator_2_voltage",))], "hydraulic"),
            ([sample(0), sample(1), sample(2, generator=0, missing=("blue_quantity",)),
              sample(3, generator=0, missing=("blue_quantity",))], "electrical"),
        ]
        for rows, system in cases:
            with self.subTest(system=system):
                report = analyze_diagnosis(rows)
                self.assertEqual(report["diagnosis"]["status"], "insufficient_observations")
                self.assertTrue(report["diagnosis"]["plausible_candidate_ids"])
                self.assertTrue(any(item["status"] == "unconfirmed" and item["missing_evidence"]
                                    for item in candidates(report).values()))
                self.assertTrue(any(item["system"] == system for item in report["current_impact"]))
                self.assertFalse(report["diagnosis"]["cause_identifiable"])

    def test_clock_reset_does_not_join_faults_from_different_epochs(self):
        rows = trace("generator")[:4] + [
            sample(4, sim_time=0), sample(5, sim_time=1), sample(6, sim_time=2),
            sample(7, sim_time=3, quantity=7.75), sample(8, sim_time=4, quantity=7.2),
        ]
        report = analyze_diagnosis(rows)
        self.assertEqual(report["timeline"][-1]["epoch"], 1)
        self.assertEqual(report["diagnosis"]["candidate_ids"], ["blue_inventory_loss"])
        self.assertFalse(PAIR.intersection(report["diagnosis"]["candidate_ids"]))

    def test_closed_old_inventory_incident_cannot_explain_a_new_pressure_only_event(self):
        rows = trace("blue")[:4] + [sample(4), sample(5),
            sample(6, pressure=1000), sample(7, pressure=500)]
        report = analyze_diagnosis(rows)
        self.assertEqual(report["diagnosis"]["status"], "poor_model_fit")
        self.assertEqual(report["diagnosis"]["candidate_ids"], [])
        self.assertEqual(candidates(report)["blue_inventory_loss"]["status"], "contradicted")

    def test_temporal_ablation_changes_only_order_constraints_not_data_or_catalogue(self):
        rows = [sample(0), sample(1), sample(2, pressure=1000),
                sample(3, pressure=1000), sample(4, pressure=1000, quantity=7.75),
                sample(5, pressure=500, quantity=7.2)]
        atemporal = analyze_diagnosis(rows, temporal=False)
        temporal = analyze_diagnosis(rows, temporal=True)
        self.assertEqual(atemporal["evidence"], temporal["evidence"])
        self.assertEqual(set(candidates(atemporal)), set(candidates(temporal)))
        self.assertEqual(atemporal["diagnosis"]["candidate_ids"], ["blue_inventory_loss"])
        self.assertEqual(temporal["diagnosis"]["status"], "poor_model_fit")
        self.assertEqual(temporal["diagnosis"]["candidate_ids"], [])
        self.assertTrue(candidates(temporal)["blue_inventory_loss"]["contradicting_evidence"])

    def test_unavailable_current_readings_do_not_erase_incident_impact_or_become_healthy(self):
        report = analyze_diagnosis(trace() + [sample(5, paused=True)])
        self.assertEqual(report["current_state"]["generator_2"]["status"], "insufficient_evidence")
        self.assertEqual(report["current_state"]["blue_pressure"]["status"], "insufficient_evidence")
        self.assertTrue(report["observed_impact"])
        self.assertNotEqual(report["diagnosis"]["status"], "no_selected_anomaly")

    def test_pure_inference_needs_no_external_access_and_does_not_mutate_input(self):
        rows = trace(recovered=True)
        original = copy.deepcopy(rows)
        deny = AssertionError("Inference attempted external access")
        with ExitStack() as stack:
            for target in ("builtins.open", "io.open", "socket.create_connection",
                           "http.client.HTTPConnection.request", "subprocess.Popen"):
                stack.enter_context(patch(target, side_effect=deny))
            stack.enter_context(patch.object(Path, "open", side_effect=deny))
            stack.enter_context(patch.object(socket.socket, "connect", side_effect=deny))
            report = analyze_diagnosis(iter(rows))
        self.assertEqual(rows, original)
        self.assertEqual(set(report["diagnosis"]["candidate_ids"]), PAIR)
        self.assertFalse(report["diagnosis"]["cause_identifiable"])

    def test_private_fields_are_rejected_instead_of_becoming_explanatory_evidence(self):
        for location in ("top", "reading"):
            rows = trace()
            if location == "top":
                rows[-1]["initiating_cause"] = "shared event"
            else:
                rows[-1]["readings"]["blue_leak_fault"] = copy.deepcopy(rows[-1]["readings"]["paused"])
            with self.subTest(location=location), self.assertRaises(ValueError):
                analyze_diagnosis(rows)

    def test_schema_1_dispatch_does_not_silently_change_the_legacy_contract(self):
        rows = trace("generator")
        for row in rows:
            row.pop("observation_profile")
            row["schema_version"] = 1
            row["readings"] = {name: item for name, item in row["readings"].items() if name in CHANNELS}
        report = analyze_diagnosis(rows)
        self.assertEqual(report["observation_schema_version"], 1)
        self.assertEqual(report["diagnosis"]["candidate_ids"], ["generator_2_source_path_fault"])

    def _input_file(self):
        path = self.directory / "observations.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in trace(recovered=True)), encoding="utf-8")
        return path

    def test_cli_reads_explicit_public_input_and_writes_reproducible_inspection_artifacts(self):
        source = self._input_file()
        canary = self.directory / "manifest.json"
        canary.write_text("not diagnostic input", encoding="utf-8")
        private = self.directory / "private_truth"
        private.mkdir()
        (private / "actions.jsonl").write_text("not diagnostic input", encoding="utf-8")
        output = self.directory / "report"
        original_open = Path.open

        def guarded_open(path, mode="r", *args, **kwargs):
            if "r" in mode:
                resolved = path.resolve()
                permitted = (resolved == source.resolve()
                             or resolved.is_relative_to((ROOT / "aircraft_debugger").resolve())
                             or resolved.is_relative_to(output.resolve()))
                self.assertTrue(permitted, f"Unexpected input read: {path}")
            return original_open(path, mode, *args, **kwargs)

        with patch.object(Path, "open", new=guarded_open), patch.object(sys, "argv", [
                "diagnosis", "--observations", str(source), "--output", str(output), "--mode", "temporal"]):
            with redirect_stdout(io.StringIO()):
                main()
        report = json.loads((output / "report.json").read_text(encoding="utf-8"))
        provenance = json.loads((output / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(set(report["diagnosis"]["candidate_ids"]), PAIR)
        self.assertEqual(report["input_provenance"]["observation_file_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        for name in ("report.json", "report.md", "timeline.json", "provenance.json"):
            self.assertTrue((output / name).is_file())
            self.assertNotIn(b"\r\n", (output / name).read_bytes())
        for name, digest in provenance["artifact_sha256"].items():
            self.assertEqual(hashlib.sha256((output / name).read_bytes()).hexdigest(), digest)
        for name, digest in provenance["source_sha256"].items():
            archived = output / provenance["executed_source_archives"][name]
            self.assertEqual(hashlib.sha256(archived.read_bytes()).hexdigest(), digest)

    def test_cli_refuses_existing_output_before_opening_the_input(self):
        output = self.directory / "already"
        output.mkdir()
        marker = output / "keep.txt"
        marker.write_text("preserved", encoding="utf-8")
        with patch.object(Path, "open", side_effect=AssertionError("Existing output must fail before reads")), patch.object(sys, "argv", [
                "diagnosis", "--observations", str(self.directory / "absent.jsonl"), "--output", str(output)]):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main()
        self.assertEqual(marker.read_text(encoding="utf-8"), "preserved")

    def test_cli_rejects_input_changed_during_replay_before_creating_output(self):
        source = self._input_file()
        output = self.directory / "report"
        original_read_bytes = Path.read_bytes
        count = 0

        def changing_read(path):
            nonlocal count
            payload = original_read_bytes(path)
            if path.resolve() == source.resolve():
                count += 1
                if count > 1:
                    return payload + b" "
            return payload

        with patch.object(Path, "read_bytes", new=changing_read), patch.object(sys, "argv", [
                "diagnosis", "--observations", str(source), "--output", str(output)]):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main()
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
