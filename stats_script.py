import os
import glob
import json
import re
import subprocess

def get_stats(file_path):
    autonomy, trust, guard = [], [], []
    last_phase, last_micro = 0, 0
    max_promotion, last_base_promotion = 0, 0
    
    with open(file_path, 'r') as f:
        for line in f:
            if 'telemetry_autonomy_score' in line:
                m = re.search(r'telemetry_autonomy_score[:= ]*([-+]?\d*\.?\d+)', line)
                if m: autonomy.append(float(m.group(1)))
            if 'telemetry_reasoning_trust_deliberative' in line:
                m = re.search(r'telemetry_reasoning_trust_deliberative[:= ]*([-+]?\d*\.?\d+)', line)
                if m: trust.append(float(m.group(1)))
            if 'telemetry_guard_utility_ema' in line:
                m = re.search(r'telemetry_guard_utility_ema[:= ]*([-+]?\d*\.?\d+)', line)
                if m: guard.append(float(m.group(1)))
            if 'completed_phase_count' in line:
                m = re.search(r'completed_phase_count[:= ]*(\d+)', line)
                if m: last_phase = int(m.group(1))
            if 'completed_micro_total' in line:
                m = re.search(r'completed_micro_total[:= ]*(\d+)', line)
                if m: last_micro = int(m.group(1))
            if 'promotion_target' in line:
                m = re.search(r'promotion_target[:= ]*([-+]?\d*\.?\d+)', line)
                if m: max_promotion = max(max_promotion, float(m.group(1)))
            if 'base_promotion_target' in line:
                m = re.search(r'base_promotion_target[:= ]*([-+]?\d*\.?\d+)', line)
                if m: last_base_promotion = float(m.group(1))

    # Preflight
    status, warn, fail = "ERR", 0, 0
    try:
        res = subprocess.run(['python3', 'preflight_dump_gate.py', file_path, '--json'], 
                            capture_output=True, text=True, timeout=60)
        if res.returncode == 0:
            data = json.loads(res.stdout)
            status = data.get('status', 'UNK')
            warn = data.get('warning_count', 0)
            fail = data.get('failure_count', 0)
        else:
            status = f"E{res.returncode}"
    except subprocess.TimeoutExpired:
        status = "TO"
    except Exception:
        status = "ERR"

    return {
        'file': os.path.basename(file_path),
        'autonomy': sum(autonomy)/len(autonomy) if autonomy else 0,
        'trust': sum(trust)/len(trust) if trust else 0,
        'guard': sum(guard)/len(guard) if guard else 0,
        'phase': last_phase,
        'micro': last_micro,
        'drift': 1 if max_promotion > last_base_promotion else 0,
        'status': status, 'warn': warn, 'fail': fail
    }

hard_files = sorted(glob.glob("Log Dump/15_mazes_hard_*.txt"), key=os.path.getmtime, reverse=True)[:3]
very_hard_files = sorted(glob.glob("Log Dump/15_mazes_very_hard_*.txt"), key=os.path.getmtime, reverse=True)[:3]

h_stats = [get_stats(f) for f in hard_files]
vh_stats = [get_stats(f) for f in very_hard_files]

print("HARD files:", [s['file'] for s in h_stats])
print("VERY_HARD files:", [s['file'] for s in vh_stats])
print("\nHARD Details:")
print(f"{'Status':<6} {'W':<2} {'F':<2} {'Auton':<8} {'Trust':<8} {'Guard':<8} {'Drift':<5} {'Ph':<4} {'Mi':<4}")
for s in h_stats:
    print(f"{s['status']:<6} {s['warn']:<2} {s['fail']:<2} {s['autonomy']:<8.4f} {s['trust']:<8.4f} {s['guard']:<8.4f} {s['drift']:<5} {s['phase']:<4} {s['micro']:<4}")

def mean(data, key):
    return sum(s[key] for s in data)/len(data) if data else 0

h_means = {k: mean(h_stats, k) for k in ['autonomy', 'trust', 'guard']}
vh_means = {k: mean(vh_stats, k) for k in ['autonomy', 'trust', 'guard']}

print("\nMeans (H | VH | Delta):")
for k in ['autonomy', 'trust', 'guard']:
    print(f"{k.capitalize():<8}: {h_means[k]:.4f} | {vh_means[k]:.4f} | {h_means[k]-vh_means[k]:.4f}")

h_statuses = [s['status'] for s in h_stats]
vh_statuses = [s['status'] for s in vh_stats]
print(f"\nStatus Counts: HARD { {x:h_statuses.count(x) for x in set(h_statuses)} } | VERY_HARD { {x:vh_statuses.count(x) for x in set(vh_statuses)} }")
print(f"Drift Counts: HARD {sum(s['drift'] for s in h_stats)} | VERY_HARD {sum(s['drift'] for s in vh_stats)}")
