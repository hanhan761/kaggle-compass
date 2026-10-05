"""Compass experiment decisions v0.2: transparent heuristics, not predicted score."""
import argparse,copy,hashlib,json,math,pathlib
VERSION='0.2.1'
def number(v,label,low=0,high=None):
 if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<low or (high is not None and v>high):raise ValueError('invalid '+label)
 return float(v)
def plan(problem):
 if problem.get('schema_version')!=1:raise ValueError('schema_version must be 1')
 demand=problem['demand'];axes=demand['axes'];groups=demand['groups']
 if len(set(axes))!=len(axes) or set(axes)!=set(groups):raise ValueError('demand axes mismatch')
 n=number(demand['n'],'n',1)
 if not n.is_integer() or any(not number(groups[g]['n'],'group n').is_integer() for g in axes):raise ValueError('population counts must be integers')
 baseline=number(demand['baseline_mrr'],'baseline_mrr',0,1)
 if sum(number(groups[g]['n'],'group n') for g in axes)!=n:raise ValueError('group denominator mismatch')
 headroom={g:number(groups[g]['n'],'n')/n*number(groups[g]['mean_loss'],'mean_loss',0,1) for g in axes}
 if abs(sum(headroom.values())-(1-baseline))>1e-7:raise ValueError('headroom differs from baseline loss')
 context=problem['context'];penalty=number(context.get('cost_penalty_mrr_per_hour',0),'penalty');budget=number(context['budget_hours'],'budget',0.001)
 max_value=number(context.get('max_actions',3),'max_actions',1,100)
 if not max_value.is_integer():raise ValueError('max_actions must be an integer')
 max_actions=int(max_value);actions=problem['actions'];byid={a['id']:a for a in actions}
 if len(byid)!=len(actions):raise ValueError('duplicate action IDs')
 if any(a.get('status') not in ('planned','running','succeeded','failed') for a in actions):raise ValueError('invalid action status')
 for a in actions:
  if not a.get('family_id') or not a.get('acceptance') or not a.get('stop'):raise ValueError('family, acceptance and stop required')
  if len(set(a['targets']))!=len(a['targets']) or any(g not in axes for g in a['targets']):raise ValueError('invalid targets')
  for dep in a.get('requires',[]):
   if dep not in byid:raise ValueError('missing prerequisite '+dep)
 visiting=set();visited=set()
 def walk(i):
  if i in visiting:raise ValueError('dependency cycle')
  if i in visited:return
  visiting.add(i)
  for dep in byid[i].get('requires',[]):walk(dep)
  visiting.remove(i);visited.add(i)
 for i in byid:walk(i)
 def complete(i):return byid[i]['status']=='succeeded' and byid[i].get('completion_verified') is True
 rows={}
 for a in actions:
  reasons=[];blocks=[i for i in a.get('requires',[]) if not complete(i)];cover=sum(headroom[g] for g in a['targets']);e=a.get('evidence');lower=upper=None;kind='exploration';proxy=cover
  if e is not None:
   for key in ('cohort_id','baseline_id','metric_id'):
    if e.get(key)!=demand.get(key):raise ValueError('incomparable evidence '+key)
   if e.get('axes')!=axes or e.get('n')!=n or set(e.get('groups',{}))!=set(axes):raise ValueError('incomparable evidence population or groups')
   if e.get('mode') not in ('standalone','fused'):raise ValueError('invalid evidence mode')
   if any(e['groups'][g]['n']!=groups[g]['n'] for g in axes):raise ValueError('evidence group denominators differ')
   if abs(number(e['baseline_mrr'],'evidence baseline',0,1)-baseline)>1e-7:raise ValueError('incomparable evidence baseline score')
   delta=number(e['delta_mrr'],'delta_mrr',-1,1)
   weighted=sum(groups[g]['n']/n*number(e['groups'][g]['delta_mrr'],'group delta',-1,1) for g in axes)
   if abs(weighted-delta)>1e-7:raise ValueError('evidence group delta inconsistency')
   if e.get('evaluation_role') not in ('development','calibration','historical_development'):raise ValueError('confirmation evidence cannot select next strategy')
   ci=e['ci95'];lower=ci.get('low');upper=ci.get('high')
   if lower is not None and upper is not None:
    lower=number(lower,'ci low',-1,1);upper=number(upper,'ci high',-1,1)
    if not lower<=delta<=upper:raise ValueError('invalid CI')
   else:lower=upper=None
   harm=number(e['top1_harm'],'harm',0,n);rescue=number(e['top1_rescue'],'rescue',0,n)
   if not harm.is_integer() or not rescue.is_integer():raise ValueError('rescue/harm counts must be integers')
   if harm>rescue:reasons.append('Top1 harm exceeds rescue; prioritize diagnosis over integration')
   if e.get('mode')=='fused' and e.get('ranking_replay_verified') is True and lower is not None and lower>0 and harm<=rescue:
    kind='measured_positive';proxy=lower
   else:
    kind='exploration';proxy=min(cover,max(0,upper)) if upper is not None else cover
    reasons.append('Standalone, uncertain, unreplayed or harmful evidence cannot justify adoption')
   if upper is not None and upper<=0:kind='defer_negative';proxy=0;reasons.append('No positive upper-bound benefit in this batch')
  if context.get('validation_status')!='trusted':
   if kind=='measured_positive':kind='exploration';proxy=min(cover,max(0,upper));reasons.append('Validation transfer uncertain; historical gain is only a hypothesis')
  cost=a.get('cost');hours=None
  if cost is None:blocks.append('unknown_cost');reasons.append('Estimate bounded development/compute cost before budget allocation')
  else:
   hours=number(cost['upper_hours'],'upper_hours',0.001)
   if cost.get('basis') not in ('measured','planning_estimate'):raise ValueError('cost basis required')
   if cost['basis']=='planning_estimate':reasons.append('Cost is a declared planning estimate, not measured runtime')
  if a.get('kind')=='integration' and kind!='measured_positive':blocks.append('missing_reliable_fusion_evidence');reasons.append('Integration deferred until replayed positive paired evidence is available')
  if a.get('ancestry_verified') is not True and a.get('kind')=='integration':blocks.append('ancestry_review');reasons.append('Integration needs ancestry review to avoid duplicate evidence')
  if a['status']!='planned':blocks.append('status:'+a['status'])
  score=None if hours is None else (max(0,proxy-penalty*hours)/hours)
  rows[a['id']]={'id':a['id'],'name':a['name'],'family_id':a['family_id'],'kind':a.get('kind'),'evidence_class':kind,'headroom_mrr':cover,'measured_ci_low':lower,'measured_ci_high':upper,'priority_proxy':score,'cost_upper_hours':hours,'cost_basis':cost.get('basis') if cost else None,'blocks':blocks,'reasons':reasons,'requires':a.get('requires',[]),'acceptance':a['acceptance'],'stop':a['stop'],'source_refs':a.get('source_refs',[]),'unlocks':[]}
 # Prerequisite value is maximum reachable downstream priority, never sum of correlated gains.
 def descendants(i):
  reached=set();todo=[i]
  while todo:
   parent=todo.pop()
   for a in actions:
    if parent in a.get('requires',[]) and a['id'] not in reached:reached.add(a['id']);todo.append(a['id'])
  return reached
 for a in actions:
  row=rows[a['id']]
  if a.get('kind')=='prerequisite':
   downstream=[rows[i] for i in descendants(a['id']) if byid[i]['status']=='planned' and rows[i]['evidence_class']!='defer_negative' and rows[i]['priority_proxy'] is not None and rows[i]['priority_proxy']>0]
   row['unlocks']=sorted(r['id'] for r in downstream)
   value=max([r['headroom_mrr'] for r in downstream] or [0])
   if row['cost_upper_hours'] is not None:row['priority_proxy']=max(row['priority_proxy'],max(0,value-penalty*row['cost_upper_hours'])/row['cost_upper_hours'])
   row['reasons'].append('Enabling priority uses maximum downstream loss coverage, not summed predicted gains')
 ready=[r for r in rows.values() if not r['blocks'] and r['priority_proxy'] is not None and r['priority_proxy']>0 and r['evidence_class']!='defer_negative']
 ready.sort(key=lambda r:(0 if r['evidence_class']=='measured_positive' else 1,-r['priority_proxy'],r['id']))
 measured=[r for r in ready if r['evidence_class']=='measured_positive'];explore=[r for r in ready if r['evidence_class']!='measured_positive']
 reserve=min(max_actions-1,1) if measured and explore else 0
 order=measured[:max_actions-reserve]+explore+measured[max_actions-reserve:]
 selected=[];used=set();remaining=budget
 for r in order:
  if len(selected)>=max_actions:break
  if r['family_id'] in used:r['reasons'].append('Same family already scheduled');continue
  if r['cost_upper_hours']>remaining:r['reasons'].append('Exceeds remaining declared budget');continue
  selected.append(r['id']);used.add(r['family_id']);remaining-=r['cost_upper_hours']
 return {'tool_version':VERSION,'kind':'experiment_decision','problem_id':problem['problem_id'],'next_action':rows[selected[0]] if selected else None,'selected_actions':selected,'budget_hours':budget,'reserved_hours':budget-remaining,'ranked_ready':ready,'all_actions':list(rows.values()),'interpretation':'priority_proxy is loss-coverage or observed-benefit per declared cost; not expected Kaggle score or a statistical VOI estimate','adoption_authorized':False,'execution_authorized_by_plan':False,'warnings':['Demand is cohort-specific; historical proxy gains do not guarantee hidden-test gains.','Unmeasured capability remains null; code similarity is not gain evidence.','Completed actions require verified completion; failed tasks are not automatically retried.']}
