import os
import re
from collections import Counter
import preflight_dump_gate

files = [
    "Log Dump/15_mazes_hard_20260424_004536.txt",
    "Log Dump/15_mazes_hard_20260424_003834.txt",
    "Log Dump/15_mazes_hard_20260424_003225.txt",
    "Log Dump/15_mazes_hard_20260424_002459.txt",
    "Log Dump/15_mazes_hard_20260424_002132.txt",
    "Log Dump/15_mazes_hard_20260424_001817.txt",
    "Log Dump/15_mazes_hard_20260424_000336.txt",
    "Log Dump/15_mazes_hard_20260424_000038.txt",
    "Log Dump/15_mazes_hard_20260423_235831.txt",
    "Log Dump/15_mazes_hard_20260423_235143.txt",
    "Log Dump/15_mazes_hard_20260423_234624.txt",
    "Log Dump/15_mazes_hard_20260423_234305.txt",
    "Log Dump/15_mazes_hard_20260423_233449.txt",
    "Log Dump/15_mazes_hard_20260423_232713.txt",
    "Log Dump/15_mazes_hard_20260423_232213.txt",
    "Log Dump/15_mazes_hard_20260423_231913.txt",
    "Log Dump/15_mazes_hard_20260423_231625.txt",
    "Log Dump/15_mazes_hard_20260423_231258.txt",
    "Log Dump/15_mazes_hard_20260423_230554.txt",
    "Log Dump/15_mazes_hard_20260423_225805.txt"
]

status_counts = Counter()
metrics_acc = Counter()
metrics_sums = Counter()
file_count = 0
warnings_counter = Counter()
phase_evidence = Counter()

file_results = []

for f in files:
    if not os.path.exists(f):
        continue
    file_count += 1
    dump = preflight_dump_gate.parse_dump(f, profile='relaxed')
    
    # Status
    status_counts[dump.get('status', 'unknown')] += 1
    
    # Completion Metrics
    m = dump.get('metrics', {})
    metrics_sums['pipeline.step_mode_success'] += m.get('pipeline.step_mode_success', 0)
    metrics_sums['completed_hits'] += m.get('completed_hits', 0)
    metrics_sums['execution_count'] += m.get('execution_count', 0)
    
    # Rates and Scores
    rates = ['guard_override_rate', 'intervention_rate', 
             'behavior_screen:learned_only_rate', 'behavior_screen:hardcoded_only_rate', 
             'behavior_screen:mixed_rate', 'behavior_screen:unresolved_objective_override_rate',
             'behavior_screen:phase1_intervention_utility_win3', 'behavior_screen:phase1_penalty_delta_win3',
             'projection_screen:projection_coverage', 'projection_screen:projection_beneficial_rate',
             'projection_screen:projection_non_beneficial_rate', 'projection_screen:projection_clip_rate',
             'projection_screen:projection_effectiveness_score', 'projection_screen:projection_score_delta_avg',
             'projection_screen:projection_score_delta_scaled_avg']
    
    for r in rates:
        val = m.get(r, 0)
        metrics_sums[r] += val

    # Results for top 3
    file_results.append({
        'name': f,
        'guard_override_rate': m.get('guard_override_rate', 0),
        'projection_effectiveness_score': m.get('projection_screen:projection_effectiveness_score', 0)
    })

    # Warnings
    for w in dump.get('warnings', []):
        warnings_counter[w] += 1
        
    # Phase evidence
    with open(f, 'r') as content:
        text = content.read()
        phases = ['phase_1_envelope_shadow', 'phase_2_envelope_shadow', 'phase_3_envelope_shadow', 'phase_4_envelope_shadow', 'phase_5_legacy_prune']
        for p in phases:
            if p in text:
                phase_evidence[p] += 1
        if 'adaptive_phase_transition' in text:
            phase_evidence['adaptive_phase_transition'] += 1

print(f"Evaluated Files: {len(files)}")
print("\nStatus Counts:")
for k, v in status_counts.items():
    print(f"{k}: {v}")

print("\nMetric Summary Table (Means):")
for k in rates:
    avg = metrics_sums[k]/file_count if file_count > 0 else 0
    print(f"{k}: {avg:.4f}")

print(f"\nStep Mode Success: {metrics_sums['pipeline.step_mode_success']}")
print(f"Completed Hits / Execution Count: {metrics_sums['completed_hits']} / {metrics_sums['execution_count']}")

print("\nTop Recurring Warnings:")
for w, c in warnings_counter.most_common(5):
    print(f"{c}: {w}")

print("\nPhase Evidence Summary:")
for p, c in phase_evidence.items():
    print(f"{p}: Found in {c} files")

print("\n3 Worst Files by Highest guard_override_rate:")
for r in sorted(file_results, key=lambda x: x['guard_override_rate'], reverse=True)[:3]:
    print(f"{r['name']}: {r['guard_override_rate']:.4f}")

print("\n3 Worst Files by Lowest projection_effectiveness_score:")
for r in sorted(file_results, key=lambda x: x['projection_effectiveness_score'])[:3]:
    print(f"{r['name']}: {r['projection_effectiveness_score']:.4f}")
