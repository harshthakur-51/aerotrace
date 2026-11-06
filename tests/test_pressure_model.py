"""Pressure-supply extension specifications; fixtures are not aircraft trials."""
import copy
from pathlib import Path
import unittest

from aircraft_debugger.airborne_profile import iter_profile_observations
from aircraft_debugger.diagnosis import analyze_diagnosis
from aircraft_debugger.diagnostic_session import DiagnosisSession
from aircraft_debugger.hypotheses import default_model,pressure_supply_model
from aircraft_debugger.replay_panel import ReplayPanelState
from test_diagnosis import sample,trace,ROOT

class PressureModelTests(unittest.TestCase):
    def pressure_trace(self,generator=False):
        return [sample(0),sample(1),sample(2,pressure=1000,generator=0 if generator else 115),sample(3,pressure=0,generator=0 if generator else 115)]

    def test_explicit_extension_leaves_v1_default_and_same_fact_contract(self):
        v1=default_model();v2=pressure_supply_model()
        self.assertEqual(len(v1['roots']),2);self.assertEqual(len(v2['roots']),3)
        self.assertEqual(len(v1['candidates']),5);self.assertEqual(len(v2['candidates']),8)
        self.assertEqual(v1['facts'],v2['facts'])
        v2['edges'].clear();self.assertEqual(len(pressure_supply_model()['edges']),5)

    def test_retained_quantity_pressure_loss_is_new_candidate_not_leak(self):
        rows=self.pressure_trace()
        self.assertEqual(analyze_diagnosis(rows)['diagnosis']['status'],'poor_model_fit')
        v2=analyze_diagnosis(rows,model=pressure_supply_model())
        self.assertEqual(v2['diagnosis']['candidate_ids'],['blue_pressure_supply_loss'])
        self.assertFalse(v2['diagnosis']['cause_identifiable'])
        self.assertEqual(v2['evidence']['blue_inventory_loss']['state'],'not_observed')
        self.assertTrue(v2['observed_impact'])

    def test_inventory_loss_distinguishes_depletion_from_supply_only(self):
        result=analyze_diagnosis(trace('blue'),model=pressure_supply_model())
        self.assertEqual(result['diagnosis']['candidate_ids'],['blue_inventory_loss'])
        supply=next(c for c in result['diagnosis']['candidates'] if c['id']=='blue_pressure_supply_loss')
        self.assertTrue(supply['contradicting_evidence'])

    def test_source_plus_pressure_pair_retains_its_own_equivalent_histories(self):
        value=analyze_diagnosis(self.pressure_trace(True),model=pressure_supply_model())['diagnosis']
        self.assertEqual(set(value['candidate_ids']),{'independent_pressure_pair','grouped_pressure_joint_event'})
        self.assertTrue(value['ambiguity']['equivalent_joint_histories'])
        self.assertTrue(any(not x.get('available_discriminator',True) for x in value['missing_evidence']))
        for candidate in value['candidates']:
            if candidate['id'] in value['candidate_ids']:
                self.assertTrue(any(x.get('available_discriminator') is False for x in candidate['missing_evidence']))

    def test_missing_quantity_preserves_supply_vs_inventory_uncertainty(self):
        rows=self.pressure_trace()
        for row in rows:row['readings'].pop('blue_quantity');row['complete']=False
        value=analyze_diagnosis(rows,model=pressure_supply_model())['diagnosis']
        self.assertEqual(value['status'],'insufficient_observations')
        self.assertIn('blue_inventory_loss',value['plausible_candidate_ids'])
        self.assertIn('blue_pressure_supply_loss',value['plausible_candidate_ids'])

    def test_graph_edge_drives_new_prediction(self):
        model=pressure_supply_model()
        model['edges']=[e for e in model['edges'] if e['from']!='blue_pressure_supply_loss']
        value=analyze_diagnosis(self.pressure_trace(),model=model)['diagnosis']
        self.assertEqual(value['status'],'poor_model_fit')

    def test_new_model_session_and_replay_match_offline(self):
        rows=self.pressure_trace(True);model=pressure_supply_model();session=DiagnosisSession(model=model)
        for row in rows:value=session.advance(row)
        expected=analyze_diagnosis(rows,model=model)['diagnosis']
        self.assertEqual(value['result'],expected)
        panel=ReplayPanelState(rows,model=model);panel.seek({'position':3})
        self.assertEqual(panel.get_state()['diagnosis']['result'],expected)

    def test_existing_native_development_cases_keep_their_candidate_sets(self):
        for relative in ['airborne-contrast-20261028-01/observations.jsonl','airborne-contrast-20261029-01/observations.jsonl','airborne-pairs-20261029-01/grouped-recipe/observations.jsonl','cross-system-20261026-01/episode-001/observations.jsonl']:
            rows=list(iter_profile_observations(ROOT/'results'/relative))
            v1=analyze_diagnosis(rows);v2=analyze_diagnosis(rows,model=pressure_supply_model())
            self.assertEqual(v1['diagnosis']['candidate_ids'],v2['diagnosis']['candidate_ids'])
            self.assertEqual(v1['evidence'],v2['evidence'])
