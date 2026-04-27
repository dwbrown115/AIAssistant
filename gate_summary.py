import glob
import os
import re
from preflight_dump_gate import parse_dump

def get_newest_files(pattern, n=3):
    files = glob.glob(pattern)
    files.sort(key=os.path.getmtime, reverse=True)
    return files[:n]

files = get_newest_files("Log Dump/15_mazes_hard_*.txt", 3)
print(f"{'Filename':40} | {'Status':6} | {'Fail':4} | {'Warn':4} | {'LRN':5} | {'HRD':5} | {'Util':5} | {'Proj':5}")
print("-" * 103)

for fpath in files:
    with open(fpath, 'r') as f:
        text = f.read()
    
    res = parse_dump(text, profile='batch4')
    
    # Try to find common metrics in the result structure
    metrics = res.get('metrics', {})
    
    def get_metric(name):
        # 1. Try metrics dict from parse_dump
        if name in metrics: return metrics[name]
        # 2. Try regex search in text
        m = re.findall(rf'"{name}"\s*[:=]\s*([\d\.]+)', text)
        if m: return float(m[-1])
        m = re.findall(rf'{name}\s*[:=]\s*([\d\.]+)', text)
        if m: return float(m[-1])
        return 0.0

    fname = os.path.basename(fpath)
    status = res.get('status', 'N/A')
    fail_count = len(res.get('failures', []))
    warn_count = len(res.get('warnings', []))
    
    lrn = get_metric('learned_only_rate')
    hrd = get_metric('hardcoded_only_rate')
    util = get_metric('phase1_intervention_utility_win3')
    proj = get_metric('projection_effectiveness_score')
    
    print(f"{fname:40} | {status:6} | {fail_count:4} | {warn_count:4} | {lrn:.3f} | {hrd:.3f} | {util:.3f} | {proj:.3f}")
