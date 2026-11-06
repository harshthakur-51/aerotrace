"""Live session parity and fail-visible integration checks; fixtures are not aircraft trials."""
import copy
from pathlib import Path
import time
import unittest
from unittest.mock import Mock, patch

from aircraft_debugger.airborne_profile import iter_profile_observations
from aircraft_debugger.diagnosis import analyze_diagnosis
from aircraft_debugger.diagnostic_features import build_feature_frames
from aircraft_debugger.diagnostic_session import DiagnosisSession, SessionLimitReached
from aircraft_debugger.hypotheses import evaluate_hypotheses, pressure_supply_model
from aircraft_debugger.observations import CHANNELS
from aircraft_debugger.sim_panel import PanelState
from test_diagnosis import sample, trace

ROOT = Path(__file__).resolve().parents[1]

def legacy(row):
    result=copy.deepcopy(row)
    result.pop('observation_profile',None)
    result['schema_version']=1
    result['readings']={key:value for key,value in result['readings'].items() if key in CHANNELS}
    return result

def live_snapshot(row):
    result=legacy(row)
    for key in ('schema_version','sample_index','poll_started_monotonic_s'):
        result.pop(key)
    now=time.monotonic()
    result['received_monotonic_s']=now
    for reading in result['readings'].values():
        reading['received_monotonic_s']=now
    return result

class SessionTests(unittest.TestCase):
    def test_every_archived_prefix_matches_offline_features_and_hypotheses(self):
        inputs=['airborne-pairs-20261029-01/grouped-recipe','airborne-pairs-20261029-01/matched-independent',
                'airborne-contrast-20261028-01','airborne-contrast-20261029-01',
                'cross-system-20261026-01/episode-001', 'pressure-pair-20261106-01/pair']
        # Determine actual matched directory without guessing a simulator path.
        pair_root=ROOT/'results/airborne-pairs-20261029-01'
        inputs[1]=str(next(p.parent.relative_to(ROOT/'results') for p in pair_root.glob('*/observations.jsonl') if p.parent.name!='grouped-recipe'))
        for name in inputs:
            rows=list(iter_profile_observations(ROOT/'results'/name/'observations.jsonl'))
            frames=build_feature_frames(rows)['frames']
            model = pressure_supply_model() if name == 'pressure-pair-20261106-01/pair' else None
            for temporal in (True,False):
                session=DiagnosisSession(temporal=temporal, model=model)
                for row,frame in zip(rows,frames):
                    with self.subTest(input=name,index=row['sample_index'],temporal=temporal):
                        result=session.advance(row)
                        self.assertEqual(result['result'],evaluate_hypotheses(frame,temporal=temporal,model=model))
                        self.assertEqual(result['evidence'],frame['facts'])
                        self.assertEqual(result['current_impact'],frame['current_impact'])
                        self.assertEqual(result['observed_impact'],frame['observed_impact'])
                        self.assertEqual(result['current_quality'], frame['current_quality'])
                        self.assertEqual(result['temporal_relations'], frame['temporal_relations'])

    def test_missing_paused_reset_and_later_incident_match_core(self):
        rows=trace(recovered=True)
        rows.extend([sample(9,missing=('blue_quantity',)),sample(10,paused=True),
                     sample(11,sim_time=10),sample(12,sim_time=11),sample(13,sim_time=12,pressure=1000)])
        session=DiagnosisSession()
        for row in rows:
            current=session.advance(row)
        expected=analyze_diagnosis(rows)
        self.assertEqual(current['result'],expected['diagnosis'])
        self.assertEqual(current['result']['status'],'poor_model_fit')
        self.assertEqual(current['evidence']['blue_inventory_loss']['state'],'not_observed')

    def test_invalid_input_does_not_advance_or_poison_reference(self):
        session=DiagnosisSession()
        session.advance(sample(0))
        invalid_context = sample(1)
        invalid_context['readings']['height_agl']['value'] = 'invalid'
        for bad in (sample(0),{**sample(1),'fault':True},legacy(sample(1)),invalid_context):
            with self.assertRaises(ValueError):session.advance(bad)
        self.assertEqual(session.count,1)
        result=session.advance(sample(1))
        self.assertEqual(result['result']['status'],'no_selected_anomaly')

    def test_limit_never_drops_history_or_resets_silently(self):
        session=DiagnosisSession(max_records=2)
        session.advance(sample(0));session.advance(sample(1))
        with self.assertRaises(SessionLimitReached):session.advance(sample(2))
        self.assertEqual(session.count,2)
        for limit in (0,1201,True,1.5):
            with self.assertRaises(ValueError):DiagnosisSession(max_records=limit)

    def test_pure_session_and_defensive_input_output(self):
        row=sample(0);session=DiagnosisSession()
        with patch('socket.socket',side_effect=AssertionError('network')),patch('builtins.open',side_effect=AssertionError('file')):
            result=session.advance(row)
            row['readings']['blue_quantity']['value']=0
            result['model']['edges'].clear()
            result['timeline'].clear()
            result=session.advance(sample(1))
        self.assertEqual(result['result']['status'],'no_selected_anomaly')
        self.assertEqual(len(result['model']['edges']),4)
        self.assertEqual(len(result['timeline']),2)

