import os
import glob
import subprocess
import json
import re
import statistics

def parse_line_by_line(filepath):
    metrics = {
        'auto_scores': [],
        'trust_scores': [],
        'guard_scores': [],
        'completed_phase_count': 0,
        'completed_micro_total': 0,
        'promotion_target_max': 0,
        'base_promotion_target_last': 0
    }
    
    try:
        with open(filepath, 'r') as f:
            for line in f:
                # Telemetry patterns
                if 'telemetry_autonomy_score' in line:
                    match = re.search(r'telemetry_autonomy_score:\s*([\d.]+)', line)
                    if match: metrics['auto_scores'].append(float(match.group(1)))
                
                if 'telemetry_reasoning_trust_deliberative' in line:
                    match = re.search(r'telemetry_reasoning_trust_deliberative:\s*([\d.]+)', line)
                    if match: metrics['trust_scores'].append(float(match.group(1)))
                
                if 'telemetry_guard_utility_ema' in line:
                    match = re.search(r'telemetry_guard_utility_ema:\s*([\d.]+)', line)
                    if match: metrics['guard_scores'].append(float(match.group(1)))

                # Phase counts
                if 'completed_phase_count' in line:
                    match = re.search(r'completed_phase_count:\s*(\d+)', line)
                    if match: metrics['completed_phase_count'] = int(match.group(1))
                
                if 'completed_micro_total' in line:
                    match = re.search(r'completed_micro_total:\s*(\d+)', line)
                    if match: metrics['completed_micro_total'] = int(match.group(1))

                # Promotion targets
                if 'promotion_target' in line and 'base_promotion_target' not in line:
                    match = re.search(r'promotion_target:\s*([\d.]+)', line)
                    if match: metrics['promotion_target_max'] = max(metrics['promotion_target_max'], float(match.group(1)))
                
                if 'base_promotion_target' in line:
                    match = re.search(r'base_promotion_target:\s*([\d.]+)', line)
                    if match: metrics['base_promotion_target_last'] = float(match.group(1))
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
    
    return metrics

def main():
    files = glob.glob('Log Dump/15_mazes_*.txt')
    files.sort(key=os.path.getmtime, reverse=True)
    target_files = files[:10]

    results = []
    
    for f in target_files:
        filename = os.path.basename(f)
        try:
            cmd = ['python3', 'preflight_dump_gate.py', f, '--json']
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=75)
            
            if proc.returncode == 0:
                data = json.loads(proc.stdout)
                status = data.get('status', 'N/A')
                warn = data.get('warning_count', 0)
                fail = data.get('failure_count', 0)
            else:
                status = 'ERR'
                warn = 0
                fail = 1
        except subprocess.TimeoutExpired:
            status = 'TIMEOUT'
            warn = 0
            fail = 1
        except Exception as e:
            status = f'ERR({type(e).__name__})'
            warn = 0
            fail = 1

        m = parse_line_by_line(f)
        
        auto = statistics.mean(m['auto_scores']) if m['auto_scores'] else 0.0
        trust = statistics.mean(m['trust_scores']) if m['trust_scores'] else 0.0
        guard = statistics.mean(m['guard_scores']) if m['guard_scores'] else 0.0
        drift = 1 if m['promotion_target_max'] > m['base_promotion_target_last'] else 0

        results.append({
            'file': filename,
            'status': status,
            'warn': warn,
            'fail': fail,
            'auto': auto,
            'trust': trust,
            'guard': guard,
            'phase': m['completed_phase_count'],
            'micro': m['completed_micro_total'],
            'drift': drift
        })

    # Table
    print(f"{'filename':<30} | {'status':<8} | {'w':>2} | {'f':>2} | {'auto':>5} | {'trust':>5} | {'guard':>5} | {'ph':>3} | {'mi':>3} | {'dr'}")
    print("-" * 100)
    for r in results:
        print(f"{r['file']:<30} | {r['status']:<8} | {r['warn']:2d} | {r['fail']:2d} | {r['auto']:.2f} | {r['trust']:.2f} | {r['guard']:.2f} | {r['phase']:3d} | {r['micro']:3d} | {r['drift']}")

    # Aggregates
    statuses = [r['status'] for r in results]
    total_warns = sum(r['warn'] for r in results)
    total_fails = sum(r['fail'] for r in results)
    total_drift = sum(r['drift'] for r in results)
    
    autos = [r['auto'] for r in results]
    trusts = [r['trust'] for r in results]
    guards = [r['guard'] for r in results]

    print("\nSummary Aggregates:")
    print(f"- Status counts: { {s: statuses.count(s) for s in set(statuses)} }")
    print(f"- Total warns/fails: {total_warns}/{total_fails}")
    print(f"- Drift count: {total_drift}")
    if results:
        print(f"- Mean auto: {statistics.mean(autos):.3f}")
        print(f"- Mean trust: {statistics.mean(trusts):.3f}")
        print(f"- Mean guard: {statistics.mean(guards):.3f}")
        print(f"- Trust min/max: {min(trusts):.3f} / {max(trusts):.3f}")

    # Notable issues
    issues = []
    if total_fails > 0: issues.append("Failures detected in gate checks.")
    if total_drift > 0: issues.append("Target drift detected in some files.")
    for r in results:
        if r['status'] in ['ERR', 'TIMEOUT']:
            issues.append(f"File {r['file']} failed with {r['status']}.")
    
    print("\nNotable Issues:")
    if issues:
        for iss in issues:
            print(f"- {iss}")
    else:
        print("No critical issues.")

if __name__ == '__main__':
    main()
