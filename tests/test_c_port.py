"""Check the embedded C core against the Python fit on fixtures and recorded flights."""

from itertools import product
import random
import tempfile
import unittest

from aircraft_debugger import c_port
from aircraft_debugger.airborne_profile import PILOT_CHANNELS, PROPULSION_CHANNELS, PROPULSION_PROFILE_ID
from test_sequence_reasoning import (
    BLUE_PUMP, ENGINE, GEN, LEAK, MECHANISMS, PAIR_BOUNDS, RESULTS, YELLOW, synthetic_frame,
)


RECORDED_FLIGHTS = (
    ("engine-drive-20261106-01/engine-auto", None), ("engine-drive-20261106-01/pair-auto", None),
    ("yellow-edp-isolated-20261106-01/run", None), ("timed-pair-20261106-01", None),
    ("timed-pair-20261106-01", PAIR_BOUNDS),
    ("timed-pair-20261106-01", {**PAIR_BOUNDS, BLUE_PUMP: {"blue_pressure_loss": [0, 30]}}),
    ("pressure-pair-20261106-01/pair", PAIR_BOUNDS), ("timed-separated-20261106-01", PAIR_BOUNDS),
    ("airborne-contrast-20261029-01", None), ("airborne-reference-20261027-01", None),
)
# Values on and beside every detector threshold. Repeats make the normal level the usual one.
LEVELS = {
    "generator_2_voltage": (115.0, 115.0, 115.0, 0.0, 0.0, 4.9, 5.0, 19.9, 20.0, 50.0, 99.9, 100.0, -1.0),
    "ac_bus_2": (115.0, 115.0, 100.0, 99.0, 20.0, 19.0, 0.0),
    "blue_quantity": (8.0, 8.0, 8.05, 7.95, 7.9, 7.85, 7.6, 7.5, 7.4, 3.0),
    "blue_pressure": (3000.0, 3000.0, 2500.0, 2499.0, 0.0),
    "engine_2_n2": (85.0, 85.0, 85.0, 60.0, 59.9, 55.0, 54.9, 10.0, -1.0),
    "engine_2_fuel_flow": (2500.0, 2500.0, 2500.0, 100.0, 99.0, 50.0, 49.0, 0.0),
    "yellow_edp_pressure": (3000.0, 3000.0, 2500.0, 2499.0, 500.0, 499.0, 0.0, 0.0, -1.0),
    "yellow_electric_pressure": (0.0, 0.0, 499.0, 500.0, 2499.0, 2500.0, 3000.0),
    "yellow_transfer_pressure": (0.0, 0.0, 499.0, 2500.0, 3000.0),
    "yellow_quantity": (12.0, 12.0, 12.0, 1.0, 0.9),
    "yellow_pressure": (3000.0, 3000.0, 2500.0, 2499.0, 2000.0, 1999.0, 0.0),
    "main_gear_1_wow": (False,) * 14 + (True,),
    "main_gear_2_wow": (False,) * 14 + (True,),
    "height_agl": (5000.0,) * 14 + (0.0, -1.0),
    "aircraft": ("A320-200-CFM",) * 25 + ("A320-200-IAE", "c172p"),
    "paused": (False,) * 30 + (True,),
}
FUZZ_STREAMS = 40
STEADY = {"altitude": 8000.0, "airspeed": 250.0, "engine_1_n1": 80.0, "engine_2_n1": 80.0, "ac_bus_1": 115.0,
          "vertical_speed": 0.0, "bank": 0.0, "autopilot_1": True, "autopilot_2": True, "autothrust": True,
          "ptu_selected": True, "external_power_output": 0.0}


NORMAL = {**{name: values[0] for name, values in LEVELS.items()}, **STEADY}