class LivePanelTests(unittest.TestCase):
    def make_panel(self,rows,**kwargs):
        client=Mock()
        iterator=iter(rows)
        def poll(_channels):
            row=next(iterator)
            if isinstance(row,Exception):raise row
            return Mock(to_dict=lambda:live_snapshot(row))
        client.poll.side_effect=poll
        return PanelState(client,**kwargs),client

    def test_live_poll_caches_same_diagnosis_and_keeps_commands_private(self):
        rows=trace(recovered=True)
        panel,client=self.make_panel(rows)
        panel._operator_commands={'blue_leak':{'enabled':True}}
        for _ in rows:panel.poll_once()
        state=panel.get_state()
        expected=analyze_diagnosis([legacy(row) for row in rows])
        self.assertEqual(state['diagnosis']['result'],expected['diagnosis'])
        self.assertEqual(state['diagnosis']['current_impact'],[])
        self.assertTrue(state['diagnosis']['observed_impact'])
        self.assertEqual(state['diagnosis']['session']['record_count'],len(rows))
        for _ in range(3):panel.get_state()
        self.assertEqual(client.poll.call_count,len(rows))
        client.read_property.assert_not_called()

    def test_whole_poll_failure_removes_verdict_and_prevents_false_continuity(self):
        rows=[sample(0),sample(1),sample(2,generator=0),OSError(),sample(4,generator=0)]
        panel,_=self.make_panel(rows)
        for _ in range(3):panel.poll_once()
        panel.poll_once()
        state=panel.get_state()
        self.assertIsNone(state['telemetry'])
        self.assertEqual(state['diagnosis']['availability'],'unavailable')
        self.assertNotIn('result',state['diagnosis'])
        panel.poll_once();state=panel.get_state()
        self.assertEqual(state['diagnosis']['availability'],'ready')
        self.assertEqual(state['diagnosis']['evidence']['generator_source_anomaly']['state'],'unknown')
        self.assertEqual(state['diagnosis']['session']['record_count'],5)

    def test_stale_cached_snapshot_is_explicit(self):
        panel,_=self.make_panel([sample(0),sample(1)])
        panel.poll_once();panel.poll_once()
        now=time.monotonic()
        with patch('aircraft_debugger.sim_panel.time.monotonic',return_value=now+5):
            state=panel.get_state()
        self.assertTrue(state['diagnosis']['wall_clock_stale'])
        self.assertGreater(state['oldest_reading_age_s'],2)

    def test_inference_error_stops_without_replacing_valid_telemetry(self):
        panel,_=self.make_panel([sample(0),sample(1)])
        with patch.object(panel._diagnostic_session,'advance',side_effect=RuntimeError('fixture')):
            panel.poll_once()
        state=panel.get_state()
        self.assertIsNotNone(state['telemetry'])
        self.assertEqual(state['diagnosis']['availability'],'error')
        panel.poll_once()
        self.assertEqual(panel.get_state()['diagnosis']['availability'],'error')
        self.assertEqual(panel._diagnostic_session.count,0)

    def test_live_limit_preserves_telemetry_without_obsolete_verdict(self):
        panel,client=self.make_panel([sample(0),sample(1),sample(2)],diagnosis_limit=2)
        for _ in range(3):panel.poll_once()
        state=panel.get_state()
        self.assertIsNotNone(state['telemetry'])
        self.assertEqual(state['diagnosis']['availability'],'limit_reached')
        self.assertNotIn('result',state['diagnosis'])
        self.assertEqual(panel._diagnostic_session.count,2)
        self.assertEqual(client.poll.call_count,3)


