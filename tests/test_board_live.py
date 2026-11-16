import shutil
import tempfile
import unittest
from pathlib import Path

from aircraft_debugger import board_live, c_port, device_check
from aircraft_debugger.airborne_profile import iter_profile_observations


RECORDING = Path(__file__).resolve().parents[1] / "results/yellow-edp-isolated-20261106-01/run/observations.jsonl"


class _Broken:
    def write(self, data):
        raise OSError("unplugged")

    def close(self):
        pass


class BoardLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        try:
            cls.executable = c_port.build_host(cls.directory.name)
        except c_port.CompilerUnavailable as error:
            cls.directory.cleanup()
            raise unittest.SkipTest(str(error))

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def _replay(self, output, records):
        shutil.copy(RECORDING, output / "observations.jsonl")
        shown = []
        observer = board_live.BoardObserver(device_check.HarnessTransport(self.executable, timed=True), output,
                                            echo=shown.append)
        try:
            for record in records:
                observer.accept(record)
        finally:
            observer.close()
        return observer, shown

    def test_replies_saved_during_a_run_match_python(self):
        records = list(iter_profile_observations(RECORDING))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            observer, shown = self._replay(output, records)
            report = board_live.check_replies(output)
            images = list(output.glob("board-screen-*.png"))
        self.assertIsNone(observer.failure)
        self.assertEqual(report["polls_identical_to_python"], len(records))
        self.assertEqual(report["mismatching_polls"] + report["unanswered_polls"], [])
        self.assertGreater(report["polls_with_evidence_frame"], 0)
        self.assertTrue(any("YEDP" in text for text in shown))
        self.assertEqual(len(images), len(shown))

    def test_a_missing_reply_is_reported(self):
        records = list(iter_profile_observations(RECORDING))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            self._replay(output, records[:-3])
            report = board_live.check_replies(output)
        self.assertEqual(report["unanswered_polls"], [record["sample_index"] for record in records[-3:]])

    def test_a_link_failure_does_not_reach_the_experiment(self):
        records = list(iter_profile_observations(RECORDING))
        with tempfile.TemporaryDirectory() as directory:
            observer = board_live.BoardObserver(device_check.HarnessTransport(self.executable), Path(directory),
                                                echo=lambda text: None)
            working, observer.transport = observer.transport, _Broken()
            observer.accept(records[0])
            observer.accept(records[1])
            working.close()
        self.assertIn("unplugged", observer.failure)
        self.assertEqual(observer.polls, 0)


if __name__ == "__main__":
    unittest.main()
