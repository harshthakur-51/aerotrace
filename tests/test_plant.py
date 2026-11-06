from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from aircraft_debugger.experiment import run_experiment
from aircraft_debugger.plant import Observation, Parameters, Scenario, simulate


class PlantTests(unittest.TestCase):
    def setUp(self):
        self.p = Parameters(
            duration_s=40, fault_time_s=10,
            pressure_noise_sd_bar=0, reservoir_noise_sd_l=0, position_noise_sd_deg=0,
        )

    def test_sensor_bias_does_not_change_physical_state(self):
        healthy = list(simulate(Scenario.HEALTHY, self.p))
        biased = list(simulate(Scenario.SENSOR_BIAS, self.p))
        for (normal_obs, normal_truth), (biased_obs, biased_truth) in zip(healthy, biased):
            self.assertEqual(normal_truth.pressure_bar, biased_truth.pressure_bar)
            self.assertEqual(normal_truth.reservoir_l, biased_truth.reservoir_l)
            self.assertEqual(normal_truth.actuator_position_deg, biased_truth.actuator_position_deg)
            expected_bias = self.p.sensor_bias_bar if normal_obs.t_s >= self.p.fault_time_s else 0
            self.assertAlmostEqual(biased_obs.hyd_b_pressure_bar - normal_obs.hyd_b_pressure_bar, expected_bias)

    def test_leak_obeys_external_fluid_balance_and_causal_onset(self):
        pairs = list(simulate(Scenario.LEAK, self.p))
        for (_, previous), (_, current) in zip(pairs, pairs[1:]):
            self.assertAlmostEqual(current.reservoir_l, previous.reservoir_l - previous.external_leak_l_s * self.p.dt_s)
        for obs, truth in pairs:
            if obs.t_s < self.p.fault_time_s:
                self.assertEqual(truth.external_leak_l_s, 0)
                self.assertEqual(truth.reservoir_l, self.p.initial_reservoir_l)
        self.assertLess(pairs[-1][1].pressure_bar, self.p.nominal_pressure_bar)
        self.assertLess(pairs[-1][1].reservoir_l, self.p.initial_reservoir_l)

    def test_empty_reservoir_stays_nonnegative(self):
        p = replace(self.p, duration_s=120, initial_reservoir_l=0.1)
        for _, truth in simulate(Scenario.LEAK, p):
            self.assertGreaterEqual(truth.reservoir_l, 0)
            self.assertGreaterEqual(truth.pressure_bar, 0)
            self.assertLessEqual(truth.pressure_bar, p.nominal_pressure_bar)

    def test_identical_seed_reproduces_measurements(self):
        self.assertEqual(list(simulate(Scenario.LEAK, seed=13)), list(simulate(Scenario.LEAK, seed=13)))
        a = next(simulate(Scenario.HEALTHY, seed=13))[0]
        b = next(simulate(Scenario.HEALTHY, seed=14))[0]
        self.assertNotEqual(a, b)

    def test_observation_contract_contains_no_fault_or_private_state(self):
        allowed = {
            "schema_version", "sequence", "t_s", "hyd_b_pressure_bar", "hyd_b_reservoir_l",
            "actuator_command_deg", "actuator_position_deg", "quality",
        }
        self.assertEqual(set(Observation.__dataclass_fields__), allowed)
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "experiment"
            run_experiment(output)
            header = (output / "run002" / "telemetry.csv").read_text().splitlines()[0]
            self.assertEqual(set(header.split(",")), allowed)
            self.assertTrue((output / "run002" / "private_truth" / "states.jsonl").exists())
            with self.assertRaises(FileExistsError):
                run_experiment(output)

    def test_halving_time_step_preserves_hydraulic_solution(self):
        coarse = list(simulate(Scenario.LEAK, self.p))[-1][1]
        fine = list(simulate(Scenario.LEAK, replace(self.p, dt_s=0.025)))[-1][1]
        self.assertLess(abs(coarse.pressure_bar - fine.pressure_bar), 0.05)
        self.assertLess(abs(coarse.reservoir_l - fine.reservoir_l), 0.005)

    def test_invalid_parameters_fail_early(self):
        for change in (
            {"dt_s": 0}, {"dt_s": 0.1}, {"pressure_noise_sd_bar": -1},
            {"sensor_bias_bar": float("nan")}, {"actuator_amplitude_deg": -1},
            {"actuator_frequency_hz": -1},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(self.p, **change)

    def test_stationary_actuator_cannot_corroborate_a_pressure_fault(self):
        p = replace(self.p, actuator_amplitude_deg=0)
        leak = list(simulate(Scenario.LEAK, p))
        bias = list(simulate(Scenario.SENSOR_BIAS, p))
        self.assertTrue(all(obs.actuator_command_deg == 0 for obs, _ in leak + bias))
        self.assertTrue(all(obs.actuator_position_deg == 0 for obs, _ in leak + bias))
        self.assertLess(leak[-1][0].hyd_b_reservoir_l, bias[-1][0].hyd_b_reservoir_l)

    def test_custom_experiment_uses_parameters_and_preserves_truth_boundary(self):
        p = replace(self.p, leak_coefficient_l_s=0.005, actuator_amplitude_deg=0)
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "configured"
            summary = run_experiment(output, parameters=p)
            self.assertEqual(summary["parameters"]["leak_coefficient_l_s"], 0.005)
            self.assertEqual(summary["runs"][1]["tracking_error_rms_after_settling_deg"], 0)
            self.assertEqual(summary["runs"][0]["sample_count"], round(p.duration_s / p.dt_s) + 1)
            self.assertNotIn(b"\r\n", (output / "summary.json").read_bytes())
            self.assertNotIn(b"\r\n", (output / "run002" / "private_truth" / "manifest.json").read_bytes())

    def test_too_short_summary_window_fails_before_writing_output(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "too-short"
            with self.assertRaises(ValueError):
                run_experiment(output, parameters=replace(self.p, duration_s=15))
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
