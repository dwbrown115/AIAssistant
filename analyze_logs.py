import os
import glob
import json
import subprocess
import re
import statistics

def find_files():
    files = glob.glob("Log Dump/15_mazes_*.txt")
    files.sort(key=os.path.getmtime, reverse=True)
    return files[:10]

def run_preflight(file_path):
    try:
        result = subprocess.run(['python3', 'preflight_dump_gate.py', file_path, '--json'], 
                                capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    except Exception as e:
        print(f"Error running preflight on {file_path}: {e}")
        return None

def parse_raw_file(file_path):
    metrics = {
        'completed_phase_count': [],
        'completed_micro_total': [],
        'active_target': [],
        'promotion_target': []
    }
    try:
        with open(file_path, 'r') as f:
            content = f.read()
            metrics['completed_phase_count'] = [int(m) for m in re.findall(r'completed_phase_count[:=]\s*(\d+)', content)]
            metrics['completed_micro_total'] = [int(m) for m in re.findall(r'completed_micro_total[:=]\s*(\d+)', content)]
            metrics['active_target'] = re.findall(r'active_target[:=]\s*(\S+)', content)
            metrics['promotion_target'] = [float(m) for m in re.findall(r'promotion_target[:=]\s*([\d\.]+)', content)]
            
            # Look for base_promotion_target. If not found explicitly, we might need a default or search for it.
            base_search = re.search(r'base_promotion_target[:=]\s*([\d\.]+)', content)
            base_promotion_target = float(base_search.group(1)) if base_search else None
            
            return metrics, base_promotion_target
    except Exception as e:
        print(f"Error parsing raw file {file_path}: {e}")
        return metrics, None

def analyze():
    files = find_files()
    if not files:
        print("No files found.")
        return

    results = []
    
    for f in files:
        pj = run_preflight(f)
        raw_metrics, base_pt = parse_raw_file(f)
        results.append({
            'file': f,
            'json': pj,
            'raw': raw_metrics,
            'base_pt': base_pt
        })

    print("--- Files (Newest to Oldest) ---")
    for r in results:
        print(r['file'])

    # Status/Failures/Warnings
    statuses = [r['json'].get('status', 'unknown') for r in results if r['json']]
    total_warns = sum(len(r['json'].get('warnings', [])) for r in results if r['json'])
    total_fails = sum(len(r['json'].get('failures', [])) for r in results if r['json'])
    
    print(f"\nStatus Counts: Pass: {statuses.count('pass')}, Warn: {statuses.count('warn')}, Fail: {statuses.count('fail')}")
    print(f"Total Warnings: {total_warns}, Total Failures: {total_fails}")

    # Numeric Metrics Mean
    metric_keys = [
        'learned_only_rate', 'hardcoded_only_rate', 'unresolved_objective_override_rate',
        'phase1_telemetry_coverage', 'phase1_intervention_utility_win3', 'phase1_penalty_delta_win3',
        'projection_coverage', 'projection_beneficial_rate', 'projection_non_beneficial_rate', 'projection_clip_rate'
    ]
    
    print("\nMean Metric Values:")
    for k in metric_keys:
        vals = []
        for r in results:
            if r['json'] and 'metrics' in r['json']:
                v = r['json']['metrics'].get(k)
                if v is not None: vals.append(v)
        if vals:
            print(f"  {k}: {statistics.mean(vals):.4f}")
        else:
            print(f"  {k}: N/A")

    # Kernel-phase integration summary
    all_phases = []
    all_micros = []
    all_active_targets = []
    drift_count = 0
    global_max_pt = 0.0
    found_phase_files = 0
    found_micro_files = 0
    
    for r in results:
        m = r['raw']
        if m['completed_phase_count']:
            all_phases.extend(m['completed_phase_count'])
            found_phase_files += 1
        if m['completed_micro_total']:
            all_micros.extend(m['completed_micro_total'])
            found_micro_files += 1
        all_active_targets.extend(m['active_target'])
        
        max_pt = max(m['promotion_target']) if m['promotion_target'] else 0.0
        global_max_pt = max(global_max_pt, max_pt)
        if r['base_pt'] is not None and max_pt > r['base_pt']:
            drift_count += 1

    print("\nKernel-Phase Integration Summary:")
    print(f"  Files with completed_phase_count: {found_phase_files}/10")
    if all_phases:
        print(f"    Phases: min={min(all_phases)}, max={max(all_phases)}, mean={statistics.mean(all_phases):.2f}")
    print(f"  Files with completed_micro_total: {found_micro_files}/10")
    if all_micros:
        print(f"    Micros: min={min(all_micros)}, max={max(all_micros)}, mean={statistics.mean(all_micros):.2f}")
    
    if all_active_targets:
        from collections import Counter
        common_targets = Counter(all_active_targets).most_common(3)
        print(f"  Most common active_target: {common_targets}")

    print(f"\nPromotion Drift Summary:")
    print(f"  Files with drift: {drift_count}")
    print(f"  Global max promotion_target: {global_max_pt}")

    # Assessment
    # High drift or low telemetry or high failures suggest poor health.
    # High coverage and consistent phases suggest good health.
    passed = statuses.count('pass')
    print("\nAssessment:")
    if passed >= 8 and drift_count <= 2:
        print("Kernel and phase integration health is strong, showing high pass rates and minimal promotion drift across the recent maze logs.")
    elif passed >= 5:
        print("Kernel and phase integration health is moderate; while core metrics are stable, some drift or warnings indicate potential optimization needs.")
    else:
        print("Kernel and phase integration health appears degraded, with frequent failures or significant promotion drift requiring investigation.")

if __name__ == "__main__":
    analyze()