def sensitivity(problem):
 baseline=plan(problem);first=baseline['next_action']['id'] if baseline['next_action'] else None;trials=[]
 for i,a in enumerate(problem['actions']):
  if a.get('cost') is None or a['status']!='planned':continue
  for multiplier in (.5,2):
   altered=copy.deepcopy(problem);altered['actions'][i]['cost']['upper_hours']*=multiplier;d=plan(altered)
   trials.append({'changed_action':a['id'],'cost_multiplier':multiplier,'next_action':d['next_action']['id'] if d['next_action'] else None})
 return {'baseline_next_action':first,'one_cost_at_a_time_trials':trials,'same_next_action_fraction':sum(t['next_action']==first for t in trials)/len(trials) if trials else None,'interpretation':'planning-cost sensitivity, not probability of success or a confidence interval'}

def main():
 p=argparse.ArgumentParser();p.add_argument('--input',type=pathlib.Path,required=True);p.add_argument('--out',type=pathlib.Path,required=True);a=p.parse_args()
 try:
  if a.out.exists():raise ValueError('output already exists; preserve prior decision')
  raw=a.input.read_bytes();problem=json.loads(raw);result=plan(problem);result['cost_sensitivity']=sensitivity(problem);result['input_sha256']=hashlib.sha256(raw).hexdigest();result['planner_sha256']=hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest();a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'next_action':result['next_action']['id'] if result['next_action'] else None,'selected':result['selected_actions']}))
 except (KeyError,ValueError,TypeError,OSError) as e:p.error(str(e))
if __name__=='__main__':main()
