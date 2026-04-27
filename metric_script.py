import os
import re
import glob

def mean(l):
    return sum(l) / len(l) if l else 0.0

def process_file(f):
    with open(f, 'r') as fb:
        # Only read the last 1MB to avoid total memory/regex explosion
        fb.seek(0, os.SEEK_END)
        size = fb.tell()
        fb.seek(max(0, size - 1000000))
        text = fb.read()

    row = {"name": os.path.basename(f)}
    
    # Quick metrics from tail end
    row["status"] = "PASS" if "STATUS: PASS" in text else "FAIL"
    
    def get_last_float(pattern, default=0.0):
        matches = re.findall(pattern, text)
        return float(matches[-1]) if matches else default

    row["learned_only"] = get_last_float(r'learned_only_rate[:=\s]+([\d\.]+)')
    row["hardcoded_only"] = get_last_float(r'hardcoded_only_rate[:=\s]+([\d\.]+)')
    row["mixed"] = get_last_float(r'mixed_rate[:=\s]+([\d\.]+)')
    row["unres_obj"] = get_last_float(r'unresolved_objective_override_rate[:=\s]+([\d\.]+)')
    row["p1_util"] = get_last_float(r'phase1_intervention_utility_win3[:=\s]+([\d\.-]+)')
    row["proj_eff"] = get_last_float(r'projection_effectiveness_score[:=\s]+([\d\.-]+)')
    
    row["phase_count"] = int(get_last_float(r'"completed_phase_count"\s*:\s*(\d+)'))
    row["micro_total"] = int(get_last_float(r'"completed_micro_total"\s*:\s*(\d+)'))
    
    prom = [float(m) for m in re.findall(r'"promotion_target"\s*:\s*([\d\.\-]+)', text)]
    base_prom = [float(m) for m in re.findall(r'"base_promotion_target"\s*:\s*([\d\.\-]+)', text)]
    max_prom = max(prom) if prom else 0.0
    max_base = max(base_prom) if base_prom else 0.0
    row["drift"] = 1 if max_prom > max_base and max_base > 0 else 0

    # Module settling means
    keys = ["telemetry_autonomy_score", "telemetry_reasoning_trust_deliberative", "telemetry_guard_utility_ema"]
    for key in keys:
        matches = [float(m) for m in re.findall(rf'"{key}"\s*:\s*([\d\.\-]+)', text)]
        if not matches:
            matches = [float(m) for m in re.findall(rf'{key}=([\d\.\-]+)', text)]
        row[f"{key}_mean"] = mean(matches)
        
    return row

files = sorted(glob.glob("Log Dump/15_mazes_*.txt"), key=os.path.getmtime, reverse=True)
post_files = [f for f in files if "15_mazes_very_hard_20260426_" in os.path.basename(f)][:3]
pre_files = []
if post_files:
    last_post = post_files[-1]
    last_post_idx = files.index(last_post)
    pre_files = files[last_post_idx+1 : last_post_idx+4]

pre_results = [process_file(f) for f in pre_files]
post_results = [process_file(f) for f in post_files]

print("PRE Files:", [r["name"] for r in pre_results])
print("POST Files:", [r["name"] for r in post_results])
print("\nPer-File Metrics (Status, Lrn%, Hrd%, P1Util, ProjEff, Phases, Micro, Drift):")
for r in pre_results + post_results:
    print(f"{r['name'][:35]:35} | {r['status']:6} | {r['learned_only']:.2f} | {r['hardcoded_only']:.2f} | {r['p1_util']:.2f} | {r['proj_eff']:.2f} | {r['phase_count']:3} | {r['micro_total']:5} | {r['drift']}")

keys_to_sum = ["learned_only", "hardcoded_only", "mixed", "unres_obj", "p1_util", "proj_eff", "telemetry_autonomy_score_mean", "telemetry_reasoning_trust_deliberative_mean", "telemetry_guard_utility_ema_mean"]
pre_means = {k: mean([r[k] for r in pre_results]) for k in keys_to_sum}
post_means = {k: mean([r[k] for r in post_results]) for k in keys_to_sum}

print("\nGroup Summaries (PRE | POST):")
for k in keys_to_sum:
    print(f"{k:40} | {pre_means[k]:.4f} | {post_means[k]:.4f}")

print("\nDelta (POST - PRE):")
for k in keys_to_sum:
    print(f"{k:40} | {post_means[k] - pre_means[k]:.4f}")

print("\nModule Settling Interpretation:")
d_lrn = post_means["learned_only"] - pre_means["learned_only"]
d_p1 = post_means["p1_util"] - pre_means["p1_util"]
d_auto = post_means["telemetry_autonomy_score_mean"] - pre_means["telemetry_autonomy_score_mean"]
d_drift = sum(r["drift"] for r in post_results) - sum(r["drift"] for r in pre_results)

print(f"- Learned behavior shift: {d_lrn:+.4f} ({'increasing' if d_lrn > 0 else 'decreasing'} reliance on model weights).")
print(f"- Phase 1 Utility Delta: {d_p1:+.4f}. Intervention effectiveness is {'improving' if d_p1 > 0 else 'stagnating/dropping'}.")
print(f"- Autonomy Score Delta: {d_auto:+.4f}. Agent is showing {'greater' if d_auto > 0 else 'less'} self-directed policy execution.")
print(f"- Drift instances: {'Increased' if d_drift > 0 else 'Stable/Decreased'} by {abs(d_drift)} across the POST set.")
print(f"- Projection Effectiveness: Mean {post_means['proj_eff']:.4f} in POST group.")
print(f"- Overall Status: POST has {sum(1 for r in post_results if r['status'] == 'PASS')} PASS outcomes vs {sum(1 for r in pre_results if r['status'] == 'PASS')} in PRE.")
