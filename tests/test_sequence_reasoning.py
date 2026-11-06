"""Check every ordered partition and replay selected native contrasts."""

from itertools import product
from math import inf
from pathlib import Path
import unittest
from unittest.mock import patch

from aircraft_debugger.airborne_profile import iter_profile_observations
from aircraft_debugger.hypotheses import generated_model
from aircraft_debugger.sequence_reasoning import (
    _catalogue_orders, _fit_epoch, _response_bounds, _timing_conflict, analyze_sequences,
)


RESULTS = Path(__file__).resolve().parents[1] / "results"
GEN = "generator_2_source_path_fault"
LEAK = "blue_fluid_loss_mechanism"
BLUE_PUMP = "blue_pressure_supply_loss"
ENGINE = "engine_2_power_loss"
YELLOW = "yellow_engine_driven_pump_supply_loss"
MECHANISMS = (GEN, LEAK, BLUE_PUMP, ENGINE, YELLOW)
PAIR_BOUNDS = {GEN: {"generator_source_anomaly": [0, 3]}, BLUE_PUMP: {"blue_pressure_loss": [0, 10]}}


def recording(folder):
    return list(iter_profile_observations(RESULTS / folder / "observations.jsonl"))


def pair_orders(epoch):
    return {item["onset_groups"] for item in epoch["histories"]
            if item["mechanism_set"] == f"{GEN}+{BLUE_PUMP}" and item["status"] == "unconfirmed"}


def synthetic_frame(onsets, *, delayed, backup, depletes):
    """An independent fixture plant with sustained threshold steps and masking."""
    gen, leak, pump, engine, yellow = (onsets.get(root, inf) for root in MECHANISMS)
    drive_lag = 3 if delayed else 1
    generator_loss = min(gen + 1, engine + drive_lag)
    edp_loss = min(yellow + 1, engine + drive_lag)
    effects = {
        "generator_source_anomaly": generator_loss,
        "blue_inventory_loss": leak + 2,
        "bus_supply_loss": inf if backup else generator_loss + 2,
        "blue_pressure_loss": min(pump + 1, leak + 6 if depletes else inf),
        "engine_2_fuel_flow_loss": engine + 1,
        "engine_2_core_speed_loss": engine + drive_lag,
        "yellow_edp_output_loss": edp_loss,
        "yellow_line_pressure_loss": inf if backup else edp_loss + 4,
    }
    facts = {}
    for effect, time in effects.items():
        interval = None if time == inf else {
            "lower_sim_time_s": time - 0.25, "upper_sim_time_s": time + 0.25,
            "covered_through_confirmation": True,
        }
        facts[effect] = {"state": "observed" if interval else "not_observed", "onset_interval": interval}
    relations = {}
    if effects["blue_pressure_loss"] + 1 < effects["blue_inventory_loss"] < inf:
        relations["inventory_before_pressure"] = {"status": "contradicted"}
    for name, channel, loss in (
        ("generator_loss_with_drive_retained", "generator_2_voltage", generator_loss),
        ("yellow_pump_loss_with_drive_retained", "yellow_edp_pressure", edp_loss),
    ):
        if loss + 1 < engine + 1:
            relations[name] = {"status": "contradicted",
                               "evidence": [{"channel": channel, "sim_time_s": loss + 0.25}]}
    bounds = {
        GEN: {"generator_source_anomaly": [1, 1]},
        LEAK: {"blue_inventory_loss": [2, 2]},
        BLUE_PUMP: {"blue_pressure_loss": [1, 1]},
        ENGINE: {"engine_2_fuel_flow_loss": [1, 1], "engine_2_core_speed_loss": [drive_lag, drive_lag],
                 "generator_source_anomaly": [drive_lag, drive_lag], "yellow_edp_output_loss": [drive_lag, drive_lag]},
        YELLOW: {"yellow_edp_output_loss": [1, 1]},
    }
    return {"facts": facts, "temporal_relations": relations}, bounds


