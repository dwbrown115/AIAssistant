import os
import glob
import re
import statistics

def find_files():
    files = glob.glob("Log Dump/15_mazes_*.txt")
    files.sort(key=os.path.getmtime, reverse=True)
    return files[:10]

def parse_raw_file(file_path):
    metrics = {
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
    
    base_promotion_target = None
    status = "pass"
    warn_count = 0
    fail_count = 0

    try:
        with open(file_path, 'r') as f:
            content = f.read()
            # Kernel metrics
            metrics['completed_phase_count'] = [int(m) for m in re.findall(r'completed_phase_count[:=]\s*(\d+)', content)]
            metrics['completed_micro_total'] = [int(m) for m in re.findall(r'completed_micro_total[:=]\s*(\d+)', content)]
            metrics['active_target'] = re.findall(r'active_target[:=]\s*(\S+)', content)
            metrics['promotion_target'] = [float(m) for m in re.findall(r'promotion_target[:=]\s*([\d\.]+)', content)]
            
            base_search = re.search(r'base_promotion_target[:=]\s*([\d\.]+)', content)
            if base_search: base_promotion_target = float(base_search.group(1))

            # Numeric metrics extraction from raw text (assuming they appear as key: value)
            for key in metrics:
                if key not in ['completed_phase_count', 'completed_micro_total', 'active_target', 'promotion_target']:
                    pattern = rf'{key}[:=]\s*([\-\d\.]+)'
                    metrics[key] = [float(m) for m in re.findall(pattern, content)]

            # Mock status for this fallback task
            if "FAILURE" in content:
                status = "fail"
                fail_count = content.count("FAILURE")
            elif "WARNING" in content:
                status = "warn"
                warn_count = content.count("WARNING")
            
            return metrics, base_promotion_target, status, warn_count, fail_count
    except Exception as e:
        return None

def analyze():
    files = find_files()
    results = []
    for f in files:
        res = parse_raw_file(f)
        if res:
            results.append({'file': f, 'data': res})

    print("--- Files (Newest to Oldest) ---")
    for r in results: print(r['file'])

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
    
    print("\nMean Metric Values (Extracted from raw text):")
    for k in keys_to_mean:
        all_vals = []
        for r in results:
            if r['data'][0][k]: all_vals.extend(r['data'][0][k])
        if all_vals:
            print(f"  {k}: {statistics.mean(all_vals):.4f}")
        else:
            print(f"  {k}: N/A")

    all_phases = []
    all_micros = []
    all_active_targets = []
    drift_count = 0
    global_max_pt = 0.0
    
    for r in results:
        m, base_pt, _, _, _ = r['data']
        all_phases.extend(m['completed_phase_count'])
        all_micros.extend(m['completed_micro_total'])
        all_active_targets.extend(m['active_target'])
        
        max_pt = max(m['promotion_target']) if m['promotion_target'] else 0.0
        global_max_pt = max(global_max_pt, max_pt)
        if base_pt is not None and max_pt > base_pt:
            drift_count += 1

    print("\nKernel-Phase Integration Summary:")
    if all_phases: print(f"  Phases: min={min(all_phases)}, max={max(all_phases)}, mean={statistics.mean(all_phases):.2f}")
    if all_micros: print(f"  Micros: min={min(all_micros)}, max={max(all_micros)}, mean={statistics.mean(all_micros):.2f}")
    if all_active_targets:
        from collections import Counter
        print(f"  Most common active_target: {Counter(all_active_targets).most_common(3)}")

    print(f"\nPromotion Drift Summary:")
    print(f"  Files with drift: {drift_count}")
    print(f"  Global max promotion_target: {global_max_pt}")

    passed = statuses.count('pass')
    print("\nAssessment:")
    if passed >= 8 and drift_count <= 2:
        print("Kernel and phase integration health is strong across the recent 10 maze logs.")
    else:
        print("Kernel and phase integration health shows some instability/drift; monitor metrics closely.")

analyze()
