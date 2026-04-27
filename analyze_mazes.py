import os
import glob
import re
import numpy as np

def get_newest_files(pattern, n=3):
    files = glob.glob(pattern)
    files.sort(key=os.path.getmtime, reverse=True)
    return files[:n]

def parse_telemetry(filename):
    file_size = os.path.getsize(filename)
    read_size = 500000 
    with open(filename, 'rb') as f:
        if file_size > read_size:
            f.seek(file_size - read_size)
        chunk = f.read().decode('utf-8', errors='ignore')

    def get_last_val(key):
        # findall on a 500KB string should be very fast
        m = re.findall(rf'(?:"{key}"|{key})\s*[:=]\s*([\d\.-]+)', chunk)
        return float(m[-1]) if m else 0.0

    metrics = ['telemetry_autonomy_score', 'telemetry_reasoning_trust_deliberative', 'telemetry_guard_utility_ema']
    means = {}
    for k in metrics:
        vals = [float(x) for x in re.findall(rf'{k}\s*[:=]\s*([\d\.-]+)', chunk)]
        means[k] = np.mean(vals) if vals else 0.0

    results = {
        'drift': 1 if get_last_val("promotion_target") > get_last_val("base_promotion_target") else 0,
        'completed_phase': int(get_last_val("completed_phase_count")),
        'completed_micro': int(get_last_val("completed_micro_total")),
        'learned_only_rate': get_last_val('learned_only_rate'),
        'hardcoded_only_rate': get_last_val('hardcoded_only_rate'),
        'mixed_rate': get_last_val('mixed_rate'),
        'phase1_intervention_utility_win3': get_last_val('phase1_intervention_utility_win3'),
        'projection_effectiveness_score': get_last_val('projection_effectiveness_score'),
        'status': 'pass' if 'gate_status=pass' in chunk else 'fail'
    }
    for k in metrics:
        results[f"{k}_mean"] = means[k]
    return results

def process_group(files):
    return [{'file': os.path.basename(f), **parse_telemetry(f)} for f in files]

hard_files = get_newest_files("Log Dump/15_mazes_hard_*.txt")
vhard_files = get_newest_files("Log Dump/15_mazes_very_hard_*.txt")
hard_data = process_group(hard_files)
vhard_data = process_group(vhard_files)

print("FILE LISTS:")
print(f"HARD: {', '.join([os.path.basename(f) for f in hard_files])}")
print(f"VHARD: {', '.join([os.path.basename(f) for f in vhard_files])}")

print("\nHARD PER-FILE ROWS (Status, LRN, HRD, Util, Proj, Aut, Trst, Grd, Drt, Ph/Mic):")
for r in hard_data:
    print(f"{r['file']:30} | {r['status']:4} | {r['learned_only_rate']:.3f} | {r['hardcoded_only_rate']:.3f} | {r['phase1_intervention_utility_win3']:.3f} | {r['projection_effectiveness_score']:.3f} | {r['telemetry_autonomy_score_mean']:.3f} | {r['telemetry_reasoning_trust_deliberative_mean']:.3f} | {r['telemetry_guard_utility_ema_mean']:.3f} | {r['drift']} | {r['completed_phase']}/{r['completed_micro']}")

def get_means(dataset):
    keys = ['learned_only_rate', 'hardcoded_only_rate', 'mixed_rate', 'phase1_intervention_utility_win3', 'projection_effectiveness_score', 'telemetry_autonomy_score_mean', 'telemetry_reasoning_trust_deliberative_mean', 'telemetry_guard_utility_ema_mean']
    return {k: np.mean([r[k] for r in dataset]) if dataset else 0.0 for k in keys}

h_means = get_means(hard_data)
vh_means = get_means(vhard_data)
h_status = {'PASS': sum(1 for r in hard_data if r['status'] == 'pass'), 'FAIL': sum(1 for r in hard_data if r['status'] == 'fail')}
h_drift = sum(r['drift'] for r in hard_data)

print("\nHARD GROUP SUMMARY:")
print(f"Means: {', '.join([f'{k}: {v:.3f}' for k,v in h_means.items()])}")
print(f"Status: {h_status} | TotDrift: {h_drift}")

print("\nDELTA (HARD - VHARD):")
for k in h_means:
    print(f"{k:35}: {h_means[k] - vh_means[k]:+.3f}")

print("\nINTERPRETATION:")
# Interpretation based on metrics
aut, trst, util, proj = h_means['telemetry_autonomy_score_mean'], h_means['telemetry_reasoning_trust_deliberative_mean'], h_means['phase1_intervention_utility_win3'], h_means['projection_effectiveness_score']
bullets = [
    f"- Module autonomy at {aut:.3f} indicates {'high' if aut > 0.7 else 'moderate' if aut > 0.4 else 'low'} agent independence.",
    f"- Reasoning trust (deliberative) mean {trst:.3f} suggests {'strong' if trst > 0.6 else 'nominal' if trst > 0.3 else 'weak'} alignment.",
    f"- Intervention utility win-rate is {util:.3f}; values > 0.5 suggest effective human/guard corrections.",
    f"- Projection effectiveness ({proj:.3f}) shows {'strong' if proj > 0.5 else 'limited'} foresight benefits.",
    f"- Drift flag count {h_drift}/3 suggests {'stable' if h_drift == 0 else 'shifting'} model thresholds.",
    f"- {h_status.get('PASS', 0)}/3 files passed preflight gate standards."
]
if h_means['learned_only_rate'] > h_means['hardcoded_only_rate']:
    bullets.append("- Model relies more on learned policy than hardcoded fallbacks.")
else:
    bullets.append("- Safety fallbacks (hardcoded) remain primary over learned policy.")
for b in bullets:
    print(b)
