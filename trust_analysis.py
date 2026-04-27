import re
import glob
import os

def analyze_trust(filepath):
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Extract trust samples
    samples = [float(m) for m in re.findall(r"telemetry_reasoning_trust_deliberative=([0-9\.-]+)", content)]
    
    if not samples:
        return None
    
    count = len(samples)
    mean_all = sum(samples) / count
    
    n_25 = max(1, count // 4)
    first_25 = samples[:n_25]
    last_25 = samples[-n_25:]
    
    mean_first = sum(first_25) / len(first_25)
    mean_last = sum(last_25) / len(last_25)
    delta = mean_last - mean_first
    
    return {
        "File": os.path.basename(filepath),
        "Count": count,
        "Mean": mean_all,
        "First 25%": mean_first,
        "Last 25%": mean_last,
        "Delta": delta
    }

files = sorted(glob.glob("Log Dump/15_mazes_*.txt"))
results = []
for f in files:
    res = analyze_trust(f)
    if res:
        results.append(res)

# Print Table
header = f"{'File':<35} {'Count':<6} {'Mean':<8} {'First25%':<10} {'Last25%':<10} {'Delta':<8}"
print(header)
print("-" * len(header))
negative_deltas = 0
for r in results:
    if r['Delta'] < 0:
        negative_deltas += 1
    print(f"{r['File']:<35} {r['Count']:<6} {r['Mean']:<8.4f} {r['First 25%']:<10.4f} {r['Last 25%']:<10.4f} {r['Delta']:<8.4f}")

print(f"\nFiles with negative delta: {negative_deltas}")
