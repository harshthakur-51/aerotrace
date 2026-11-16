"""Check the C screen renderer against the Python reference layout, by reading its pixels back as text."""

from itertools import product
import json
import tempfile
import unittest

from aircraft_debugger import c_port, screen
from aircraft_debugger.sequence_reasoning import _catalogue_orders, _fit_epoch, _response_bounds
from test_c_port import RECORDED_FLIGHTS, fixture_cases, scripted_streams, unknown_cases
from test_sequence_reasoning import GEN, RESULTS, synthetic_frame


def unread_mix_cases():
    """Every mix of observed and unread effects. Unread effects leave up to four smallest sets open."""
    names = list(c_port.model_tables()["facts"])
    for index, states in enumerate(product(("observed", "unknown"), repeat=len(names))):
        facts = {}
        for position, (name, state) in enumerate(zip(names, states)):
            interval = {"lower_sim_time_s": 10.0 + position, "upper_sim_time_s": 11.0 + position,
                        "covered_through_confirmation": True}
            facts[name] = {"state": state, "onset_interval": interval if state == "observed" else None}
        yield f"mix-{index}", {"facts": facts, "temporal_relations": {}}, None


def hold_streams():
    """The five-fault flight, and a copy whose gap with no fit lasts seven polls.

    The copy repeats the gap's first poll at whole simulator seconds after it, so one repeat
    falls exactly on the end of the hold.
    """
    rows = c_port.recording_rows(RESULTS / "board-live-20261117-01/run/observations.jsonl")
    lost = next(index for index, row in enumerate(rows) if row["readings"]["engine_2_fuel_flow"]["value"] < 100)
    copies = []
    for step in range(1, 7):
        copy = json.loads(json.dumps(rows[lost]))
        copy["sample_index"] += step
        copy["received_monotonic_s"] += step
        for reading in copy["readings"].values():
            reading["received_monotonic_s"] += step
            reading["sim_time_s"] += step
        copy["readings"]["sim_time"]["value"] += step
        copies.append(copy)
    return [("five", rows, None), ("stuck", rows[:lost + 1] + copies, None)]


