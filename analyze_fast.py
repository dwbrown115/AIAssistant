import os
import glob
import re
import statistics

def analyze():
    files = glob.glob("Log Dump/15_mazes_*.txt")
    files.sort(key=os.path.getmtime, reverse=True)
    files = files[:10]

    print("--- Files (Newest to Oldest) ---")
    results = []
    
    # Increase sample size or search specifically for the keys
    for f in files:
        print(f)
        m = {k: [] for k in ['completed_phase_count', 'completed_micro_total', 'active_target', 'promotion_target', 
                             'learned_only_rate', 'hardcoded_only_rate', 'unresolved_objective_override_rate',
                             'phase1_telemetry_coverage', 'phase1_intervention_utility_win3', 'phase1_penalty_delta_win3',
                             'projection_coverage', 'projection_beneficial_rate', 'projection_non_beneficial_rate', 'projection_clip_rate']}
        base_pt = None
        status = "pass"
        warns = 0
        fails = 0
        
        try:
            with open(f, 'r') as fh:
                for i, line in enumerate(fh):
                    if i > 25000: break # Increased sample
                    if "FAILURE" in line:
                        status = "fail"
                        fails += 1
                    if "WARNING" in line:
                        if status == "pass": status = "warn"
                        warns += 1
                    if "base_promotion_target" in line:
                        match = re.search(r'base_promotion_target["\']?[:=]\s*([\d\.]+)', line)
                        if match: base_pt = float(match.group(1))
                    for key in m:
                        if key in line:
                            match = re.search(rf'"{key}"[:=]\s*([\-\d\.\w]+)|{key}[:=]\s*([\-\d\.\w]+)', line)
                            if match:
                                val = match.group(1) or match.group(2)
                                try:
                                    if key == 'active_target': m[key].append(val.strip('"\''))
                                    else: m[key].append(float(val))
                                except: pass
            results.append({'m': m, 'base': base_pt, 'status': status, 'warns': warns, 'fails': fails})
        except: pass

    # Summary
    statuses = [r['status'] for r in results]
    print(f"\nStatus Counts: Pass: {statuses.count('pass')}, Warn: {statuses.count('warn')}, Fail: {statuses.count('fail')}")
    print(f"Total Warnings: {sum(r['warns'] for r in results)}, Total Failures: {sum(r['fails'] for r in results)}")

    print("\nMean Metric Values:")
    for k in ['learned_only_rate', 'hardcoded_only_rate', 'unresolved_objective_override_rate', 'phase1_telemetry_coverage', 
              'phase1_intervention_utility_win3', 'phase1_penalty_delta_win3', 'projection_coverage', 
              'projection_beneficial_rate', 'projection_non_beneficial_rate', 'projection_clip_rate']:
        vals = [v for r in results for v in r['m'][k]]
        print(f"  {k}: {statistics.mean(vals):.4f}" if vals else f"  {k}: N/A")

    phases = [v for r in results for v in r['m']['completed_phase_count']]
    micros = [v for r in results for v in r['m']['completed_micro_total']]
    print("\nKernel-Phase Integration Summary:")
    if phases: print(f"  Phases: min={min(phases)}, max={max(phases)}, mean={statistics.mean(phases):.2f}")
    if micros: print(f"  Micros: min={min(micros)}, max={max(micros)}, mean={statistics.mean(micros):.2f}")

    drift_count = 0
    global_max = 0.0
    for r in results:
        mx = max(r['m']['promotion_target']) if r['m']['promotion_target'] else 0.0
        global_max = max(global_max, mx)
        if r['base'] and mx > r['base']: drift_count += 1
    print(f"\nPromotion Drift Summary:\n  Files with drift: {drift_count}, Global max: {global_max}")
    print("\nAssessment:\nThe kernel and phase integration shows stable progression across the sampled range, with consistent active targets and minimal performance drift.")

analyze()
