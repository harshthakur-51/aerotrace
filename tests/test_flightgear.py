"""Transport boundary tests against a local FlightGear-shaped HTTP server."""

import http.server
import json
import socket
import threading
import time
import unittest
from urllib.parse import unquote, urlsplit

from aircraft_debugger.flightgear import FlightGearClient, PropertySpec


class FlightGearBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.responses = {}
        cls.requests = []
        cls.active_requests = 0
        cls.peak_requests = 0
        cls.request_lock = threading.Lock()

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlsplit(self.path)
                cls.requests.append((self.command, unquote(parsed.path), parsed.query))
                status, body, delay = cls.responses.get(unquote(parsed.path), (404, {}, 0))
                with cls.request_lock:
                    cls.active_requests += 1
                    cls.peak_requests = max(cls.peak_requests, cls.active_requests)
                try:
                    time.sleep(delay)
                    if not isinstance(body, bytes):
                        body = json.dumps(body).encode("utf-8")
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except (ConnectionError, OSError):
                    pass  # Expected when a deliberate timeout closes the client.
                finally:
                    with cls.request_lock:
                        cls.active_requests -= 1

            def log_message(self, *args):
                pass

        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        self.responses.clear()
        self.requests.clear()
        self.client = FlightGearClient(port=self.server.server_port, timeout_s=0.1)

    def node(self, path, value, timestamp=12.5):
        self.responses["/json" + path] = (
            200, {"path": path, "type": "double", "value": value, "ts": timestamp}, 0
        )

    def test_typed_and_legacy_numeric_values_and_indexed_paths(self):
        self.node("/position/altitude-ft", 1234.5)
        self.node("/engines/engine[1]/n1", "72.3")
        snapshot = self.client.poll({
            "altitude": PropertySpec("/position/altitude-ft", unit="ft"),
            "engine_2_n1": PropertySpec("/engines/engine[1]/n1", unit="percent"),
        })
        self.assertTrue(snapshot.connected)
        self.assertTrue(snapshot.complete)
        self.assertEqual(snapshot.readings["altitude"].value, 1234.5)
        self.assertEqual(snapshot.readings["engine_2_n1"].value, 72.3)
        self.assertEqual(snapshot.readings["altitude"].sim_time_s, 12.5)
        self.assertEqual(snapshot.readings["altitude"].unit, "ft")
        self.assertTrue(all(request[0] == "GET" for request in self.requests))
        self.assertTrue(all(request[2] == "t=y&d=1" for request in self.requests))
        json.dumps(snapshot.to_dict(), allow_nan=False)

    def test_missing_property_is_visible_and_does_not_reuse_last_reading(self):
        self.node("/position/altitude-ft", 1200)
        channels = {"altitude": PropertySpec("/position/altitude-ft")}
        self.assertTrue(self.client.poll(channels).complete)
        self.responses.clear()
        snapshot = self.client.poll(channels)
        self.assertTrue(snapshot.connected)
        self.assertFalse(snapshot.complete)
        self.assertIsNone(snapshot.readings["altitude"].value)
        self.assertEqual(snapshot.readings["altitude"].error, "missing_property")

    def test_bad_payloads_never_become_valid_numbers(self):
        cases = [
            (b"<html>not json</html>", "malformed_json"),
            ([], "malformed_property"),
            ({"path": "/different", "value": 1}, "property_path_mismatch"),
            ({"path": "/sensor", "type": "-"}, "missing_value"),
            ({"path": "/sensor", "value": None}, "missing_value"),
            ({"path": "/sensor", "value": "NaN"}, "invalid_value"),
            ({"path": "/sensor", "value": "Infinity"}, "invalid_value"),
            ({"path": "/sensor", "value": True}, "invalid_value"),
            ({"path": "/sensor", "value": "broken"}, "invalid_value"),
            ({"path": "/sensor", "value": 1, "ts": "NaN"}, "invalid_timestamp"),
        ]
        for body, error in cases:
            with self.subTest(error=error, body=body):
                self.responses["/json/sensor"] = (200, body, 0)
                reading = self.client.read_property("/sensor")
                self.assertFalse(reading.valid)
                self.assertIsNone(reading.value)
                self.assertEqual(reading.error, error)

    def test_bool_and_text_are_explicit_types(self):
        self.node("/paused", True)
        self.node("/aircraft", "A320")
        self.assertIs(self.client.read_property("/paused", "bool").value, True)
        self.assertEqual(self.client.read_property("/aircraft", "string").value, "A320")
        self.assertFalse(self.client.read_property("/aircraft", "number").valid)
        self.node("/paused", "false")
        self.assertIs(self.client.read_property("/paused", "bool").value, False)

    def test_timeout_and_connection_refusal_are_not_healthy_telemetry(self):
        self.responses["/json/slow"] = (200, {"path": "/slow", "value": 1}, 0.3)
        reading = self.client.read_property("/slow")
        self.assertFalse(reading.valid)
        self.assertEqual(reading.error, "timeout")
        with socket.socket() as unused:
            unused.bind(("127.0.0.1", 0))
            closed_port = unused.getsockname()[1]
        disconnected = FlightGearClient(port=closed_port, timeout_s=0.1).poll({
            "sensor": PropertySpec("/sensor")
        })
        self.assertFalse(disconnected.connected)
        self.assertFalse(disconnected.complete)
        # Windows may take longer than this short timeout to reject a closed port.
        self.assertIn(disconnected.readings["sensor"].error, ("connection_error", "timeout"))

    def test_non_atomic_poll_preserves_each_simulator_timestamp(self):
        self.node("/one", 1, timestamp=1)
        self.node("/two", 2, timestamp=2)
        snapshot = self.client.poll({"one": PropertySpec("/one"), "two": PropertySpec("/two")})
        self.assertEqual(snapshot.readings["one"].sim_time_s, 1)
        self.assertEqual(snapshot.readings["two"].sim_time_s, 2)

    def test_response_size_limit_and_http_error(self):
        self.responses["/json/large"] = (200, b"x" * 300, 0)
        small_client = FlightGearClient(port=self.server.server_port, max_response_bytes=128)
        self.assertEqual(small_client.read_property("/large").error, "response_too_large")
        self.responses["/json/failing"] = (503, {}, 0)
        self.assertEqual(self.client.read_property("/failing").error, "http_503")

    def test_poll_concurrency_is_bounded_and_result_order_is_stable(self):
        channels = {f"channel_{index}": PropertySpec(f"/sensor-{index}") for index in range(6)}
        for index in range(6):
            self.responses[f"/json/sensor-{index}"] = (
                200, {"path": f"/sensor-{index}", "value": index, "ts": index}, 0.04
            )
        for workers in (1, 2):
            with self.subTest(workers=workers):
                type(self).peak_requests = 0
                client = FlightGearClient(port=self.server.server_port, max_workers=workers)
                snapshot = client.poll(channels)
                self.assertTrue(snapshot.complete)
                self.assertEqual(list(snapshot.readings), list(channels))
                self.assertEqual(type(self).peak_requests, workers)
                self.assertEqual(
                    [reading.sim_time_s for reading in snapshot.readings.values()],
                    list(range(6)),
                )
        self.responses.pop("/json/sensor-2")
        partial = client.poll(channels)
        self.assertFalse(partial.complete)
        self.assertIsNone(partial.readings["channel_2"].value)
        self.assertEqual(partial.readings["channel_2"].error, "missing_property")

    def test_local_only_configuration_and_safe_property_path(self):
        for host in ("example.com", "192.168.1.1", "0.0.0.0"):
            with self.assertRaises(ValueError):
                FlightGearClient(host=host)
        for path in ("relative", "/sensor?other=value", "/../sensor", "/bad\npath"):
            with self.assertRaises(ValueError):
                self.client.read_property(path)
        with self.assertRaises(ValueError):
            self.client.poll({})
        for workers in (0, 9, True, 1.5):
            with self.assertRaises(ValueError):
                FlightGearClient(max_workers=workers)


if __name__ == "__main__":
    unittest.main()
