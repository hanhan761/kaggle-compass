import copy,importlib.util,pathlib,unittest
P=pathlib.Path(__file__).resolve().parents[1]/'skills/kaggle-compass/scripts/decide.py';s=importlib.util.spec_from_file_location('decide',P);D=importlib.util.module_from_spec(s);s.loader.exec_module(D)
def action(i,**kw):
 a={'id':i,'name':i,'family_id':i,'kind':'experiment','targets':['error'],'status':'planned','requires':[],'cost':{'upper_hours':1,'basis':'planning_estimate'},'acceptance':'paired replayed improvement','stop':'no gain'};a.update(kw);return a
def problem():return {'schema_version':1,'problem_id':'synthetic-only','demand':{'axes':['correct','error'],'n':100,'baseline_mrr':.8,'cohort_id':'c','baseline_id':'b','metric_id':'mrr@25','groups':{'correct':{'n':80,'mean_loss':0},'error':{'n':20,'mean_loss':1}}},'context':{'budget_hours':3,'max_actions':3,'validation_status':'trusted'},'actions':[]}
def evidence(low=.01,high=.05,delta=.02):return {'axes':['correct','error'],'n':100,'cohort_id':'c','baseline_id':'b','metric_id':'mrr@25','baseline_mrr':.8,'delta_mrr':delta,'groups':{'correct':{'n':80,'delta_mrr':0},'error':{'n':20,'delta_mrr':delta*5}},'evaluation_role':'calibration','mode':'fused','ranking_replay_verified':True,'ci95':{'low':low,'high':high},'top1_harm':1,'top1_rescue':3}
class TestDecision(unittest.TestCase):
 def test_dependency_unblocks_without_recommending_blocked_run(self):
  p=problem();p['actions']=[action('repair',kind='prerequisite',targets=[]),action('train',requires=['repair'])];r=D.plan(p);self.assertEqual(r['next_action']['id'],'repair');self.assertNotIn('train',r['selected_actions'])
 def test_unknown_cost_never_free(self):
  p=problem();p['actions']=[action('unknown',cost=None),action('known')];self.assertEqual(D.plan(p)['selected_actions'],['known'])
 def test_negative_evidence_and_confirmation_selection(self):
  p=problem();p['actions']=[action('bad',evidence=evidence(-.05,-.01,-.02))];self.assertIsNone(D.plan(p)['next_action']);p['actions'][0]['evidence']['evaluation_role']='confirmation'
  with self.assertRaises(ValueError):D.plan(p)
 def test_standalone_and_replay_not_integration(self):
  p=problem();p['actions']=[action('fuse',kind='integration',ancestry_verified=True,evidence=evidence())];self.assertEqual(D.plan(p)['selected_actions'],['fuse'])
  p['actions'][0]['evidence']['mode']='standalone';self.assertIsNone(D.plan(p)['next_action'])
  p['actions'][0]['evidence']['mode']='fused';p['actions'][0]['evidence']['ranking_replay_verified']=False;self.assertIsNone(D.plan(p)['next_action'])
 def test_untrusted_validation_blocks_integration(self):
  p=problem();p['context']['validation_status']='untrusted';p['actions']=[action('fuse',kind='integration',ancestry_verified=True,evidence=evidence())];self.assertIsNone(D.plan(p)['next_action'])
 def test_budget_and_family_diversity(self):
  p=problem();p['context']['budget_hours']=1.5;p['actions']=[action('a',family_id='same'),action('b',family_id='same'),action('c')];self.assertEqual(D.plan(p)['selected_actions'],['a']);self.assertLessEqual(D.plan(p)['reserved_hours'],1.5)
 def test_mismatch_cycles_and_unverified_completion(self):
  p=problem();p['actions']=[action('a',requires=['b']),action('b',requires=['a'])]
  with self.assertRaises(ValueError):D.plan(p)
  p['actions']=[action('a',evidence=evidence())];p['actions'][0]['evidence']['cohort_id']='other'
  with self.assertRaises(ValueError):D.plan(p)
  p['actions']=[action('repair',status='succeeded'),action('run',requires=['repair'])];self.assertIsNone(D.plan(p)['next_action']);p['actions'][0]['completion_verified']=True;self.assertEqual(D.plan(p)['selected_actions'],['run'])
 def test_measured_evidence_not_outbid_by_unmeasured_headroom(self):
  p=problem();p['actions']=[action('known',evidence=evidence()),action('unknown')];r=D.plan(p);self.assertEqual(r['next_action']['id'],'known');self.assertIn('unknown',r['selected_actions'])
 def test_corrupt_counts_and_nonfinite_evidence(self):
  p=problem();p['actions']=[action('a',evidence=evidence())];p['actions'][0]['evidence']['baseline_mrr']=float('nan')
  with self.assertRaises(ValueError):D.plan(p)
  p['actions'][0]['evidence']=evidence();p['actions'][0]['evidence']['top1_harm']=101
  with self.assertRaises(ValueError):D.plan(p)
 def test_feedback_changes_next_action(self):
  p=problem();p['actions']=[action('a'),action('b')];self.assertEqual(D.plan(p)['next_action']['id'],'a');p['actions'][0]['evidence']=evidence(-.05,-.01,-.02);self.assertEqual(D.plan(p)['next_action']['id'],'b')
if __name__=='__main__':unittest.main()
