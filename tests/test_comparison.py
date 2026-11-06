"""Method comparison behavior checks, not validation-accuracy claims."""
import copy
from contextlib import redirect_stderr,redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aircraft_debugger.comparison import compare_methods,main
from aircraft_debugger.hypotheses import default_model
from test_diagnosis import sample,trace,ROOT

class ComparisonTests(unittest.TestCase):
    def test_same_facts_catalogue_and_explicit_alert_only_non_inference(self):
        rows=trace(recovered=True);original=copy.deepcopy(rows)
        result=compare_methods(iter(rows))
        self.assertEqual(rows,original)
        self.assertEqual(result['model'],default_model())
        self.assertEqual(result['summary']['temporal_changed_prefix_count'],0)
        self.assertFalse(result['summary']['accuracy_measured'])
        for point in result['timeline']:
            methods=point['methods']
            self.assertIsNone(methods['alert_only']['candidate_ids'])
            self.assertEqual(methods['alert_only']['cause_inference'],'not_performed')
            self.assertEqual(methods['dependency']['candidate_ids'],methods['temporal_dependency']['candidate_ids'])
        self.assertEqual(result['timeline'][-1]['shared_current_impact'],[])
        self.assertTrue(result['timeline'][-1]['shared_incident_impact'])

    def test_reversed_order_changes_temporal_model_fit_without_new_features(self):
        rows=[sample(0),sample(1),sample(2,pressure=1000),sample(3,pressure=1000),
              sample(4,pressure=1000,quantity=7.75),sample(5,pressure=500,quantity=7.2)]
        result=compare_methods(rows)
        final=result['timeline'][-1]
        self.assertEqual(final['methods']['dependency']['candidate_ids'],['blue_inventory_loss'])
        self.assertEqual(final['methods']['temporal_dependency']['status'],'poor_model_fit')
        self.assertEqual(final['shared_temporal_relations']['inventory_before_pressure']['status'],'contradicted')
        self.assertIn(5,result['summary']['temporal_changed_sample_indices'])
        self.assertEqual(final['methods']['alert_only']['observed_fact_ids'],['blue_inventory_loss','blue_pressure_loss'])

    def test_missing_data_is_not_a_wrong_definitive_or_healthy_assertion(self):
        rows=[sample(0),sample(1,missing=('blue_quantity',))]
        result=compare_methods(rows)
        methods=result['summary']['final_methods']
        for method in ('alert_only','dependency','temporal_dependency'):
            self.assertEqual(methods[method]['status'],'insufficient_observations')
        self.assertFalse(methods['dependency']['cause_identifiable'])

    def test_graph_changes_both_dependency_methods_but_not_alerts(self):
        model=default_model();model['edges'][1]['necessity']='required'
        original=compare_methods(trace('generator'))
        changed=compare_methods(trace('generator'),model=model)
        self.assertEqual(original['summary']['final_methods']['alert_only'],changed['summary']['final_methods']['alert_only'])
        for method in ('dependency','temporal_dependency'):
            self.assertEqual(changed['summary']['final_methods'][method]['status'],'poor_model_fit')

    def test_no_io_and_private_input_rejection(self):
        with patch('builtins.open',side_effect=AssertionError('file')),patch('socket.socket',side_effect=AssertionError('network')):
            compare_methods(trace())
        bad=trace();bad[0]['private_label']='grouped'
        with self.assertRaises(ValueError):compare_methods(bad)

    def test_cli_analyzes_whole_files_separately_and_preserves_hashes(self):
        Path('work/tests').mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir='work/tests') as folder:
            out=Path(folder)/'comparison'
            inputs=[ROOT/'results/airborne-contrast-20261028-01/observations.jsonl',
                    ROOT/'results/cross-system-20261026-01/episode-001/observations.jsonl']
            argv=['comparison','--observations',*map(str,inputs),'--output',str(out)]
            with patch('sys.argv',argv),redirect_stdout(io.StringIO()):main()
            report=json.loads((out/'comparison.json').read_text(encoding='utf-8'))
            self.assertEqual([case['report']['sample_count'] for case in report['cases']],[34,13])
            provenance=json.loads((out/'provenance.json').read_text(encoding='utf-8'))
            for entry,path in zip(provenance['inputs'],inputs):
                self.assertEqual(entry['sha256'],hashlib.sha256(path.read_bytes()).hexdigest())
            for name,digest in provenance['source_sha256'].items():
                self.assertEqual(digest,hashlib.sha256((out/'executed-source'/name).read_bytes()).hexdigest())
            with patch('sys.argv',argv),redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):main()

    def test_cli_rejects_private_contamination_before_creating_output(self):
        Path('work/tests').mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir='work/tests') as folder:
            source=Path(folder)/'bad.jsonl';out=Path(folder)/'out'
            row=sample(0);row['operator_command']='blue_leak'
            source.write_text(json.dumps(row)+'\n',encoding='utf-8')
            with patch('sys.argv',['comparison','--observations',str(source),'--output',str(out)]),redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):main()
            self.assertFalse(out.exists())

    def test_input_race_fails_before_any_output_is_created(self):
        from aircraft_debugger import comparison
        Path('work/tests').mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir='work/tests') as folder:
            source=Path(folder)/'observations.jsonl';out=Path(folder)/'out'
            source.write_text(''.join(json.dumps(row)+'\n' for row in trace()),encoding='utf-8')
            original=comparison.compare_methods
            def mutate(rows, *, model=None):
                result=original(rows, model=model)
                source.write_text('',encoding='utf-8')
                return result
            with patch.object(comparison,'compare_methods',side_effect=mutate),patch('sys.argv',['comparison','--model','v2','--observations',str(source),'--output',str(out)]),redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):main()
            self.assertFalse(out.exists())

    def test_duplicate_input_is_not_counted_as_another_run(self):
        source=ROOT/'results/airborne-contrast-20261028-01/observations.jsonl'
        with patch('sys.argv',['comparison','--observations',str(source),str(source),'--output','work/duplicate-comparison-should-not-exist']),redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):main()
        self.assertFalse(Path('work/duplicate-comparison-should-not-exist').exists())

    def test_analysis_role_is_metadata_and_does_not_change_any_method_result(self):
        Path('work/tests').mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir='work/tests') as folder:
            root=Path(folder);source=root/'observations.jsonl'
            source.write_text(''.join(json.dumps(row)+'\n' for row in trace()),encoding='utf-8')
            reports=[]
            for role in ('development','post_prediction_descriptive'):
                out=root/role
                with patch('sys.argv',['comparison','--observations',str(source),'--output',str(out),'--data-role',role]),redirect_stdout(io.StringIO()):main()
                value=json.loads((out/'comparison.json').read_text(encoding='utf-8'))
                self.assertEqual(value['declared_data_role'],role)
                reports.append(value['cases'])
            self.assertEqual(reports[0],reports[1])
