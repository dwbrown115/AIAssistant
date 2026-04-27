import sys
import re
import json
import subprocess
import os

def analyze_file(filepath):
    metrics = {
        'auto': [],
        'trust': [],
        'guard': [],
        'phase': 0,
        'micro': 0,
        'max_target': 0,
        'last_base': 0
    }
    
    # Regex patterns
    auto_re = re.compile(r'telemetry_autonomy_score=([-+]?\d*\.\d+|\d+)')
    trust_re = re.compile(r'telemetry_reasoning_trust_deliberative=([-+]?\d*\.\d+|\d+)')
    guard_re = re.compile(r'telemetry_guard_utility_ema=([-+]?\d*\.\d+|\d+)')
    phase_re = re.compile(r'completed_phase_count=([-+]?\d*\.\d+|\d+)')
    micro_re = re.compile(r'completed_micro_total=([-+]?\d*\.\d+|\d+)')
    target_re = re.compile(r'promotion_target=([-+]?\d*\.\d+|\d+)')
    base_re = re.compile(r'base_promotion_target=([-+]?\d*\.\d+|\d+)')

    try:
        with open(filepath, 'r') as f:
            for line in f:
                m = auto_re.search(line)
                if m: metrics['auto'].append(float(m.group(1)))
                
                m = trust_re.search(line)
                if m: metrics['trust'].append(float(m.group(1)))
                
                m = guard_re.search(line)
                if m: metrics['guard'].append(float(m.group(1)))
                
                m = phase_re.search(line)
                if m: metrics['phase'] = int(m.group(1))
                
                m = micro_re.search(line)
                if m: metrics['micro'] = int(m.group(1))
                
                m = target_re.search(line)
                if m: metrics['max_target'] = max(metrics['max_target'], int(m.group(1)))
                
                m = base_re.search(line)
                if m: metrics['last_base'] = int(m.group(1))
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return None

    # Run preflight
    preflight_res = {"status": "ERROR", "warn": 0, "fail": 0}
    try:
        proc = subprocess.run(
            [sys.executable, "preflight_dump_gate.py", filepath, "--json"],
            capture_output=True, text=True, timeout=75
        )
        if proc.returncode == 0:
            data = json.loads(proc.stdout)
            preflight_res['status'] = data.get('status', 'OK')
            preflight_res['warn'] = data.get('warning_count', 0)
            preflight_res['fail'] = data.get('failure_count', 0)
        else:
            preflight_res['status'] = f"FAIL_{proc.returncode}"
    except subprocess.TimeoutExpired:
        preflight_res['status'] = "TIMEOUT"
    except Exception as e:
        preflight_res['status'] = "PROC_ERR"

    res = {
        'file': os.path.basename(filepath),
        'status': preflight_res['status'],
        'warn': preflight_res['warn'],
        'fail': preflight_res['fail'],
        'auto': sum(metrics['auto'])/len(metrics['auto']) if metrics['auto'] else 0,
        'trust': sum(metrics['trust'])/len(metrics['trust']) if metrics['trust'] else 0,
        'guard': sum(metrics['guard'])/len(metrics['guard']) if metrics['guard'] else 0,
        'phase': metrics['phase'],
        'micro': metrics['micro'],
        'drift': metrics['max_target'] > metrics['last_base'],
        'raw_metrics': metrics
    }
    return res

files = sys.argv[1:]
results = []
for f in files:
    r = analyze_file(f)
    if r: results.append(r)

# Print Table
header = f"{'File':<30} | {'Stat':<8} | {'W':<2} | {'F':<2} | {'Auto':<5} | {'Trust':<5} | {'Guard':<5} | {'Ph':<2} | {'Mi':<4} | {'D'}"
print(header)
print("-" * len(header))
for r in results:
    print(f"{r['file'][:30]:<30} | {r['status']:<8} | {r['warn']:<2} | {r['fail']:<2} | {r['auto']:5.2f} | {r['trust']:5.2f} | {r['guard']:5.2f} | {r['phase']:2d} | {r['micro']:4d} | {r['drift']}")

# Aggregates
if results:
    status_counts = {}
    for r in results: status_counts[r['status']] = status_counts.get(r['status'], 0) + 1
    total_warns = sum(r['warn'] for r in results)
    total_fails = sum(r['fail'] for r in results)
    drift_count = sum(1 for r in results if r['drift'])
    mean_auto = sum(r['auto'] for r in results) / len(results)
    mean_trust = sum(r['trust'] for r in results) / len(results)
    mean_guard = sum(r['guard'] for r in results) / len(results)
    all_trust = [r['trust'] for r in results]
    
    print("\n--- Aggregates ---")
    print(f"Statuses: {status_counts}")
    print(f"Total Warns: {total_warns}, Total Fails: {total_fails}")
    print(f"Drift Count: {drift_count}/{len(results)}")
    print(f"Mean Auto: {mean_auto:.3f}, Trust: {mean_trust:.3f}, Guard: {mean_guard:.3f}")
    if all_trust:
        print(f"Trust Range: {min(all_trust):.3f} to {max(all_trust):.3f}")

    print("\n--- Review Bullets ---")
    # Health/Risk Insight logic
    if total_fails > 0:
        print(f"- Risk: {total_fails} total preflight failures detected across the batch.")
    else:
        print("- Health: All files passed preflight without critical failures.")
    
    if drift_count > 0:
        print(f"- Warning: Promotion drift (target > base) detected in {drift_count} runs, suggesting unstable scaling.")
    
    if mean_trust < 0.5:
        print(f"- Risk: Low mean deliberative trust ({mean_trust:.3f}) indicating potential reasoning divergence.")
    elif mean_trust > 0.8:
        print(f"- Health: High reasoning trust stability observed ({mean_trust:.3f}).")
    
    if any(r['status'] == 'TIMEOUT' for r in results):
        print("- Operational: Some preflight checks timed out; results for those files are incomplete.")
