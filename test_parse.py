import re
import os
import glob

files = glob.glob("Log Dump/15_mazes_hard_*.txt")
if not files:
    print("No files found")
    exit()

f = sorted(files, key=os.path.getmtime, reverse=True)[0]
print(f"Testing file: {f}")
with open(f, 'r') as file:
    text = file.read()

# Try a more flexible regex for one of the keys
key = "telemetry_autonomy_score"
# Try searching without quotes or with different spacing
m1 = re.findall(rf'"{key}"\s*[:=]\s*([\d\.-]+)', text)
m2 = re.findall(rf'{key}\s*[:=]\s*([\d\.-]+)', text)
m3 = re.findall(rf'"{key}"\s*[:]\s*([\d\.-]+)', text)

print(f"M1 index: {len(m1)} (first 5: {m1[:5]})")
print(f"M2 index: {len(m2)} (first 5: {m2[:5]})")
print(f"M3 index: {len(m3)} (first 5: {m3[:5]})")

# Check for completed_phase_count
cpc = re.findall(r'completed_phase_count[:= ]*([0-9]*)', text)
print(f"CPC: {cpc[-5:] if cpc else 'None'}")

# Check first 500 characters
print("First 500 chars of text:")
print(text[:500])
