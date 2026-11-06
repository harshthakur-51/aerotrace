"""Sealed profile scoring checks. Synthetic targets are software fixtures, not final trials."""
import copy
from contextlib import redirect_stdout,redirect_stderr
import hashlib,io,json
from pathlib import Path
import tempfile,unittest
from unittest.mock import patch

from aircraft_debugger.diagnosis import analyze_diagnosis,main as predict_main
from aircraft_debugger.evaluation import make_protocol,score_prediction,canonical_observation_hash,main
from aircraft_debugger.hypotheses import pressure_supply_model
from test_diagnosis import sample,trace

class EvaluationTests(unittest.TestCase):
    def fixture(self,rows=None):
        rows=trace(recovered=True) if rows is None else rows
        raw=hashlib.sha256(json.dumps(rows).encode()).hexdigest();canonical=canonical_observation_hash(rows)
        sources={'module.py':'a'*64}
        protocol=make_protocol([{'run_id':'dev-1','flight_group':'flight-dev','observation_sha256':raw,'canonical_observations_sha256':canonical}],sources,'b'*64,[{'run_id':'new','flight_group':'new-declared-flight','profile':'joint_selected_effects'}])
        report=analyze_diagnosis(rows);report['input_provenance']['observation_file_sha256']=raw
        provenance={'source_sha256':sources,'observation_file_sha256':raw,'verified_canonical_observations_sha256':canonical}
        target={'schema_version':1,'run_id':'dev-1','flight_group':'flight-dev','observation_sha256':raw,'canonical_observations_sha256':canonical,'profile':'joint_selected_effects','data_role':'development'}
        return report,provenance,target,protocol

    def test_joint_target_requires_both_equivalent_histories(self):
        report,provenance,target,protocol=self.fixture()
        result=score_prediction(report,provenance,target,protocol)
        self.assertTrue(result['exact_bounded_profile_match'])
        self.assertEqual(len(result['expected_compatible_ids']),2)
        self.assertFalse(result['physical_cause_accuracy_measured'])
        self.assertFalse(result['independent_trials_claimed'])
        report['diagnosis']['candidate_ids']=['grouped_joint_event']
        self.assertFalse(score_prediction(report,provenance,target,protocol)['exact_bounded_profile_match'])

    def test_wrong_bounded_set_is_mismatch_not_silent_success(self):
        report,provenance,target,protocol=self.fixture()
        target['profile']='source_path'
        value=score_prediction(report,provenance,target,protocol)
        self.assertEqual(value['assessment'],'bounded_profile_mismatch')
        self.assertTrue(value['extra_compatible_ids'])
        self.assertTrue(value['expected_ids_not_compatible'])

    def test_missing_data_retained_without_a_forced_match(self):
        values=self.fixture([sample(0),sample(1,missing=('blue_quantity',))])
        value=score_prediction(*values)
        self.assertEqual(value['assessment'],'insufficient_observations')
        self.assertIsNone(value['exact_bounded_profile_match'])

    def test_raw_reuse_and_reencoded_public_data_cannot_be_final(self):
        report,provenance,target,protocol=self.fixture();target['data_role']='final'
        for reencoded in (False,True):
            with self.subTest(reencoded=reencoded):
                if reencoded:
                    target['run_id']='renamed';target['flight_group']='new-flight'
                    target['observation_sha256']='c'*64
                    provenance['observation_file_sha256']='c'*64
                    report['input_provenance']['observation_file_sha256']='c'*64
                with self.assertRaisesRegex(ValueError,'Known development'):score_prediction(report,provenance,target,protocol)

    def test_whole_flight_group_cannot_cross_split_even_with_new_rows(self):
        report,provenance,target,protocol=self.fixture();target.update(data_role='final',run_id='new',observation_sha256='c'*64,canonical_observations_sha256='d'*64)
        provenance.update(observation_file_sha256='c'*64,verified_canonical_observations_sha256='d'*64)
        report['input_provenance']['observation_file_sha256']='c'*64
        with self.assertRaisesRegex(ValueError,'flight group'):score_prediction(report,provenance,target,protocol)
        target['flight_group']='new-declared-flight'
        result=score_prediction(report,provenance,target,protocol)
        self.assertFalse(result['independent_trials_claimed'])

    def test_source_model_protocol_and_input_drift_are_refused(self):
        for kind in ('source','model','protocol','input','physical_claim'):
            report,provenance,target,protocol=self.fixture()
            if kind=='source':provenance['source_sha256']={'module.py':'e'*64}
            if kind=='model':report['model']['edges'].clear()
            if kind=='protocol':protocol['detector_thresholds']['blue_quantity_drop_raw']=99
            if kind=='input':provenance['observation_file_sha256']='e'*64
            if kind=='physical_claim':report['diagnosis']['cause_identifiable']=True
            with self.subTest(kind=kind),self.assertRaises(ValueError):score_prediction(report,provenance,target,protocol)

    def test_private_physical_initiator_labels_are_outside_target_contract(self):
        report,provenance,target,protocol=self.fixture();target['physical_cause']='uncontained_engine'
        with self.assertRaises(ValueError):score_prediction(report,provenance,target,protocol)

    def test_pure_scoring_does_not_invoke_inference_or_external_access(self):
        values=self.fixture()
        with patch('builtins.open',side_effect=AssertionError('file')),patch('socket.socket',side_effect=AssertionError('network')),patch('aircraft_debugger.diagnosis.analyze_diagnosis',side_effect=AssertionError('inference')):
            score_prediction(*values)

    def test_protocol_and_target_are_not_mutated(self):
        values=self.fixture();before=copy.deepcopy(values)
        score_prediction(*values)
        self.assertEqual(values,before)

    def test_cli_seal_then_predict_then_score_and_detect_artifact_tampering(self):
        Path('work/tests').mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir='work/tests') as folder:
            root=Path(folder);source=root/'observations.jsonl';registry=root/'registry.json';protocol=root/'protocol';prediction=root/'prediction';target=root/'target.json';score=root/'score.json'
            rows=trace(recovered=True);source.write_text(''.join(json.dumps(row)+'\n' for row in rows),encoding='utf-8')
            registry.write_text(json.dumps([{'run_id':'dev','flight_group':'declared-flight','observations':str(source)}]),encoding='utf-8')
            with patch('sys.argv',['eval','seal','--development-runs',str(registry),'--output',str(protocol)]),redirect_stdout(io.StringIO()):main()
            self.assertFalse(target.exists())
            with patch('sys.argv',['predict','--observations',str(source),'--output',str(prediction)]),redirect_stdout(io.StringIO()):predict_main()
            target.write_text(json.dumps({'schema_version':1,'run_id':'dev','flight_group':'declared-flight','observation_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'canonical_observations_sha256':canonical_observation_hash(rows),'profile':'joint_selected_effects','data_role':'development'}),encoding='utf-8')
            args=['eval','score','--protocol',str(protocol),'--prediction',str(prediction),'--observations',str(source),'--target',str(target),'--output',str(score)]
            with patch('sys.argv',args),redirect_stdout(io.StringIO()):main()
            self.assertEqual(json.loads(score.read_text(encoding='utf-8'))['assessment'],'matched_bounded_profile')
            original_report=(prediction/'report.json').read_bytes()
            (prediction/'report.json').write_text('{}',encoding='utf-8')
            args[-1]=str(root/'tampered-score.json')
            with patch('sys.argv',args),redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):main()
            self.assertFalse((root/'tampered-score.json').exists())
            (prediction/'report.json').write_bytes(original_report)
            archived=prediction/'executed-source/aircraft_debugger/hypotheses.py'
            archived.write_text('# modified source',encoding='utf-8')
            args[-1]=str(root/'tampered-source-score.json')
            with patch('sys.argv',args),redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):main()
            self.assertFalse((root/'tampered-source-score.json').exists())

    def test_final_profile_assignment_cannot_be_chosen_after_results(self):
        report,provenance,target,protocol=self.fixture()
        target.update(data_role='final',run_id='new',flight_group='new-declared-flight',observation_sha256='c'*64,canonical_observations_sha256='d'*64,profile='source_path')
        provenance.update(observation_file_sha256='c'*64,verified_canonical_observations_sha256='d'*64)
        report['input_provenance']['observation_file_sha256']='c'*64
        with self.assertRaisesRegex(ValueError,'before sealing'):score_prediction(report,provenance,target,protocol)

    def test_duplicate_canonical_development_data_cannot_inflate_registry(self):
        values=self.fixture();protocol=values[3]
        runs=copy.deepcopy(protocol['development_runs'])
        second={**runs[0],'run_id':'alias','observation_sha256':'e'*64}
        with self.assertRaises(ValueError):make_protocol(runs+[second],{'module.py':'a'*64},'b'*64)

    def test_v2_pressure_pair_requires_both_histories_and_the_sealed_method(self):
        rows = [sample(0), sample(1), sample(2, generator=0, pressure=1000),
                sample(3, generator=0, pressure=0), sample(4, generator=0, pressure=0)]
        _, provenance, target, v1 = self.fixture(rows)
        target["profile"] = "joint_pressure_effects"
        protocol = make_protocol(v1["development_runs"], provenance["source_sha256"], "b" * 64,
                                 model_version="v2")
        prediction = analyze_diagnosis(rows, model=pressure_supply_model())
        prediction["input_provenance"]["observation_file_sha256"] = target["observation_sha256"]
        value = score_prediction(prediction, provenance, target, protocol)
        self.assertTrue(value["exact_bounded_profile_match"])
        self.assertEqual(set(value["observed_compatible_ids"]),
                         {"independent_pressure_pair", "grouped_pressure_joint_event"})

        prediction["method"] = "dependency_compatibility"
        with self.assertRaisesRegex(ValueError, "Prediction method"):
            score_prediction(prediction, provenance, target, protocol)
        with self.assertRaisesRegex(ValueError, "target contract"):
            score_prediction(prediction, provenance, target, v1)
