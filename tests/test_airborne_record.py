"""Read-only protocol fixtures; these are not airborne physical-response trials."""

from dataclasses import asdict
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.parse import unquote, urlsplit

from aircraft_debugger.airborne_admission import AirborneAdmission, QualificationSettings, READINESS_CHANNELS
from aircraft_debugger.airborne_profile import AIRBORNE_CHANNELS, iter_profile_observations
from aircraft_debugger.airborne_record import collect_reference, load_settings
from aircraft_debugger.flightgear import FlightGearClient, PropertyReading, TelemetrySnapshot


class AirborneRecorderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nodes = {}
        cls.requests = []
        cls.epoch = time.monotonic()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                path = unquote(urlsplit(self.path).path).removeprefix("/json")
                cls.requests.append(("GET", path))
                at = 100.0 + time.monotonic() - cls.epoch
                value = at if path == "/sim/time/elapsed-sec" else cls.nodes.get(path)
                if path not in cls.nodes:
                    status, payload = 404, {}
                else:
                    status, payload = 200, {"path": path, "value": value, "ts": at}
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                cls.requests.append(("POST", self.path))
                self.send_response(500)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *_args):
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        self.requests.clear()
        self.nodes.clear()
        type(self).epoch = time.monotonic()
        values = {
            "aircraft": "A320-200-CFM", "sim_time": 100.0, "paused": False,
            "altitude": 10000.0, "airspeed": 250.0, "engine_1_n1": 70.0,
            "engine_2_n1": 70.0, "generator_2_voltage": 115.0,
            "ac_bus_1": 115.0, "ac_bus_2": 115.0, "blue_pressure": 3000.0,
            "blue_quantity": 8.0, "main_gear_1_wow": False,
            "main_gear_2_wow": False, "height_agl": 9000.0,
            "vertical_speed": 0.0, "bank": 0.0, "autopilot_1": False,
            "autopilot_2": False, "autothrust": False,
        }
        self.nodes.update({spec.path: values[name] for name, spec in AIRBORNE_CHANNELS.items()})
        self.nodes.update({spec.path: "XX" if spec.kind == "string" else name.startswith("engine_")
                           for name, spec in READINESS_CHANNELS.items()})
        base = Path("work/tests")
        base.mkdir(parents=True, exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.output = self.root / "recording"
        # Short duration is a transport-fixture setting, not a proposed flight test.
        self.settings = QualificationSettings(qualification_duration_sim_s=0.15)

    def reader(self):
        return FlightGearClient(port=self.server.server_port, timeout_s=1.0, max_workers=4)

    def test_get_only_collection_keeps_readiness_private_and_replays_qualification(self):
        result = collect_reference(self.output, self.settings, max_wait_s=3,
                                   interval_s=0.1, client=self.reader())
        self.assertEqual(result["status"], "qualified_recorded_window")
        self.assertTrue(result["artifacts_complete"])
        self.assertFalse(result["simulator_writes_performed"])
        self.assertTrue(all(method == "GET" for method, _ in self.requests))
        public = (self.output / "observations.jsonl").read_text(encoding="utf-8")
        for spec in READINESS_CHANNELS.values():
            self.assertNotIn(spec.path, public)
        self.assertNotIn('"qualified"', public)
        rows = list(iter_profile_observations(self.output / "observations.jsonl"))
        private = [json.loads(line) for line in (self.output / "private_truth/qualification.jsonl").read_text().splitlines()]
        self.assertEqual(len(rows), result["samples"])
        self.assertEqual(len(rows), len(private))
        gate = AirborneAdmission(self.settings)
        for row, check in zip(rows, private):
            source = check["readiness"]
            readings = {name: PropertyReading(**value) for name, value in source["readings"].items()}
            snapshot = TelemetrySnapshot(readings, source["connected"], source["complete"], source["received_monotonic_s"])
            self.assertEqual(gate.update(row, snapshot, check["evaluated_monotonic_s"]), check["gate"])
        manifest = json.loads((self.output / "manifest.json").read_text())
        self.assertEqual(hashlib.sha256((self.output / manifest["observations"]).read_bytes()).hexdigest(), manifest["sha256"])
        self.assertEqual(hashlib.sha256((self.output / manifest["qualification_settings"]).read_bytes()).hexdigest(), manifest["qualification_settings_sha256"])
        self.assertEqual(hashlib.sha256((self.output / manifest["qualification_checks"]).read_bytes()).hexdigest(), manifest["qualification_checks_sha256"])
        for source, digest in manifest["source_sha256"].items():
            archived = self.output / manifest["executed_source_archives"][source]
            self.assertEqual(hashlib.sha256(archived.read_bytes()).hexdigest(), digest)

    def test_missing_private_readiness_keeps_valid_public_context_but_never_qualifies(self):
        self.nodes.pop(READINESS_CHANNELS["blue_leak_fault"].path)
        result = collect_reference(self.output, self.settings, max_wait_s=0.15,
                                   interval_s=0.05, client=self.reader())
        self.assertEqual(result["status"], "not_qualified")
        self.assertFalse(result["last_gate"]["qualified"])
        self.assertTrue(list(iter_profile_observations(self.output / "observations.jsonl")))
        self.assertTrue(all(method == "GET" for method, _ in self.requests))

    def test_interruption_retains_public_partial_data_and_aborted_status(self):
        client = self.reader()

        class InterruptOnReadiness:
            def poll(_self, channels):
                if set(channels) == set(READINESS_CHANNELS):
                    raise KeyboardInterrupt("fixture collection interrupted")
                return client.poll(channels)

        with self.assertRaises(KeyboardInterrupt):
            collect_reference(self.output, self.settings, max_wait_s=3,
                              interval_s=0.1, client=InterruptOnReadiness())
        result = json.loads((self.output / "private_truth/summary.json").read_text())
        manifest = json.loads((self.output / "manifest.json").read_text())
        self.assertEqual(result["status"], "aborted")
        self.assertEqual(result["failure"]["type"], "KeyboardInterrupt")
        self.assertIsNone(result["last_gate"])
        self.assertTrue(manifest["partial_collection"])
        self.assertEqual(len(list(iter_profile_observations(self.output / "observations.jsonl"))), 1)

    def test_output_preservation_and_settings_validation_do_not_contact_simulator(self):
        self.output.mkdir()
        sentinel = self.output / "keep.txt"
        sentinel.write_text("preserve", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            collect_reference(self.output, self.settings, client=self.reader())
        self.assertEqual(sentinel.read_text(), "preserve")
        self.assertEqual(self.requests, [])
        self.assertEqual(asdict(load_settings(Path("configs/airborne-qualification-settings.json"))),
                         asdict(QualificationSettings()))
        bad = self.root / "bad-settings.json"
        for value in ({"maximum_sim_gap_s": True}, {"unrecognized": 1}, []):
            bad.write_text(json.dumps(value), encoding="utf-8")
            with self.subTest(value=value), self.assertRaises(ValueError):
                load_settings(bad)


if __name__ == "__main__":
    unittest.main()