class ScreenLayoutTests(unittest.TestCase):
    def test_every_glyph_is_distinct_and_fits_the_cell(self):
        table = [tuple(screen.glyph_columns(character)) for character in screen._GLYPHS]
        self.assertEqual(len(set(table)), len(table))
        self.assertTrue(all(0 <= byte < 128 for glyph in table for byte in glyph))
        self.assertTrue(all(len(rows.split()) == 7 and all(len(row) == 5 for row in rows.split())
                            for rows in screen._GLYPHS.values()))

    def test_labels_cover_the_model_and_fit_their_cells(self):
        model = c_port.model_tables()["model"]
        self.assertEqual(list(screen.ROOT_TAGS), list(model["roots"]))
        self.assertEqual(list(screen.FACT_TAGS), list(model["facts"]))
        self.assertTrue(all(len(tag) <= 4 for tag in screen.FACT_TAGS.values()))
        used = set("".join([*screen.ROOT_TAGS.values(), *screen.FACT_TAGS.values()]))
        self.assertLessEqual(used, set(screen._GLYPHS))
        # Any mechanism set fits on the three body lines.
        every_root = screen._explanation_lines(1, "?", list(screen.ROOT_TAGS.values()))
        self.assertLessEqual(len(every_root), screen.BODY_ROWS)
        self.assertTrue(all(len(line) <= screen.COLUMNS for line in every_root))

    def test_png_has_the_enlarged_size(self):
        image = screen.png([bytes(screen.WIDTH)] * screen.PAGES, scale=3)
        self.assertEqual(image[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(image[16:24], (screen.WIDTH * 3).to_bytes(4, "big") + (screen.HEIGHT * 3).to_bytes(4, "big"))


class ScreenRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        cls.directory = directory.name
        try:
            cls.executable = c_port.build_host(cls.directory)
        except c_port.CompilerUnavailable as error:
            raise unittest.SkipTest(str(error))
        cls.tables = c_port.model_tables()
        cls.model = cls.tables["model"]
        cls.catalogue = _catalogue_orders(cls.model)

    def frame_screens(self, cases):
        """Render each (name, frame, raw bounds) case in C and build what Python expects."""
        text, expected = [], []
        for index, (_, frame, raw) in enumerate(cases):
            bounds = _response_bounds(raw, self.model)
            text.append(c_port.frame_case(str(index), frame, bounds, self.tables) + "screen\n")
            expected.append(screen.screen_content(_fit_epoch(frame, self.model, bounds, self.catalogue), self.model))
        replies = c_port.run_harness(self.executable, "".join(text), self.directory)
        drawn = [screen.pages_from_hex(line.split()[1]) for line in replies if line.startswith("screen ")]
        return drawn, expected

    def assert_same_pixels(self, drawn, expected):
        """The C frame buffer equals the Python rendering, and reads back as the same content."""
        self.assertEqual(len(drawn), len(expected))
        self.assertEqual([index for index, (pages, content) in enumerate(zip(drawn, expected))
                          if pages != screen.render(content)], [])
        self.assertEqual([index for index, (pages, content) in enumerate(zip(drawn, expected))
                          if screen.decode(pages) != content], [])

    def test_fixture_frames_draw_the_reference_layout(self):
        drawn, expected = self.frame_screens([*fixture_cases(), *unknown_cases()])
        self.assert_same_pixels(drawn, expected)
        # The fixtures reach the wrapped, truncated, unconfirmed and no-fit layouts.
        bodies = ["\n".join(content["body"]) for content in expected]
        headers = {content["header"].split(None, 1)[1].strip() for content in expected}
        self.assertTrue(any("MORE" in body for body in bodies))
        self.assertTrue(any(line.startswith("  ") and line.strip() for content in expected for line in content["body"]))
        self.assertTrue(any("1?" in body for body in bodies))
        self.assertTrue(any("UNIQUE" in content["history"] for content in expected))
        self.assertLessEqual({"NO FAULT", "NO FIT", "1 CAUSE", "2 CAUSES"}, headers)

    def test_more_causes_than_lines_are_counted_and_keep_the_history_line(self):
        drawn, expected = self.frame_screens(unread_mix_cases())
        self.assert_same_pixels(drawn, expected)
        crowded = [content for content in expected if content["header"].endswith("4 CAUSES")]
        self.assertTrue(crowded)
        self.assertTrue(all(content["body"][2].strip() == "+2 MORE" and content["history"].startswith("HIST C:")
                            for content in crowded))

    def test_telemetry_streams_draw_the_reference_layout_after_every_poll(self):
        streams = [(folder, c_port.recording_rows(RESULTS / folder / "observations.jsonl"), bounds)
                   for folder, bounds in RECORDED_FLIGHTS[:5]] + scripted_streams()
        drawn = c_port.screens(streams, self.executable, self.directory, self.tables)
        expected = self.stream_screens(streams)
        self.assert_same_pixels(drawn, expected)
        self.assertTrue(any(content["header"].endswith("NO DATA") for content in expected))

    def stream_screens(self, streams):
        return c_port.expected_screens(streams, self.tables)

    def test_a_short_gap_with_no_fit_holds_the_previous_explanation(self):
        """Five staged faults: fuel flow fell two polls before core speed, so nothing fitted for two polls."""
        streams = hold_streams()
        rows = streams[0][1]
        drawn = c_port.screens(streams, self.executable, self.directory, self.tables)
        expected = self.stream_screens(streams)
        self.assert_same_pixels(drawn, expected)
        states = [content["header"].split(None, 1)[1].strip() for content in expected]
        five, stuck = states[:len(rows)], states[len(rows):]
        self.assertEqual(five.count("CHECKING"), 2)
        self.assertNotIn("NO FIT", five)
        self.assertEqual(five[-1], "1 CAUSE")
        held = expected[five.index("CHECKING")]["body"]
        self.assertEqual([line.strip() for line in held[:2]], ["1?GEN2+BLEAK+BPUMP+", "YEDP"])
        # A gap longer than the hold ends in NO FIT. The last six polls are exactly 1 to 6 seconds into the gap.
        self.assertEqual(stuck[-6:], ["CHECKING"] * 3 + ["NO FIT"] * 3)

    def test_screen_before_any_fit_and_after_a_rejected_frame_shows_no_data(self):
        frame, _ = synthetic_frame({GEN: 10}, delayed=0, backup=1, depletes=0)
        fitted = c_port.frame_case("ok", frame, {}, self.tables)
        rejected = fitted.replace("case ok", "case bad").replace("\nf 1 0 ", "\nf 1 7 ")
        self.assertNotEqual(fitted.replace("case ok", "case bad"), rejected)
        replies = c_port.run_harness(self.executable, "screen\n" + fitted + "screen\n" + rejected + "screen\n",
                                     self.directory)
        headers = [screen.decode(screen.pages_from_hex(line.split()[1]))["header"].split(None, 1)[1].strip()
                   for line in replies if line.startswith("screen ")]
        self.assertEqual(headers, ["NO DATA", "1 CAUSE", "NO DATA"])


if __name__ == "__main__":
    unittest.main()
