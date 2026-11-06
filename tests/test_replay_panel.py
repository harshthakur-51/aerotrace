import copy
import http.client
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from aircraft_debugger.airborne_profile import iter_profile_observations
from aircraft_debugger.diagnosis import analyze_diagnosis
from aircraft_debugger.replay_panel import ReplayPanelState
from aircraft_debugger.sim_panel import make_server

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / 'results/airborne-pairs-20261029-01/grouped-recipe/observations.jsonl'

class ReplayPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = list(iter_profile_observations(INPUT))
        cls.panel = ReplayPanelState(cls.records)

    def test_seek_is_prefix_only_and_matches_core_engine(self):
        for position in (0, 19, 50, 79):
            with self.subTest(position=position):
                self.panel.seek({'position': position})
                state = self.panel.get_state()
                expected = analyze_diagnosis(self.records[:position + 1])
                self.assertEqual(state['diagnosis']['result'], expected['diagnosis'])
                self.assertEqual(state['diagnosis']['evidence'], expected['evidence'])
                self.assertEqual(len(state['diagnosis']['timeline']), position + 1)
                self.assertEqual(state['telemetry'], self.records[position])
        self.assertEqual(state['diagnosis']['result']['candidate_ids'], ['independent_pair', 'grouped_joint_event'])
        self.assertEqual(state['diagnosis']['current_impact'], [])
        self.assertTrue(state['diagnosis']['observed_impact'])

    def test_past_frame_is_unchanged_by_future_mutations(self):
        changed = copy.deepcopy(self.records)
        for row in changed[30:]:
            row['readings']['blue_pressure']['value'] = 3000
        panel = ReplayPanelState(changed)
        self.panel.seek({'position': 25})
        panel.seek({'position': 25})
        self.assertEqual(panel.get_state()['diagnosis'], self.panel.get_state()['diagnosis'])

    def test_cached_seek_no_io_no_simulator_and_defensive_copies(self):
        self.panel.seek({'position': 50})
        with patch('socket.socket', side_effect=AssertionError('network')), patch('builtins.open', side_effect=AssertionError('file')):
            state = self.panel.get_state()
            state['diagnosis']['result']['candidate_ids'].clear()
            self.assertTrue(self.panel.get_state()['diagnosis']['result']['candidate_ids'])
            self.assertEqual(self.panel.command({'fault':'blue_leak','enabled':True})[0],409)
            self.panel.seek({'position': 0})

    def test_invalid_positions_and_private_fields_rejected(self):
        for payload in ({'position':-1},{'position':80},{'position':True},{'position':1.5},{'position':0,'fault':'blue_leak'},{}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.panel.seek(payload)
        contaminated = copy.deepcopy(self.records[:1])
        contaminated[0]['fault'] = 'blue_leak'
        with self.assertRaises(ValueError):
            ReplayPanelState(contaminated)

    def test_schema_one_and_atemporal_reuse_same_model(self):
        records = list(iter_profile_observations(ROOT/'results/cross-system-20261026-01/episode-001/observations.jsonl'))
        panel = ReplayPanelState(records, temporal=False)
        panel.seek({'position':len(records)-1})
        self.assertEqual(panel.get_state()['diagnosis']['result'], analyze_diagnosis(records,temporal=False)['diagnosis'])
        self.assertEqual(panel.get_state()['diagnosis']['model'], self.panel.get_state()['diagnosis']['model'])

    def test_http_seek_requires_token_and_control_is_read_only(self):
        server = make_server(self.panel, 0)
        thread = threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        origin = f'http://127.0.0.1:{server.server_port}'
        def request(path, body, token=None):
            client = http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=2)
            headers = {'Origin':origin,'Content-Type':'application/json'}
            if token: headers['X-Panel-Token']=token
            client.request('POST',path,json.dumps(body),headers)
            response=client.getresponse()
            status=response.status
            response.read()
            client.close()
            return status
        try:
            self.assertEqual(request('/api/replay',{'position':10}),403)
            self.assertEqual(request('/api/replay',{'position':10},self.panel.token),200)
            self.assertEqual(self.panel.get_state()['replay']['position'],10)
            self.assertEqual(request('/api/replay',{'position':True},self.panel.token),400)
            self.assertEqual(request('/api/control',{'fault':'blue_leak','enabled':True},self.panel.token),409)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
