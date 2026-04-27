import re
import os
import glob
from collections import defaultdict

def parse_file_metrics(file_path):
    metrics = {
        'autonomy': [], 'trust_delib': [], 'guard_utility': [],
        'max_promotion': 0.0, 'base_promotion': 0.0, 'completed_phase': 0, 'completed_micro': 0
    }
    
    # Regexes
    re_autonomy = re.compile(r'telemetry_autonomy_score[:= ]*([0-9.]+)')
    re_trust_delib = re.compile(r'telemetry_reasoning_trust_deliberative[:= ]*([0-9.]+)')
    re_guard_utility = re.compile(r'telemetry_guard_utility_ema[:= ]*([0-9.]+)')
    re_prom = re.compile(r'promotion_target[:= ]*([0-9.]+)')
    re_base_prom = re.compile(r'base_promotion_target[:= ]*([0-9.]+)')
    re_phase = re.compile(r'completed_phase_count[:= ]*([0-9]+)')
    re_micro = re.compile(r'completed_micro_total[:= ]*([0-9]+)')

    if not os.path.exists(file_path):
        return metrics

    with open(file_path, 'r') as f:
        # For large files, only read last 5000 lines if possible, or stream
        for line in f:
            m = re_autonomy.search(line)
            if m: metrics['autonomy'].append(float(m.group(1)))
            m = re_trust_delib.search(line)
            if m: metrics['trust_delib'].append(float(m.group(1)))
            m = re_guard_utility.search(line)
            if m: metrics['guard_utility'].append(float(m.group(1)))
            m = re_prom.search(line)
            if m: metrics['max_promotion'] = max(metrics['max_promotion'], float(m.group(1)))
            m = re_base_prom.search(line)
            if m: metrics['base_promotion'] = float(m.group(1))
            m = re_phase.search(line)
            if m: metrics['completed_phase'] = int(m.group(1))
            m = re_micro.search(line)
            if m: metrics['completed_micro'] = int(m.group(1))
            
    return metrics

def get_summary(file_path):
    stream = parse_file_metrics(file_path)
    res = {
        'file': os.path.basename(file_path),
        'status': 'PASS' if stream['completed_phase'] > 0 else 'FAIL',
        'autonomy_mean': sum(stream['autonomy'])/len(stream['autonomy']) if stream['autonomy'] else 0,
        'trust_delib_mean': sum(stream['trust_delib'])/len(stream['trust_delib']) if stream['trust_delib'] else 0,
        'guard_utility_mean': sum(stream['guard_utility'])/len(stream['guard_utility']) if stream['guard_utility'] else 0,
        'drift': stream['max_promotion'] > (stream['base_promotion'] + 0.0001) if stream['base_promotion'] > 0 else False,
        'phase': stream['completed_phase'],
        'micro': stream['completed_micro']
    }
    return res

def calc_group_means(summaries):
    if not summaries: return {}
    keys = ['autonomy_mean', 'trust_delib_mean', 'guard_utility_mean']
    means = {k: sum(s[k] for s in summaries)/len(summaries) for k in keys}
    means['status_counts'] = defaultdict(int)
    means['drift_count'] = 0
    for s in summaries:
        means['status_counts'][s['status']] += 1
        if s['drift']: means['drift_count'] += 1
    return means

hard_files = sorted(glob.glob("Log Dump/15_mazes_hard_*.txt"), key=os.path.getmtime, reverse=True)[:3]
very_hard_files = sorted(glob.glob("Log Dump/15_mazes_very_hard_*.txt"), key=os.path.getmtime, reverse=True)[:3]

print("--- FILE LISTS ---")
print(f"HARD: {[os.path.basename(f) for f in hard_files]}")
print(f"VERY HARD: {[os.path.basename(f) for f in very_hard_files]}")

hard_sums = [get_summary(f) for f in hard_files]
vh_sums = [get_summary(f) for f in very_hard_files]

h_means = calc_group_means(hard_sums)
vh_means = calc_group_means(vh_sums)

print("\n--- HARD FILE ROWS ---")
print(f"{'File':<35} | {'Stat':<4} | {'Auton':<6} | {'TrDel':<6} | {'GUtil':<6} | {'D':<1} | {'Ph/Mi'}")
for s in hard_sums:
    print(f"{s['file'][:35]:<35} | {s['status'][:4]:<4} | {s['autonomy_mean']:.4f} | {s['trust_delib_mean']:.4f} | {s['guard_utility_mean']:.4f} | {'Y' if s['drift'] else 'N'} | {s['phase']}/{s['micro']}")

print("\n--- HARD GROUP SUMMARY ---")
if h_means:
    print(f"Means: Auton:{h_means['autonomy_mean']:.4f}, TrDel:{h_means['trust_delib_mean']:.4f}, GUtil:{h_means['guard_utility_mean']:.4f}")
    print(f"Stats: {dict(h_means['status_counts'])} | Drifts:{h_means['drift_count']}")

if h_means and vh_means:
    print("\n--- DELTA (HARD - VERY_HARD) ---")
    for k in ['autonomy_mean', 'trust_delib_mean', 'guard_utility_mean']:
        print(f"{k:<30}: {h_means[k] - vh_means[k]:.4f}")

print("\n--- INTERPRETATION ---")
if h_means and vh_means:
    aut_diff = h_means['autonomy_mean'] - vh_means['autonomy_mean']
    print(f"1. Autonomy mean difference: {aut_diff:.4f}.")
    print(f"2. Drift count in HARD: {h_means['drift_count']}.")
    print(f"3. Guard utility EMA (HARD): {h_means['guard_utility_mean']:.4f}.")
    print(f"4. Trust Deliberative (HARD): {h_means['trust_delib_mean']:.4f}.")
    print(f"5. HARD success rate: {h_means['status_counts']['PASS']/len(hard_sums) if hard_sums else 0:.2f}.")
    print(f"6. VERY_HARD success rate: {vh_means['status_counts']['PASS']/len(vh_sums) if vh_sums else 0:.2f}.")