class SequenceReasoningTests(unittest.TestCase):
    def test_every_independent_fixture_history_survives_the_same_inference(self):
        model = generated_model()
        catalogue = _catalogue_orders(model)
        total = unique = 0
        # Independent enumeration by assigning an onset rank or absence to each
        # mechanism. The fixture observations contain neither ranks nor roots.
        for ranks in product(range(-1, 5), repeat=5):
            group_count = max(ranks) + 1
            if set(ranks) - {-1} != set(range(group_count)):
                continue
            groups = tuple(tuple(root for root, rank in zip(MECHANISMS, ranks) if rank == group)
                           for group in range(group_count))
            spacing = 2 if total % 2 else 7
            onsets = {root: 10 + spacing * rank for root, rank in zip(MECHANISMS, ranks) if rank >= 0}
            frame, bounds = synthetic_frame(onsets, delayed=total % 2, backup=total % 3, depletes=total % 5)
            result = _fit_epoch(frame, model, bounds, catalogue)
            actual = next(item for item in result["histories"] if item["onset_groups"] == groups)
            self.assertEqual(actual["status"], "compatible", (groups, actual))
            total += 1
            unique += result["unique_history_within_model"] is not None
        self.assertEqual(total, 1082)
        self.assertGreater(unique, 1)
        self.assertLess(unique, total)
        self.assertEqual(sum(len(roots) > 1 for roots in catalogue), 26)

    def test_order_uses_inclusive_measurement_bounds_and_strict_group_order(self):
        constraints = {
            "onset_floors": [
                {"root": GEN, "earliest_onset_sim_s": 9},
                {"root": BLUE_PUMP, "earliest_onset_sim_s": 10},
            ],
            "deadlines": [
                {"evidence_id": "generator_source_anomaly", "latest_onset_sim_s": {GEN: 10}},
                {"evidence_id": "blue_pressure_loss", "latest_onset_sim_s": {BLUE_PUMP: 11}},
            ],
            "missing_witness_paths": [],
        }
        self.assertIsNone(_timing_conflict(((GEN, BLUE_PUMP),), constraints))
        self.assertIsNone(_timing_conflict(((GEN,), (BLUE_PUMP,)), constraints))
        conflict = _timing_conflict(((BLUE_PUMP,), (GEN,)), constraints)
        self.assertEqual(conflict["missed_deadline_for"], "generator_source_anomaly")
        self.assertTrue(conflict["conflicting_paths"][0]["strictly_after"])

    def test_engine_cascade_keeps_masked_histories_and_isolated_yellow_is_unique(self):
        engine_rows = recording("engine-drive-20261106-01/engine-auto")
        yellow_rows = recording("yellow-edp-isolated-20261106-01/run")
        with (
            patch("builtins.open", side_effect=AssertionError("Inference read a file")),
            patch("pathlib.Path.open", side_effect=AssertionError("Inference read a path")),
            patch("socket.create_connection", side_effect=AssertionError("Inference connected to a socket")),
        ):
            engine = analyze_sequences(engine_rows)["epochs"][0]
            yellow = analyze_sequences(yellow_rows)["epochs"][0]
        self.assertEqual(engine["minimal_possible_mechanism_sets"], [ENGINE])
        self.assertEqual(engine["history_counts"]["compatible"], 20)
        self.assertIsNone(engine["unique_history_within_model"])
        self.assertEqual(yellow["unique_history_within_model"]["onset_groups"], ((YELLOW,),))

    def test_clock_reset_keeps_histories_from_different_flights_separate(self):
        engine_rows = recording("engine-drive-20261106-01/engine-auto")
        yellow_rows = recording("yellow-edp-isolated-20261106-01/run")
        first_yellow = yellow_rows[0]
        receipt_shift = engine_rows[-1]["received_monotonic_s"] + 1 - first_yellow["poll_started_monotonic_s"]
        clock_shift = first_yellow["readings"]["sim_time"]["value"] - 1
        for index, row in enumerate(yellow_rows, len(engine_rows)):
            row["sample_index"] = index
            row["poll_started_monotonic_s"] += receipt_shift
            row["received_monotonic_s"] += receipt_shift
            row["readings"]["sim_time"]["value"] -= clock_shift
            for reading in row["readings"].values():
                reading["received_monotonic_s"] += receipt_shift
                if reading["sim_time_s"] is not None:
                    reading["sim_time_s"] -= clock_shift
        epochs = analyze_sequences(engine_rows + yellow_rows)["epochs"]
        self.assertEqual([item["epoch"] for item in epochs], [0, 1])
        self.assertEqual([item["minimal_possible_mechanism_sets"] for item in epochs], [[ENGINE], [YELLOW]])

    def test_native_pair_timing_depends_on_bounds_and_preserves_unknown_propulsion(self):
        rows = recording("timed-pair-20261106-01")
        bounded = analyze_sequences(rows, response_bounds=PAIR_BOUNDS)["epochs"][0]
        wide = {**PAIR_BOUNDS, BLUE_PUMP: {"blue_pressure_loss": [0, 30]}}
        wide_result = analyze_sequences(rows, response_bounds=wide)["epochs"][0]
        near = analyze_sequences(recording("pressure-pair-20261106-01/pair"),
                                 response_bounds=PAIR_BOUNDS)["epochs"][0]
        recovery = analyze_sequences(recording("timed-separated-20261106-01"),
                                     response_bounds=PAIR_BOUNDS)["epochs"][0]
        self.assertEqual(pair_orders(bounded), {((GEN,), (BLUE_PUMP,))})
        self.assertEqual(pair_orders(recovery), pair_orders(bounded))
        self.assertEqual(len(pair_orders(near)), 3)
        self.assertEqual(len(pair_orders(wide_result)), 3)
        self.assertEqual(bounded["facts"]["engine_2_core_speed_loss"]["state"], "unknown")

    def test_skipped_polls_degrade_timing_coverage_without_erasing_positive_effects(self):
        rows = recording("timed-pair-20261106-01")
        result = analyze_sequences(rows[:8] + rows[9:], response_bounds=PAIR_BOUNDS)["epochs"][0]
        pressure = result["facts"]["blue_pressure_loss"]
        self.assertEqual(pressure["state"], "observed")
        self.assertFalse(pressure["onset_interval"]["covered_through_confirmation"])
        self.assertEqual(len(pair_orders(result)), 3)

    def test_unknown_or_unphysical_response_bounds_are_rejected(self):
        model = generated_model()
        for bounds in (
            {LEAK: {"blue_pressure_loss": [0, 3]}}, {GEN: {"generator_source_anomaly": [-1, 3]}},
            {GEN: {"generator_source_anomaly": [0, inf]}}, {"missing": {"generator_source_anomaly": [0, 1]}},
        ):
            with self.subTest(bounds=bounds), self.assertRaises(ValueError):
                _response_bounds(bounds, model)
