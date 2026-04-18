import re
import os
import glob
import sys

def check_file(filepath):
    metrics = {}
    evidence = []
    completion = False
    
    try:
        with open(filepath, 'r') as f:
            for line in f:
                for field in ['telemetry_batch_progress', 'telemetry_batch_ramp', 'micro_index', 'batch_index', 'runtime_micro_series', 'success_criteria', 'step_mode_success', 'step_mode_completed_hits', 'execution_count']:
                    match = re.search(fr"{field}[:=]\s*([^ \t\n,}}]+)", line)
                    if match:
                        metrics[field] = match.group(1).strip()
                
                if any(x in line for x in ['Batch ', 'Micro ']):
                    evidence.append(line.strip())
    except: return None, False, []
            
    hits = metrics.get('step_mode_completed_hits')
    goal = metrics.get('success_criteria')
    sms = metrics.get('step_mode_success')
    try:
        if str(sms).lower() == 'true': completion = True
        elif hits and goal:
            goal_num = re.search(r"(\d+)", str(goal))
            if goal_num and int(hits) >= int(goal_num.group(1)): completion = True
    except: pass
    
    return metrics, completion, evidence[-5:] if evidence else []

hard_files = sorted(glob.glob('Log Dump/15_mazes_hard_*.txt'), reverse=True)
if hard_files:
    f = hard_files[0]
    m, c, e = check_file(f)
    if m:
        print(f"NEWEST HARD: {f}")
        print(f"Progress: {m.get('telemetry_batch_progress', 'N/A')}, Ramp: {m.get('telemetry_batch_ramp', 'N/A')}")
        print(f"Completion: {c}")
        print("Evidence:")
        for line in e: print(line)

print('---')

all_files = sorted(glob.glob('Log Dump/*.txt'), reverse=True)
found_comp = False
for f in all_files:
    m, c, e = check_file(f)
    if c:
        print(f"NEWEST COMPLETED: {f}")
        print(f"Progress: {m.get('telemetry_batch_progress', 'N/A')}, Ramp: {m.get('telemetry_batch_ramp', 'N/A')}")
        print(f"Completion: {c}")
        print("Evidence:")
        for line in e: print(line)
        found_comp = True
        break
if not found_comp: print("No completed run found.")