def make_poll(specs, index, sim_time, local, values, *, clock=None, defects=None, offsets=None, offline=False,
              last_time=None):
    """One schema 3 poll. `defects` maps a channel to a transport defect, `offsets` to a timestamp offset."""
    defects, offsets = defects or {}, offsets or {}
    started, received = local, local + 0.5
    readings = {}
    for name, spec in specs.items():
        value = (sim_time if clock is None else clock) if name == "sim_time" else values[name]
        reading = {"path": spec.path, "value": value, "valid": True, "error": None,
                   "sim_time_s": sim_time + offsets.get(name, 0.0),
                   "received_monotonic_s": local + 0.01, "reachable": True, "unit": spec.unit}
        defect = defects.get(name)
        if offline:
            reading.update(value=None, valid=False, error="connection_error", sim_time_s=None, reachable=False)
        elif defect == "missing":
            continue
        elif defect == "invalid":
            reading.update(value=None, valid=False, error="timeout", sim_time_s=None)
        elif defect == "untimed":
            reading["sim_time_s"] = None
        elif defect == "stale":
            started = received - 3.0
            reading["received_monotonic_s"] = started
        elif defect == "frozen" and last_time and name in last_time:
            reading["sim_time_s"] = last_time[name]
        if last_time is not None and reading["sim_time_s"] is not None:
            last_time[name] = reading["sim_time_s"]
        readings[name] = reading
    # The validator selects the start-up profile by the presence of the external-power reading.
    profile = PILOT_CHANNELS if "external_power_output" in readings else PROPULSION_CHANNELS
    return {
        "schema_version": 3, "observation_profile": PROPULSION_PROFILE_ID, "sample_index": index,
        "poll_started_monotonic_s": started, "received_monotonic_s": received, "readings": readings,
        "connected": any(reading["reachable"] for reading in readings.values()),
        "complete": readings.keys() == profile.keys() and all(reading["valid"] for reading in readings.values()),
    }


def telemetry_stream(seed, length=60):
    """Seeded schema 3 polls with threshold crossings and every transport defect the extractor handles."""
    rng = random.Random(seed)
    specs = PILOT_CHANNELS if seed % 4 == 0 else PROPULSION_CHANNELS
    ground_polls = rng.randint(1, 5) if seed % 4 == 0 else 0
    jitter = (0.0, 0.0, 0.0, 0.1, 0.2) if seed % 3 == 0 else (0.0,)
    change = 0.03 + 0.03 * (seed % 5)
    level = dict(NORMAL)
    last_time, rows = {}, []
    index, sim_time, local = rng.randint(0, 3), 100.0, 1000.0
    for poll in range(length):
        index += 2 if rng.random() < 0.04 else 1
        local += 1.0
        event = rng.random()
        if event < 0.012:
            sim_time = max(1.0, sim_time - 50.0)
        elif event < 0.02:
            local -= 100.0
        elif event >= 0.05:
            sim_time += rng.choice((1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 3.0, 3.1, 4.0))
        for name, values in LEVELS.items():
            if rng.random() < change:
                level[name] = rng.choice(values)
        values = dict(level)
        if poll < ground_polls:
            values.update(main_gear_1_wow=True, main_gear_2_wow=True, height_agl=0.0)
        offsets = {name: rng.choice(jitter) for name in specs}
        defects = {}
        if rng.random() < 0.2:
            target = rng.choice(list(specs))
            defect = rng.choice(("invalid", "missing", "untimed", "stale", "frozen", "skewed"))
            if defect == "skewed":
                offsets[target] += 0.3
            else:
                defects[target] = defect
        rows.append(make_poll(specs, index, sim_time, local, values, defects=defects, offsets=offsets,
                              offline=rng.random() < 0.03, last_time=last_time))
    return rows


