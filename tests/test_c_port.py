"""Check the embedded C core against the Python fit on fixtures and recorded flights."""

from itertools import product
import tempfile
import unittest

from aircraft_debugger import c_port
from test_sequence_reasoning import (
    BLUE_PUMP, ENGINE, GEN, LEAK, MECHANISMS, PAIR_BOUNDS, RESULTS, YELLOW, synthetic_frame,
)


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

    def test_recorded_flights_fit_identically_after_every_observation(self):
        wide = {**PAIR_BOUNDS, BLUE_PUMP: {"blue_pressure_loss": [0, 30]}}
        cases = []
        for folder, bounds in (
            ("engine-drive-20261106-01/engine-auto", None), ("engine-drive-20261106-01/pair-auto", None),
            ("yellow-edp-isolated-20261106-01/run", None), ("timed-pair-20261106-01", None),
            ("timed-pair-20261106-01", PAIR_BOUNDS), ("timed-pair-20261106-01", wide),
            ("pressure-pair-20261106-01/pair", PAIR_BOUNDS), ("timed-separated-20261106-01", PAIR_BOUNDS),
        ):
            path = RESULTS / folder / "observations.jsonl"
            cases += c_port.recording_cases(path, bounds, prefixes=True, label=folder)
            cases += c_port.recording_cases(path, bounds, label=folder)
        self.assert_identical(cases, 100)

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
