import os, glob, subprocess, json

def newest(pattern,n=3):
    return sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)[:n]

def get_json(path):
    p=subprocess.run(['python3','preflight_dump_gate.py',path,'--json'],capture_output=True,text=True)
    if p.returncode!=0:
        return None
    try:
        return json.loads(p.stdout)
    except:
        return None

def metrics(d):
    if not d: return {}
    b=d.get('metrics',{}).get('behavior_screen',{})
    p=d.get('metrics',{}).get('projection_screen',{})
    return {
      'learned_only_rate': b.get('learned_only_rate',0.0),
      'hardcoded_only_rate': b.get('hardcoded_only_rate',0.0),
      'mixed_rate': b.get('mixed_rate',0.0),
      'phase1_intervention_utility_win3': b.get('phase1_intervention_utility_win3',0.0),
      'projection_effectiveness_score': p.get('projection_effectiveness_score',0.0),
    }

def summarize(files):
    rows=[]
    for f in files:
        d=get_json(f)
        if not d: continue
        m=metrics(d)
        rows.append((f,d,m))
    if not rows: return [], {}, {}, 0, 0
    keys=list(rows[0][2].keys())
    means={k:sum(r[2][k] for r in rows)/len(rows) for k in keys}
    statuses={}
    warn=fail=0
    for _,d,_ in rows:
        s=d.get('status','?')
        statuses[s]=statuses.get(s,0)+1
        warn+=len(d.get('warnings',[]))
        fail+=len(d.get('failures',[]))
    return rows,means,statuses,warn,fail

hard=newest('Log Dump/15_mazes_hard_*.txt',3)
vhard=newest('Log Dump/15_mazes_very_hard_*.txt',3)
hr,hm,hs,hw,hf=summarize(hard)
vr,vm,vs,vw,vf=summarize(vhard)

print('HARD_STATUS',hs,'warn',hw,'fail',hf)
print('VERY_HARD_STATUS',vs,'warn',vw,'fail',vf)
print('HARD_MEAN_PREFLIGHT', {k:round(v,4) for k,v in hm.items()})
print('VERY_HARD_MEAN_PREFLIGHT', {k:round(v,4) for k,v in vm.items()})
if hm and vm:
    print('DELTA_HARD_MINUS_VERY_HARD_PREFLIGHT', {k:round(hm[k]-vm[k],4) for k in hm})
