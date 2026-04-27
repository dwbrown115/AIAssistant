import os
import json
import glob
import subprocess
import re

def get_mean(pattern, text):
    matches = re.findall(pattern, text)
    if not matches:
        return None
    return sum(float(m) for m in matches) / len(matches)

def get_last(pattern, text):
    matches = re.findall(pattern, text)
    if not matches:
        return "N/A"
    return matches[-1]

files = glob.glob("Log Dump/15_mazes_*.txt")
results = []

for f in sorted(files):
    # Get status from preflight
    try:
        cmd = ["python3", "preflight_dump_gate.py", "--json", f]
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode()
        data = json.loads(output)
        status = data.get("status", "N/A")
    except:
        status = "Error"

    with open(f, 'r') as file:
        content = file.read()

    mean_autonomy = get_mean(r"telemetry_autonomy_score=([0-9\.-]+)", content)
    mean_trust = get_mean(r"telemetry_reasoning_trust_deliberative=([0-9\.-]+)", content)
    mean_utility = get_mean(r"telemetry_guard_utility_ema=([0-9\.-]+)", content)
    
    # Try looking for "key=value" then fallback to " "key": value" form if any
    phase_count = get_last(r"completed_phase_count=([0-9]+)", content)
    if phase_count == "N/A":
        phase_count = get_last(r"\"completed_phase_count\": ([0-9]+)", content)
        
    micro_total = get_last(r"completed_micro_total=([0-9]+)", content)
    if micro_total == "N/A":
        micro_total = get_last(r"\"completed_micro_total\": ([0-9]+)", content)

    results.append({
        "File": os.path.basename(f),
        "Status": status,
        "Mean Autonomy": mean_autonomy,
        "Mean Trust": mean_trust,
        "Mean Utility": mean_utility,
        "Phases": f"{phase_count}/{micro_total}"
    })

# Print Table
header = f"{'File':<35} {'Status':<7} {'Autonomy':<10} {'Trust':<10} {'Utility':<10} {'Phases':<10}"
print(header)
print("-" * len(header))
for r in results:
    auton = f"{r['Mean Autonomy']:.4f}" if r["Mean Autonomy"] is not None else "N/A"
    trust = f"{r['Mean Trust']:.4f}" if r["Mean Trust"] is not None else "N/A"
    util = f"{r['Mean Utility']:.4f}" if r["Mean Utility"] is not None else "N/A"
    print(f"{r['File']:<35} {r['Status']:<7} {auton:<10} {trust:<10} {util:<10} {r['Phases']:<10}")

# Aggregate Trust
trusts = [r["Mean Trust"] for r in results if r["Mean Trust"] is not None]
print("\nAggregate Statistics (Trust):")
if trusts:
    print(f"Mean: {sum(trusts) / len(trusts):.4f}")
    print(f"Min:  {min(trusts):.4f}")
    print(f"Max:  {max(trusts):.4f}")
