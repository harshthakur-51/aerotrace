"""Panel tests use a local protocol fixture, never a real aircraft install."""

import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import unittest
from urllib.parse import unquote, urlsplit

from aircraft_debugger.flightgear import FlightGearClient
from aircraft_debugger.sim_panel import CHANNELS, FAULT_PATHS, PanelState, make_server, validate_command


class SimPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nodes = {}
        cls.requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                path = unquote(urlsplit(self.path).path).removeprefix("/json")
                cls.requests.append(("GET", path, None))
                if path not in cls.nodes:
                    status, body = 404, {}
                else:
                    status, body = 200, {"path": path, "value": cls.nodes[path], "ts": 15.0}
                body = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                path = unquote(urlsplit(self.path).path).removeprefix("/json")
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                cls.requests.append(("POST", path, body))
                if path in cls.nodes:
                    cls.nodes[path] = body["value"]
                    self.send_response(200)
                else:
                    self.send_response(404)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *_args):
                pass

        cls.simulator = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.sim_thread = threading.Thread(target=cls.simulator.serve_forever, daemon=True)
        cls.sim_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.simulator.shutdown()
        cls.simulator.server_close()
        cls.sim_thread.join(timeout=2)

    def setUp(self):
        self.requests.clear()
        self.nodes.clear()
        for spec in CHANNELS.values():
            self.nodes[spec.path] = False if spec.kind == "bool" else 42
        self.nodes["/sim/aircraft"] = "A320-200-CFM"
        for path in FAULT_PATHS.values():
            self.nodes[path] = False
        self.panel = PanelState(FlightGearClient(port=self.simulator.server_port, timeout_s=0.2))

    def test_cached_reads_do_not_poll_and_observations_exclude_fault_flags(self):
        self.panel.poll_once()
        calls = len(self.requests)
        for _ in range(4):
            snapshot = self.panel.get_state()
        self.assertEqual(len(self.requests), calls)
        self.assertTrue(snapshot["telemetry"]["complete"])
        paths = {r["path"] for r in snapshot["telemetry"]["readings"].values()}
        self.assertFalse(paths.intersection(FAULT_PATHS.values()))
        self.assertEqual(snapshot["operator_commands"], {})
        self.assertTrue(snapshot["diagnosis"]["implemented"])
        self.assertEqual(snapshot["diagnosis"]["availability"], "ready")

    def test_missing_channel_replaces_previous_value(self):
        self.panel.poll_once()
        self.nodes.pop(CHANNELS["blue_pressure"].path)
        self.panel.poll_once()
        snapshot = self.panel.get_state()["telemetry"]
        self.assertFalse(snapshot["complete"])
        self.assertIsNone(snapshot["readings"]["blue_pressure"]["value"])
        self.assertEqual(snapshot["readings"]["blue_pressure"]["error"], "missing_property")

    def test_command_rejects_nonboolean_extra_fields_and_unknown_paths(self):
        for payload in [None, {}, {"fault": "generator_2", "enabled": 1},
                        {"fault": "/arbitrary/property", "enabled": True},
                        {"fault": "blue_leak", "enabled": True, "path": "/other"}]:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                validate_command(payload)
        self.assertEqual(self.requests, [])

    def test_command_requires_supported_aircraft_and_existing_flag(self):
        self.nodes["/sim/aircraft"] = "c172p"
        status, _ = self.panel.command({"fault": "blue_leak", "enabled": True})
        self.assertEqual(status, 409)
        self.nodes["/sim/aircraft"] = "A320-200-CFM"
        del self.nodes[FAULT_PATHS["blue_leak"]]
        status, _ = self.panel.command({"fault": "blue_leak", "enabled": True})
        self.assertEqual(status, 409)
        self.assertFalse(any(method == "POST" for method, _, _ in self.requests))

    def test_native_bool_write_is_verified_and_kept_outside_observations(self):
        for flag in (True, False):
            status, body = self.panel.command({"fault": "blue_leak", "enabled": flag})
            self.assertEqual(status, 200)
            self.assertTrue(body["ok"])
            self.assertIs(self.nodes[FAULT_PATHS["blue_leak"]], flag)
        writes = [(path, body) for method, path, body in self.requests if method == "POST"]
        self.assertEqual(writes, [(FAULT_PATHS["blue_leak"], {"value": True}),
                                  (FAULT_PATHS["blue_leak"], {"value": False})])
        self.panel.poll_once()
        state = self.panel.get_state()
        self.assertIs(state["operator_commands"]["blue_leak"]["enabled"], False)
        self.assertNotIn("blue_leak", state["telemetry"]["readings"])

    def test_http_requires_same_origin_token_and_does_not_expose_it_in_state(self):
        server = make_server(self.panel, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{server.server_port}"

        def request(method, path, body=None, headers=None):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
            connection.request(method, path, body, headers or {})
            response = connection.getresponse()
            result = response.status, response.read(), response.getheaders()
            connection.close()
            return result

        try:
            status, body, _ = request("GET", "/api/state")
            self.assertEqual(status, 200)
            self.assertNotIn(self.panel.token.encode(), body)
            payload = json.dumps({"fault": "generator_2", "enabled": True})
            base = {"Origin": origin, "Content-Type": "application/json"}
            # Repeated denials must deliver a complete response on Windows too;
            # rejecting before consuming this body can cause a TCP reset there.
            for _ in range(12):
                status, rejected_body, _ = request("POST", "/api/control", payload, base)
                self.assertEqual(status, 403)
                self.assertIn("error", json.loads(rejected_body))
            headers = {**base, "X-Panel-Token": self.panel.token, "Origin": "https://example.com"}
            self.assertEqual(request("POST", "/api/control", payload, headers)[0], 403)
            self.assertEqual(self.requests, [])
            headers = {**base, "X-Panel-Token": self.panel.token}
            self.assertEqual(request("POST", "/api/control", payload, headers)[0], 200)
            status, body, response_headers = request("GET", "/")
            self.assertEqual(status, 200)
            self.assertIn(self.panel.token.encode(), body)
            self.assertIn("frame-ancestors 'none'", dict(response_headers)["Content-Security-Policy"])
            self.assertEqual(request("GET", "/", headers={"Host": "example.com"})[0], 403)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
