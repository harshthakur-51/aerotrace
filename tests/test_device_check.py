"""Check the poll sender against the PC harness, which runs the same text link as the firmware."""

import tempfile
import unittest

from aircraft_debugger import c_port, device_check
from test_c_port import scripted_streams
from test_sequence_reasoning import PAIR_BOUNDS, RESULTS


class ScriptedTransport:
    """Replays fixed lines, as a board that ignores what it is sent would."""

    def __init__(self, *lines):
        self.lines = [line.encode("ascii") + b"\n" for line in lines]
        self.sent = b""

    def write(self, data):
        self.sent += data

    def readline(self):
        return self.lines.pop(0) if self.lines else b""


class TamperingTransport:
    """Wraps a real link partner. It can send extra lines first and alter the partner's lines."""

    def __init__(self, inner, *, noise=(), change=lambda line: line):
        self.inner, self.noise, self.change = inner, list(noise), change

    def write(self, data):
        self.inner.write(data)

    def readline(self):
        return self.noise.pop(0) if self.noise else self.change(self.inner.readline())


class DeviceCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        try:
            cls.executable = c_port.build_host(directory.name)
        except c_port.CompilerUnavailable as error:
            raise unittest.SkipTest(str(error))
        cls.tables = c_port.model_tables()
        cls.model_id = cls.tables["model"]["model_id"]
        rows = c_port.recording_rows(RESULTS / "timed-pair-20261106-01" / "observations.jsonl")
        cls.recorded = [("timed-pair", rows, PAIR_BOUNDS)]

    def harness(self, *, timed=False):
        transport = device_check.HarnessTransport(self.executable, timed=timed)
        self.addCleanup(transport.close)
        return transport

    def test_harness_replies_match_python_poll_by_poll(self):
        report = device_check.run_streams(self.harness(), self.recorded, self.tables)
        self.assertEqual(report["mismatches"], [])
        self.assertEqual((report["polls"], report["framed"], report["timed"]), (76, 76, False))
        self.assertEqual(report["extract_us"], [])
        self.assertEqual(len(report["round_trip_s"]), 76)

    def test_timing_lines_are_collected_for_every_poll(self):
        streams = scripted_streams()
        report = device_check.run_streams(self.harness(timed=True), streams, self.tables, fit=False)
        self.assertEqual(report["mismatches"], [])
        self.assertTrue(report["timed"])
        self.assertEqual(report["polls"], sum(len(rows) for _, rows, _ in streams))
        self.assertLess(report["framed"], report["polls"])
        self.assertEqual(len(report["extract_us"]), report["polls"])
        self.assertEqual(len(report["fit_us"]), report["polls"])

    def test_boot_output_before_the_greeting_is_skipped(self):
        boot = [b"ESP-ROM:esp32p4\r\n", b"\xff\xfegarbage\r\n", b"\r\n"]
        report = device_check.run_streams(TamperingTransport(self.harness(), noise=boot), self.recorded, self.tables)
        self.assertEqual((report["mismatches"], report["polls"]), ([], 76))
        noisy = ScriptedTransport("ESP-ROM:esp32p4", "boot noise", f"aerotrace {self.model_id} ready timed")
        self.assertTrue(device_check.greet(noisy, self.model_id))
        self.assertEqual(noisy.sent, b"hello\n")

    def test_altered_reply_is_reported_as_a_mismatch(self):
        def alter(line):
            # Change the last digit of every poll reply. The greeting does not start with a digit.
            return line.rstrip()[:-1] + b"9\n" if line[:1].isdigit() else line

        transport = TamperingTransport(self.harness(), change=alter)
        report = device_check.run_streams(transport, self.recorded, self.tables)
        self.assertEqual(len(report["mismatches"]), 76)
        self.assertTrue(report["mismatches"][0].startswith("timed-pair@"))

    def test_wrong_model_silence_and_rejected_lines_are_errors(self):
        cases = {
            "another model": ScriptedTransport("aerotrace some-other-model ready"),
            "silent": ScriptedTransport(),
            "no greeting": ScriptedTransport(*["log line"] * 300),
            "rejected": ScriptedTransport(f"aerotrace {self.model_id} ready", "error malformed line"),
            "no timing line": ScriptedTransport(f"aerotrace {self.model_id} ready timed", "0 0 none", "1 0 none"),
        }
        first_index = self.recorded[0][1][0]["sample_index"]
        cases["no timing line"].lines[1] = f"{first_index} 0 none\n".encode("ascii")
        for name, transport in cases.items():
            with self.subTest(case=name), self.assertRaises(device_check.LinkError):
                device_check.run_streams(transport, self.recorded, self.tables)

    def test_spread_reports_median_high_percentile_and_maximum(self):
        self.assertEqual(device_check.spread([5]), (5, 5, 5))
        self.assertEqual(device_check.spread(list(range(1, 101))), (50.5, 96, 100))


if __name__ == "__main__":
    unittest.main()
