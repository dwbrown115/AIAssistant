import os
import glob
import re

def parse_file(filepath):
    res = {
        'filepath': filepath,
        'newest_progress': 'N/A',
        'newest_ramp': 'N/A',
        'max_micro_series': -1,
        'completed': False,
        'completion_evidence': [],
        'micro_evidence': []
    }
    
    success_criteria = None
    
    if not os.path.exists(filepath):
        return None

    with open(filepath, 'r') as f:
        for line in f:
            # Telemetry
            p_m = re.search(r'telemetry_batch_progress:\s*([\d.]+)', line)
            if p_m: res['newest_progress'] = p_m.group(1)
            
            r_m = re.search(r'telemetry_batch_ramp:\s*([\d.]+)', line)
            if r_m: res['newest_ramp'] = r_m.group(1)
            
            # Micro series - looking for batch_micro_series=Value or batch_micro_series:Value
            m = re.search(r'batch_micro_series[:=]\s*([\d.]+)', line)
            if m:
                val = float(m.group(1))
                if val > res['max_micro_series']:
                    res['max_micro_series'] = val
                res['micro_evidence'].append(line.strip())

            # Success criteria
            sc_m = re.search(r'success_criteria:.*?(\d+)\s+time', line)
            if sc_m:
                success_criteria = int(sc_m.group(1))

            # Completion markers
            if 'step_mode_success: True' in line:
                res['completed'] = True
                res['completion_evidence'].append(line.strip())
            
            hits_m = re.search(r'step_mode_completed_hits:\s*(\d+)', line)
            if hits_m and success_criteria is not None:
                hits = int(hits_m.group(1))
                if hits >= success_criteria:
                    res['completed'] = True
                    if line.strip() not in res['completion_evidence']:
                        res['completion_evidence'].append(line.strip())

    res['micro_evidence'] = res['micro_evidence'][-3:]
    res['completion_evidence'] = res['completion_evidence'][-3:]
    
    return res

log_files = sorted(glob.glob('Log Dump/*.txt'), key=os.path.getmtime, reverse=True)
if not log_files:
    print("No log files found.")
    exit()

newest_overall = parse_file(log_files[0])

newest_hard_completed = None
hard_files = [f for f in log_files if '15_mazes_hard' in f]
for f in hard_files:
    p = parse_file(f)
    if p and p['completed']:
        newest_hard_completed = p
        break

def print_res(label, data):
    if not data:
        print(f"{label}: None found.")
        return
    print(f"{label}: {data['filepath']}")
    print(f"  Progress: {data['newest_progress']}, Ramp: {data['newest_ramp']}, Max Micro: {data['max_micro_series']}")
    print("  Micro Evidence:")
    for e in data['micro_evidence']: print(f"    {e}")
    print("  Completion Evidence:")
    for e in data['completion_evidence']: print(f"    {e}")

print_res("OVERALL NEWEST", newest_overall)
print("---")
print_res("NEWEST COMPLETED HARD", newest_hard_completed)
