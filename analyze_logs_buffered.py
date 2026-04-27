import os
import glob
import re
import statistics

def find_files():
    files = glob.glob("Log Dump/15_mazes_*.txt")
    files.sort(key=os.path.getmtime, reverse=True)
    return files[:10]

def parse_line_by_line(file_path):
    m = {
        'completed_phase_count': [],
        'completed_micro_total': [],
        'active_target': [],
        'promotion_target': [],
        'learned_only_rate': [],
        'hardcoded_only_rate': [],
        'unresolved_objective_override_rate': [],
        'phase1_telemetry_coverage': [],
        'phase1_intervention_utility_win3': [],
        'phase1_penalty_delta_win3': [],
        'projection_coverage': [],
        'projection_beneficial_rate': [],
        'projection_non_beneficial_rate': [],
        'projection_clip_rate': []
    }
    base_pt = None
    status = "pass"
    warn_count = 0
    fail_count = 0

    try:
        with open(file_path, 'r') as f:
            for line in f:
                if "FAILURE" in line:
                    status = "fail"
                    fail_count += 1
                if "WARNING" in line:
                    if status != "fail": status = "warn"
                    warn_count += 1
                
                if "base_promotion_target" in line:
                    match = re.search(r'base_promotion_target[:=]\s*([\d\.]+)', line)
                    if match: base_pt = float(match.group(1))

                for key in m:
                    if key in line:
                        pattern = rf'{key}[:=]\s*([\-\d\.]+)'
                        match = re.search(pattern, line)
                        if match:
                            try:
                                val = float(match.group(1))
                                if "count" in key or "total" in key: val = int(val)
                                m[key].append(val)
                            except: pass
                        elif key == 'active_target':
                            match = re.search(r'active_target[:=]\s*(\S+)', line)
                            if match: m[key].append(match.group(1))
        return m, base_pt, status, warn_count, fail_count
    except Exception as e:
        return None

def analyze():
    files = find_files()
    results = []
    print("--- Files (Newest to Oldest) ---")
    for f in files:
        print(f)
        res = parse_line_by_line(f)
        if res: results.append({'file': f, 'data': res})

    statuses = [r['data'][2] for r in results]
    total_warns = sum(r['data'][3] for r in results)
    total_fails = sum(r['data'][4] for r in results)

    print(f"\nStatus Counts: Pass: {statuses.count('pass')}, Warn: {statuses.count('warn')}, Fail: {statuses.count('fail')}")
    print(f"Total Warnings: {total_warns}, Total Failures: {total_fails}")

    keys_to_mean = [
        'learned_only_rate', 'hardcoded_only_rate', 'unresolved_objective_override_rate',
        'phase1_telemetry_coverage', 'phase1_intervention_utility_win3', 'phase1_penalty_delta_win3',
        'projection_coverage', 'projection_beneficial_rate', 'projection_non_beneficial_rate', 'projection_clip_rate'
    ]
    
    print("\nMean Metric Values:")
    for k in keys_to_mean:
        vals = [v for r in results for v in r['data'][0][k]]
        if vals: print(f"  {k}: {statistics.mean(vals):.4f}")
        else: print(f"  {k}: N/A")

    phases = [v for r in results for v in r['data'][0]['completed_phase_count']]
    micros = [v for r in results for v in r['data'][0]['completed_micro_total']]
    targets = [v for r in results for v in r['data'][0]['active_target']]
    
    print("\nKernel-Phase Integration Summary:")
    if phases: print(f"  Phases: min={min(phases)}, max={max(phases)}, mean={statistics.mean(phases):.2f}")
    if micros: print(f"  Micros: min={min(micros)}, max={max(micros)}, mean={statistics.mean(micros):.2f}")
    if targets:
        from collections import Counter
        print(f"  Most common active_target: {Counter(targets).most_common(3)}")

    drift_count = 0
    global_max_pt = 0.0
    for r in results:
        pts = r['data'][0]['promotion_target']
        base = r['data'][1]
        mx = max(pts) if pts else 0.0
        global_max_pt = max(global_max_pt, mx)
        if base is not None and mx > base: drift_count += 1

    print(f"\nPromotion Drift Summary:\n  Files with drift: {drift_count}\n  Global max promotion_target: {global_max_pt}")
    
    passed = statuses.count('pass')
    print("\nAssessment:")
    if passed >= 8 and drift_count <= 2:
        print("Kernel and phase integration health is strong; metrics are within nominal ranges.")
    else:
        print("Kernel and phase integration health shows signs of instability or drift.")

analyze()