class LiveRecordingTests(unittest.TestCase):
    def folder(self):
        import tempfile
        Path('work/tests').mkdir(parents=True,exist_ok=True)
        temp=tempfile.TemporaryDirectory(dir='work/tests');self.addCleanup(temp.cleanup)
        return Path(temp.name)

    def test_recording_uses_public_schema_and_continues_beyond_inference_limit(self):
        from aircraft_debugger.observations import iter_observations
        path=self.folder()/'observations.jsonl'
        panel,client=LivePanelTests.make_panel(self,[sample(0),sample(1),sample(2)],diagnosis_limit=2,recording=path)
        self.addCleanup(panel.stop)
        panel._operator_commands={'private-fault':{'enabled':True}}
        for _ in range(3):panel.poll_once()
        for _ in range(3):panel.get_state()
        rows=list(iter_observations(path))
        self.assertEqual(len(rows),3)
        self.assertEqual(client.poll.call_count,3)
        self.assertEqual(panel.get_state()['diagnosis']['availability'],'limit_reached')
        self.assertEqual(panel.get_state()['recording']['samples_written'],3)
        self.assertTrue(all(set(row['readings'])==set(CHANNELS) for row in rows))
        self.assertNotIn('private-fault',path.read_text(encoding='utf-8'))
        panel.stop()
        self.assertEqual(panel.get_state()['recording']['status'],'closed')

    def test_failed_poll_is_saved_as_invalid_cycle_not_an_omitted_gap(self):
        from aircraft_debugger.observations import iter_observations
        path=self.folder()/'observations.jsonl'
        panel,_=LivePanelTests.make_panel(self,[sample(0),OSError(),sample(2)],recording=path)
        self.addCleanup(panel.stop)
        for _ in range(3):panel.poll_once()
        rows=list(iter_observations(path))
        self.assertEqual([row['sample_index'] for row in rows],[0,1,2])
        self.assertFalse(rows[1]['connected'])
        self.assertTrue(all(not r['valid'] for r in rows[1]['readings'].values()))
        self.assertEqual(panel.get_state()['diagnosis']['result'],analyze_diagnosis(rows)['diagnosis'])

    def test_existing_recording_is_never_overwritten(self):
        path=self.folder()/'existing.jsonl';path.write_text('sentinel',encoding='utf-8')
        with self.assertRaises(FileExistsError):PanelState(Mock(),recording=path)
        self.assertEqual(path.read_text(encoding='utf-8'),'sentinel')

    def test_recording_io_failure_is_visible_and_does_not_stop_inference(self):
        path=self.folder()/'observations.jsonl'
        panel,_=LivePanelTests.make_panel(self,[sample(0),sample(1)],recording=path)
        self.addCleanup(panel.stop)
        original=panel._recording_stream
        panel._recording_stream=Mock()
        panel._recording_stream.write.side_effect=OSError('disk fixture')
        panel.poll_once();panel.poll_once()
        original.close()
        state=panel.get_state()
        self.assertEqual(state['recording']['status'],'failed')
        self.assertEqual(state['diagnosis']['result']['status'],'no_selected_anomaly')


class ObservationPanelTests(unittest.TestCase):
    def test_public_stream_pure_parity_and_cache(self):
        from aircraft_debugger.sim_panel import ObservationPanelState
        panel=ObservationPanelState()
        rows=trace(recovered=True)
        with patch('builtins.open',side_effect=AssertionError('file')),patch('socket.socket',side_effect=AssertionError('network')):
            for row in rows:panel.accept(row)
            state=panel.get_state()
        self.assertEqual(state['diagnosis']['result'],analyze_diagnosis(rows)['diagnosis'])
        self.assertEqual(state['operator_commands'],{})
        self.assertTrue(state['read_only'])
        for name in ('start','poll_once'):
            with self.assertRaises(RuntimeError):getattr(panel,name)()
        self.assertEqual(panel.command({'fault':'blue_leak','enabled':True})[0],409)

    def test_invalid_stream_and_limit_are_visible_without_held_values(self):
        from aircraft_debugger.sim_panel import ObservationPanelState
        panel=ObservationPanelState(diagnosis_limit=2)
        panel.accept(sample(0))
        bad=sample(1);bad['operator_command']='private'
        with self.assertRaises(ValueError):panel.accept(bad)
        self.assertIsNone(panel.get_state()['telemetry'])
        self.assertNotIn('result',panel.get_state()['diagnosis'])
        panel.accept(sample(1))
        with self.assertRaises(SessionLimitReached):panel.accept(sample(2))
        self.assertIsNone(panel.get_state()['telemetry'])
        self.assertEqual(panel._diagnostic_session.count,2)
