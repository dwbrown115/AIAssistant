import glob
import os
import re
import numpy as np

def get_newest_files(pattern, n=3):
    files = glob.glob(pattern)
    files.sort(key=os.path.getmtime, reverse=True)
    return files[:n]

def extract_metric(text, name):
    # Limit search to the last 4000 chars of the text to prevent hangs on huge files
    tail = text[-4000:]
    patterns = [
        rf'"{name}"\s*[:=]\s*([\d\.-]+)',
        rf'{name}\s*[:=]\s*([\d\.-]+)'
    ]
    for p in patterns:
        m = re.findall(p, tail)
        if m:
            return float(m[-1])
    return 0.0

def check_drift(text):
    tail = text[-8000:]
    prom_targets = re.findall(r'promotion_target[:= ]*([\d\.]+)', tail)
    base_targets = re.findall(r'base_promotion_target[:= ]*([\d\.]+)', tail)
    if prom_targets and base_targets:
        max_prom = max(float(x) for x in prom_targets)
        latest_base = float(base_targets[-1])
        return max_prom > latest_base
    return False

def quick_status(text):
    tail = text[-2000:]
    if "FAIL" in tail: return "FAIL"
    if "WARN" in tail: return "WARN"
    return "PASS"

def process_file(fpath):
    print(f"Processing {fpath}...")
    with open(fpath, 'r') as f:
        text = f.read()
    
    data = {
        'fname': os.path.basename(fpath),
        'status': quick_status(text),
        'fail': text[-10000:].count("FAIL"),
        'warn': text[-10000:].count("WARN"),
        'lor': extract_metric(text, 'learned_only_rate'),
        'hor': extract_metric(text, 'hardcoded_only_rate'),
        'mixed': extract_metric(text, 'mixed_rate'),
        'util': extract_metric(text, 'phase1_intervention_utility_win3'),
        'proj': extract_metric(text, 'projection_effectiveness_score'),
        'auto': extract_metric(text, 'telemetry_autonomy_score'),
        'trust_delib': extract_metric(text, 'telemetry_reasoning_trust_deliberative'),
        'guard_util': extract_metric(text, 'telemetry_guard_utility_ema'),
        'drift': check_drift(text),
        'count': int(extract_metric(text, 'completed_phase_count')),
        'micro': int(extract_metric(text, 'completed_micro_total'))
    }
    return data

hard_files = get_newest_files("Log Dump/15_mazes_hard_*.txt", 3)
vhard_files = get_newest_files("Log Dump/15_mazes_very_hard_*.txt", 3)

print("HARD FILES:")
for f in hard_files:
    print(f"- {os.path.basename(f)}")

hard_data = [process_file(f) for f in hard_files]
vhard_data = [process_file(f) for f in vhard_files]

header = f"{'Filename':30} | {'S':1} | {'W':2} | {'F':2} | {'LOR':7} | {'HOR':7} | {'Util':7} | {'Proj':7} | {'Auto':7} | {'TrstD':7} | {'GUtil':7} | {'D':1} | {'Phs':3} | {'Mic':5}"
print("\n" + header)
print("-" * len(header))

for d in hard_data:
    print(f"{d['fname'][:30]:30} | {d['status'][0]} | {d['warn']:2} | {d['fail']:2} | {d['lor']:.4f} | {d['hor']:.4f} | {d['util']:.4f} | {d['proj']:.4f} | {d['auto']:.4f} | {d['trust_delib']:.4f} | {d['guard_util']:.4f} | {'Y' if d['drift'] else 'N'} | {d['count']:3} | {d['micro']:5}")

def get_means(dataset):
    keys = ['lor', 'hor', 'mixed', 'util', 'proj', 'auto', 'trust_delib', 'guard_util']
    return {k: np.mean([d[k] for d in dataset]) if dataset else 0.0 for k in keys}

hard_means = get_means(hard_data)
vhard_means = get_means(vhard_data)

status_counts = {}
for d in hard_data:
    status_counts[d['status']] = status_counts.get(d['status'], 0) + 1

print("\nHARD GROUP MEANS & STATUS:")
for k, v in hard_means.items():
    print(f"{k:12}: {v:.4f}")
print(f"Statuses: {status_counts}")

print("\nDELTA (HARD MEAN - VERY HARD MEAN):")
for k in ['lor', 'hor', 'mixed', 'util', 'proj', 'auto', 'trust_delib', 'guard_util']:
    print(f"{k:12}: {hard_means[k] - vhard_means[k]:.4f}")