def scripted_stream(polls, *, startup=False, offsets=None):
    """Polls one simulator second apart. Each poll overrides normal values and may carry these keys:

    ground (on the ground), defects, step (simulator seconds since the previous poll), skip (one
    sample index is left out before this poll) and clock_lag (how far the reported simulator
    clock trails the reading timestamps).
    """
    specs = PILOT_CHANNELS if startup else PROPULSION_CHANNELS
    rows, last_time, sim_time, index = [], {}, 100.0, -1
    for poll in polls:
        poll = dict(poll)
        index += 2 if poll.pop("skip", False) else 1
        sim_time += poll.pop("step", 1.0)
        defects, lag = poll.pop("defects", None), poll.pop("clock_lag", 0.0)
        values = {**NORMAL, **({"main_gear_1_wow": True, "main_gear_2_wow": True, "height_agl": 0.0}
                               if poll.pop("ground", False) else {}), **poll}
        rows.append(make_poll(specs, index, sim_time, 1000.0 + index, values, clock=sim_time - lag,
                              defects=defects, offsets=offsets, last_time=last_time))
    return rows


def scripted_streams():
    """Telemetry aimed at detector paths that recordings and random streams rarely reach."""
    def run(channel, *levels, **extra):
        return [{channel: level, **extra} for level in levels]

    normal = {}
    lost_pump = {"yellow_edp_pressure": 0.0, "yellow_transfer_pressure": 0.0}
    streams = {
        # A reading whose own timestamp repeats is unusable, so its abnormal value must not count.
        "repeated-time-generator": run("generator_2_voltage", 115.0, 115.0, 0.0)
        + [{"generator_2_voltage": 0.0, "defects": {"generator_2_voltage": "frozen"}}, normal, normal],
        **{f"repeated-time-{channel}": [normal] * 3 + [{channel: value, "defects": {channel: "frozen"}}] + [normal] * 2
           for channel, value in (("ac_bus_2", 0.0), ("blue_quantity", 7.4), ("blue_pressure", 0.0))},
        # A reading received more than two seconds before the poll completed is unusable.
        **{f"stale-{channel}": [normal] * 3 + [{"defects": {channel: "stale"}}] + [normal] * 2
           for channel in ("sim_time", "paused", "aircraft", "generator_2_voltage", "engine_2_n2")},
        # A backup source with an unusable reading leaves the supply state undetermined.
        "supply-transfer-unmeasured": [{"yellow_edp_pressure": 0.0, "yellow_transfer_pressure": -1.0,
                                        "yellow_pressure": 0.0}] * 9,
        # A skipped poll restarts the settling period.
        "supply-skipped-poll": [{**lost_pump, "yellow_electric_pressure": 3000.0, "yellow_pressure": 3000.0, **extra}
                                for extra in [{}] * 4 + [{"skip": True, "step": 2.0}] + [{}] * 3],
        "untimed-aircraft-first": [{"defects": {"aircraft": "untimed"}}] + [normal] * 3,
        # Generator confirmation needs consecutive low readings.
        "generator-low-then-normal": run("generator_2_voltage", 115.0, 115.0, 0.0, 115.0, 0.0, 115.0, 115.0),
        "generator-low-then-invalid": run("generator_2_voltage", 115.0, 115.0, 0.0)
        + [{"defects": {"generator_2_voltage": "invalid"}}] + run("generator_2_voltage", 0.0, 115.0),
        # Inventory thresholds met exactly: 0.1 - 0.0 is exactly the onset drop.
        "quantity-onset-exact": run("blue_quantity", 0.1, 0.1, 0.0, -0.5, -0.5),
        # Settled Yellow supply on each boundary value.
        "supply-backed-exact": [{**lost_pump, "yellow_electric_pressure": 2500.0, "yellow_pressure": 3000.0}] * 9,
        "supply-neither-exact": [{**lost_pump, "yellow_electric_pressure": 500.0, "yellow_pressure": 0.0}] * 9,
        "supply-line-exact": [{**lost_pump, "yellow_electric_pressure": 3000.0, "yellow_pressure": 2500.0}] * 9,
        "supply-contradicted": [{**lost_pump, "yellow_electric_pressure": 3000.0, "yellow_pressure": 0.0}] * 9,
        "supply-transfer-backed": [{"yellow_edp_pressure": 0.0, "yellow_electric_pressure": 0.0,
                                    "yellow_transfer_pressure": 3000.0, "yellow_pressure": 3000.0}] * 9,
        # Clock defects.
        "negative-clock": [{"clock_lag": 300.0}] * 5,
        "frozen-clock": [normal] * 3 + [{"clock_lag": 1.0}] + [normal] * 2,
        "reset-with-invalid-speed": [normal] * 4 + [{"step": -50.0, "defects": {"engine_2_n2": "invalid"}}]
        + run("engine_2_n2", 10.0, 10.0, 10.0),
        # Inventory and pressure order.
        "order-pressure-from-start": run("blue_quantity", 8.0, 8.0, 8.0, 8.0, 7.4, 7.4, blue_pressure=0.0),
    }
    result = [(name, scripted_stream(polls), None) for name, polls in streams.items()]

    def both(quantity, pressure):
        return [{"blue_quantity": q, "blue_pressure": p} for q, p in zip(quantity, pressure)]

    # Readings of one poll carry slightly different times. That must not create an order.
    result += [
        ("order-same-poll-quantity-first", scripted_stream(
            both((8.0, 8.0, 8.0, 7.4, 7.4, 7.4), (3000.0, 3000.0, 3000.0, 3000.0, 0.0, 0.0)),
            offsets={"blue_pressure": 0.1}), None),
        ("order-same-poll-pressure-first", scripted_stream(
            both((8.0, 8.0, 8.0, 8.0, 7.4, 7.4), (3000.0, 3000.0, 3000.0, 0.0, 0.0, 0.0)),
            offsets={"blue_quantity": 0.1}), None),
        ("supply-skewed", scripted_stream(
            [{**lost_pump, "yellow_electric_pressure": 3000.0, "yellow_pressure": 3000.0}] * 9,
            offsets={"yellow_quantity": 0.3}), None),
        ("drive-skewed", scripted_stream(run("generator_2_voltage", 115.0, 115.0, 0.0, 0.0, 0.0),
                                         offsets={"generator_2_voltage": 0.3}), None),
    ]

    # Detector state built on the ground, before the airborne window opens.
    ground = {
        "ground-generator-restored": (run("generator_2_voltage", 115.0, 115.0, 0.0, 0.0, 115.0),
                                      run("generator_2_voltage", 0.0, 115.0, 115.0)),
        "ground-generator-reduced": (run("generator_2_voltage", 115.0, 0.0, 50.0),
                                     run("generator_2_voltage", 0.0, 115.0, 115.0)),
        "ground-generator-confirmed": (run("generator_2_voltage", 115.0, 115.0, 0.0, 0.0),
                                       run("generator_2_voltage", 0.0, 0.0)),
        "ground-quantity-recovered-exact": (run("blue_quantity", 0.1, -0.5, -0.5, 0.0), run("blue_quantity", 0.0, 0.0)),
        "ground-quantity-recovered": (run("blue_quantity", 8.0, 8.0, 7.4, 8.0), run("blue_quantity", 7.8, 7.8)),
        "ground-quantity-second-loss": (run("blue_quantity", 8.0, 8.0, 7.4, 7.95), run("blue_quantity", 7.4, 7.4)),
        "ground-quantity-confirmed": (run("blue_quantity", 8.0, 8.0, 7.4), run("blue_quantity", 7.4, 7.4)),
    }
    result += [(name, scripted_stream([{**poll, "ground": True} for poll in before] + after, startup=True), None)
               for name, (before, after) in ground.items()]
    # Each ground indication alone keeps a start-up capture out of the airborne window.
    result += [(f"ground-only-{channel}", scripted_stream([{channel: value}] * 2 + [normal] * 3, startup=True), None)
               for channel, value in (("main_gear_1_wow", True), ("main_gear_2_wow", True), ("height_agl", 0.0))]
    return result


