from copy import deepcopy
from pathlib import Path
import unittest

from aircraft_debugger.airborne_profile import PILOT_CHANNELS, iter_profile_observations
from aircraft_debugger.diagnostic_session import DiagnosisSession
from aircraft_debugger.hypotheses import generated_model
from aircraft_debugger.pilot_display import GroundPowerClock, render_pilot_display
from aircraft_debugger.replay_panel import ReplayPanelState
from aircraft_debugger.sequence_reasoning import analyze_sequences


_ARCHIVE = (Path(__file__).resolve().parents[1] / "results"
            / "engine-drive-20261106-01/engine-auto/observations.jsonl")


def _power_reading(value, stamp, receipt):
    return {"value": value, "valid": True, "reachable": True, "error": None,
            "path": PILOT_CHANNELS["external_power_output"].path, "unit": "V",
            "sim_time_s": stamp, "received_monotonic_s": receipt}


def _with_startup(rows):
    airborne = deepcopy(rows)
    for row in airborne:
        row["sample_index"] += 2
        clock = row["readings"]["sim_time"]["value"]
        row["readings"]["external_power_output"] = _power_reading(0, clock, row["received_monotonic_s"])
    ground = []
    for index, voltage in enumerate((0, 115)):
        row = deepcopy(rows[0])
        stamp = 10 + index
        start = rows[0]["poll_started_monotonic_s"] - 2 + index
        row.update(sample_index=index, poll_started_monotonic_s=start, received_monotonic_s=start + 0.1)
        for reading in row["readings"].values():
            reading.update(sim_time_s=stamp, received_monotonic_s=start + 0.05)
        for name, value in {"sim_time": stamp, "main_gear_1_wow": True, "main_gear_2_wow": True,
                            "height_agl": 0, "ac_bus_1": voltage, "ac_bus_2": voltage,
                            "blue_pressure": 0, "generator_2_voltage": 0}.items():
            row["readings"][name]["value"] = value
        row["readings"]["external_power_output"] = _power_reading(voltage, stamp, start + 0.05)
        ground.append(row)
    return ground + airborne


class PilotDisplayTests(unittest.TestCase):
    def setUp(self):
        self.rows = list(iter_profile_observations(_ARCHIVE))

    def test_pilot_views_share_the_observed_origin_and_airborne_evidence(self):
        rows = _with_startup(self.rows)
        epoch, = analyze_sequences(rows)["epochs"]
        self.assertEqual(epoch["power_on_sim_s"], 11)
        self.assertEqual(epoch["first_sample_index"], 2)
        display = render_pilot_display(epoch)
        self.assertRegex(display, r"ELEC EXT PWR SUPPLY ON +00:00:00")
        self.assertIn("00:04:15", display)
        self.assertIn("ENG 2 POWER LOSS", display)
        self.assertNotIn("HYD B SYS LO PR", display)
        self.assertIn("20:0", display)

        model = generated_model()
        replay = ReplayPanelState(rows, model=model, pilot=True)
        self.assertIn("Awaiting airborne", replay.get_state()["diagnosis"]["pilot_display"])
        replay.seek({"position": len(rows) - 1})
        self.assertEqual(replay.get_state()["diagnosis"]["pilot_display"], display)
        live = DiagnosisSession(model=model, pilot=True)
        for row in rows:
            live_view = live.advance(row)["pilot_display"]
        self.assertEqual(live_view, display)

    def test_unknown_ground_power_and_competing_scores_are_explicit(self):
        for row in self.rows:
            row["readings"].pop("engine_2_n2")
            row["readings"].pop("engine_2_fuel_flow")
            row["complete"] = False
        epoch, = analyze_sequences(self.rows)["epochs"]
        display = render_pilot_display(epoch)
        self.assertIn("--:--:--", display)
        self.assertNotIn("ELEC EXT PWR SUPPLY ON", display)
        self.assertIn("1. ENG 2 POWER LOSS", display)
        self.assertIn("2. ELEC GEN 2 SOURCE PATH LOSS", display)
        self.assertIn("0:23", display)
        self.assertIn("Checks matched      1: 5/7  2: 5/7", display)

    def test_origin_needs_consecutive_cold_ground_readings_and_resets_by_epoch(self):
        off, on = _with_startup(self.rows)[:2]
        clock = GroundPowerClock()
        clock.observe(off, 0)
        clock.observe(on, 0)
        clock.observe(off, 0)
        clock.observe(on, 0)
        self.assertEqual(clock.origin, 11)
        clock.observe(on, 1)
        self.assertIsNone(clock.origin)
        clock.observe(off, 1)
        clock.observe(on, 1)
        self.assertIsNone(clock.origin)
        clock.observe(off, 2)
        on["sample_index"] += 1
        clock.observe(on, 2)
        self.assertIsNone(clock.origin)