def onset_histories():
    """Every onset history as a tuple of ranks, where -1 marks an absent mechanism."""
    for ranks in product(range(-1, 5), repeat=5):
        if set(ranks) - {-1} == set(range(max(ranks) + 1)):
            yield ranks


def without(bounds, *roots):
    return {root: effects for root, effects in bounds.items() if root not in roots}


def fixture_cases():
    """The 1,082 onset-history fixtures, each also with evidence states the plain fixtures never produce."""
    for total, ranks in enumerate(onset_histories()):
        spacing = 2 if total % 2 else 7
        onsets = {root: 10 + spacing * rank for root, rank in zip(MECHANISMS, ranks) if rank >= 0}
        frame, bounds = synthetic_frame(onsets, delayed=total % 2, backup=total % 3, depletes=total % 5)
        yield f"fixture-{total}", frame, bounds

        varied, _ = synthetic_frame(onsets, delayed=total % 2, backup=total % 3, depletes=total % 5)
        facts, relations = varied["facts"], varied["temporal_relations"]
        if total % 3 == 1:
            facts[list(facts)[(total // 3) % 8]] = {"state": "unknown", "onset_interval": None}
        for fact in facts.values():
            if fact["onset_interval"] and total % 4 == 1:
                fact["onset_interval"]["covered_through_confirmation"] = False
            if fact["onset_interval"] and total % 4 == 2:
                fact["onset_interval"]["lower_sim_time_s"] = None
        relations["yellow_pressure_follows_measured_supply"] = {
            "status": ("consistent", "contradicted", "not_applicable", "unknown")[(total // 2) % 4]}
        relations.setdefault("inventory_before_pressure", {"status": ("consistent", "not_applicable")[total % 2]})
        choice = total % 5
        partial = (bounds, bounds, None, without(bounds, MECHANISMS[(total // 5) % 5]),
                   without(bounds, MECHANISMS[(total // 5) % 5], MECHANISMS[(total // 25) % 5]))[choice]
        yield f"varied-{total}", varied, partial


def unknown_cases():
    """One or two mechanisms with each effect unread in turn, under full, absent and partial bounds."""
    for total, ranks in enumerate(onset_histories()):
        active = [root for root, rank in zip(MECHANISMS, ranks) if rank >= 0]
        if len(active) > 2:
            continue
        onsets = {root: 10 + 4 * rank for root, rank in zip(MECHANISMS, ranks) if rank >= 0}
        for index in range(8):
            for variant in range(3):
                frame, bounds = synthetic_frame(onsets, delayed=index % 2, backup=variant % 2, depletes=total % 2)
                frame["facts"][list(frame["facts"])[index]] = {"state": "unknown", "onset_interval": None}
                chosen = (bounds, None, without(bounds, *active[:1]))[variant]
                yield f"unknown-{total}-{index}-{variant}", frame, chosen


def retained_drive_cases():
    """A local source loss one second before another onset, with Engine 2 lost later.

    The reading taken with drive retained then limits the local onset more tightly
    than the effect's own bracket does once the engine path has no declared bounds.
    """
    for local, other, delayed, backup in product((GEN, YELLOW), (LEAK, BLUE_PUMP), (0, 1), (0, 1)):
        for engine_onset in (13, 14):
            frame, bounds = synthetic_frame({local: 10, other: 11, ENGINE: engine_onset},
                                            delayed=delayed, backup=backup, depletes=0)
            for variant, chosen in enumerate((bounds, without(bounds, ENGINE), without(bounds, other))):
                yield f"retained-{local}-{other}-{delayed}{backup}-{engine_onset}-{variant}", frame, chosen


def boundary_cases():
    """Onset brackets whose floors and deadlines coincide, so inclusive and strict comparisons differ."""
    effects = ("generator_source_anomaly", "blue_inventory_loss", "blue_pressure_loss",
               "engine_2_fuel_flow_loss", "engine_2_core_speed_loss", "yellow_edp_output_loss")
    names = list(c_port.model_tables()["facts"])
    bounds = {GEN: {"generator_source_anomaly": [1, 1]}, LEAK: {"blue_inventory_loss": [1, 1]},
              BLUE_PUMP: {"blue_pressure_loss": [1, 1]},
              ENGINE: {"engine_2_fuel_flow_loss": [1, 1], "engine_2_core_speed_loss": [1, 1],
                       "generator_source_anomaly": [1, 1], "yellow_edp_output_loss": [1, 1]},
              YELLOW: {"yellow_edp_output_loss": [1, 1]}}
    # Each effect's bracket starts 0, 1 or 2 seconds after time 10 and lasts one second.
    for index, offsets in enumerate(product((None, 0, 1, 2), repeat=len(effects))):
        facts = {name: {"state": "not_observed", "onset_interval": None} for name in names}
        for effect, offset in zip(effects, offsets):
            if offset is not None:
                facts[effect] = {"state": "observed", "onset_interval": {
                    "lower_sim_time_s": 10.0 + offset, "upper_sim_time_s": 11.0 + offset,
                    "covered_through_confirmation": True}}
        yield f"boundary-{index}", {"facts": facts, "temporal_relations": {}}, bounds


class GeneratedModelTests(unittest.TestCase):
    def test_committed_tables_match_the_python_model(self):
        for name, text in zip(c_port.MODEL_FILES, c_port.render_model()):
            with self.subTest(file=name):
                committed = (c_port.EMBEDDED / "core" / name).read_text(encoding="utf-8")
                self.assertEqual(committed, text, "Run python -B -m aircraft_debugger.c_port --write-model")

    def test_tables_cover_the_whole_catalogue(self):
        tables = c_port.model_tables()
        self.assertEqual((len(tables["sets"]), len(tables["histories"])), (32, 1082))
        self.assertEqual(tables["first"][-1], 1082)
        self.assertTrue(all(len(groups) <= 5 for _, groups in tables["histories"]))


class EmbeddedCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        cls.directory = directory.name
        try:
            cls.executable = c_port.build_host(cls.directory)
        except c_port.CompilerUnavailable as error:
            raise unittest.SkipTest(str(error))

    def assert_identical(self, cases, minimum):
        count, wrong = c_port.compare(cases, self.executable, self.directory)
        self.assertEqual(wrong, [])
        self.assertGreaterEqual(count, minimum)

    def test_fixture_histories_fit_identically(self):
        self.assert_identical(fixture_cases(), 2164)

    def test_unread_effects_fit_identically(self):
        self.assert_identical(unknown_cases(), 800)

    def test_source_loss_with_drive_retained_fits_identically(self):
        self.assert_identical(retained_drive_cases(), 96)

    def test_coinciding_floors_and_deadlines_fit_identically(self):
        self.assert_identical(boundary_cases(), 4096)

    def test_strict_group_order_excludes_a_tied_later_group(self):
        tables = c_port.model_tables()
        facts = {name: {"state": "not_observed", "onset_interval": None} for name in tables["facts"]}
        for effect, lower in (("generator_source_anomaly", 10.0), ("blue_pressure_loss", 11.0)):
            facts[effect] = {"state": "observed", "onset_interval": {
                "lower_sim_time_s": lower, "upper_sim_time_s": lower + 1, "covered_through_confirmation": True}}
        bounds = {GEN: {"generator_source_anomaly": [1, 1]}, BLUE_PUMP: {"blue_pressure_loss": [1, 1]}}
        text = c_port.frame_case("pair", {"facts": facts, "temporal_relations": {}}, bounds, tables)
        statuses = c_port.run_harness(self.executable, text, self.directory)[0].split()[3]
        pair = [identifier for identifier, _ in tables["sets"]].index(f"{GEN}+{BLUE_PUMP}")
        orders = {tuple(groups): statuses[index] for index, (owner, groups) in enumerate(tables["histories"])
                  if owner == pair}
        generator, pump = (1 << tables["roots"].index(root) for root in (GEN, BLUE_PUMP))
        self.assertEqual(orders, {(generator | pump,): "C", (generator, pump): "C", (pump, generator): "T"})

    def test_recorded_flights_extract_and_fit_identically_after_every_poll(self):
        streams = [(folder, c_port.recording_rows(RESULTS / folder / "observations.jsonl"), bounds)
                   for folder, bounds in RECORDED_FLIGHTS]
        count, framed, wrong = c_port.compare_streams(streams, self.executable, self.directory)
        self.assertEqual(wrong, [])
        self.assertEqual(count, framed)
        self.assertGreaterEqual(count, 600)

    def test_defective_telemetry_extracts_identically_after_every_poll(self):
        streams = [(f"seed-{seed}", telemetry_stream(seed), None) for seed in range(FUZZ_STREAMS)]
        count, framed, wrong = c_port.compare_streams(streams, self.executable, self.directory, fit=False)
        self.assertEqual(wrong, [])
        self.assertEqual(count, 60 * FUZZ_STREAMS)
        self.assertGreater(framed, count // 2)
        self.assertLess(framed, count)

    def test_scripted_telemetry_extracts_identically_after_every_poll(self):
        count, framed, wrong = c_port.compare_streams(scripted_streams(), self.executable, self.directory, fit=False)
        self.assertEqual(wrong, [])
        self.assertGreater(framed, 150)

    def test_sample_index_must_increase(self):
        tables = c_port.model_tables()
        poll = c_port.poll_lines(telemetry_stream(1, length=1)[0], tables)
        lines = c_port.run_harness(self.executable, "\n".join(["stream repeat", *poll, *poll]) + "\n",
                                   self.directory)
        self.assertEqual([line.split()[1] for line in lines], ["0", "-3"])

    def test_text_link_greets_and_rejects_malformed_lines(self):
        model_id = c_port.model_tables()["model"]["model_id"]
        self.assertEqual(c_port.run_harness(self.executable, "hello\n\n", self.directory),
                         [f"aerotrace {model_id} ready"])
        for line in ("launch", "f 0 1 1 1 0x1p+0", "b 0 0 1.5 0x1p+0", "b 0 0 0x1p+0 0x1p+0 extra",
                     "c 99 1 1 1 0x0p+0 0x0p+0 0x0p+0", "s -1 0x0p+0 1 1 0", "b 0 0 0x1.p 0x1p+0"):
            with self.subTest(line=line), self.assertRaises(RuntimeError):
                c_port.run_harness(self.executable, line + "\n", self.directory)

    def test_invalid_inputs_are_rejected(self):
        tables = c_port.model_tables()
        frame, _ = synthetic_frame({LEAK: 10}, delayed=0, backup=1, depletes=0)
        valid = c_port.frame_case("valid", frame, {}, tables)
        leak, pressure = tables["roots"].index(LEAK), tables["facts"].index("blue_pressure_loss")
        generator = tables["roots"].index(GEN)
        relation = tables["relations"].index("generator_loss_with_drive_retained")
        self.assertIn(f"\nr {relation} 1 0 ", valid)
        self.assertIn("\nf 0 0 ", valid)
        cases = (
            valid,
            valid.replace("case valid", f"case conditional-path\nb {leak} {pressure} 0x0p+0 0x1p+0"),
            valid.replace("case valid", f"case reversed\nb {generator} 0 0x1p+1 0x1p+0"),
            valid.replace("case valid", f"case too-long\nb {generator} 0 0x0p+0 0x1p+7"),
            valid.replace("case valid", "case no-witness").replace(f"\nr {relation} 1 0 ", f"\nr {relation} 3 0 "),
            valid.replace("case valid", "case bad-state").replace("\nf 0 0 ", "\nf 0 7 "),
        )
        lines = c_port.run_harness(self.executable, "".join(cases), self.directory)
        self.assertEqual([line.split()[:2] for line in lines], [
            ["valid", "0"], ["conditional-path", "-2"], ["reversed", "-2"], ["too-long", "-2"],
            ["no-witness", "-1"], ["bad-state", "-1"]])


if __name__ == "__main__":
    unittest.main()
