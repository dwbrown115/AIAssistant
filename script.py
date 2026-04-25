import os, re
exclude_dirs = {'.venv', 'Log Dump', 'Log Dump OLD', 'AIAssistant-main', 'AIAssistantBAD', 'deprecated', '__pycache__'}
kernel_targets = ['runtime_kernel', 'maze', 'adaptive_controller.py', 'learned_autonomy_controller.py', 'organism_control.py', 'parallel_reasoning_engine.py', 'governance_orchestrator.py', 'kernel_contracts.py', 'runtime/app_runtime.py', 'app.py']
patterns = [re.compile(r'os\.getenv\(\s*["\']([A-Z0-9_]+)["\']'), re.compile(r'os\.environ\.get\(\s*["\']([A-Z0-9_]+)["\']'), re.compile(r'environ\.get\(\s*["\']([A-Z0-9_]+)["\']')]
infra_vars = {'OPENAI_API_KEY', 'OPENAI_LOGIC_MODEL', 'OPENAI_AGENT_MODEL', 'OPENAI_MODEL', 'PORT', 'HOST', 'FLASK_DEBUG', 'REQUEST_METHOD', 'SERVER_NAME', 'SERVER_PORT', 'SCRIPT_NAME', 'QUERY_STRING', 'REMOTE_ADDR'}
self_tuning_prefixes = ['ADAPTIVE_', 'LEARNED_AUTONOMY_', 'TRAINING_PHASE_', 'PARALLEL_REASONING_', 'PROJECTION_TRUST_', 'TERMINAL_TRUST_', 'HAZARD_PREPAREDNESS_', 'SPATIAL_', 'KERNEL_PATTERN_', 'LONG_LOOP_SUBTYPE_', 'OBJECTIVE_EXCITEMENT_', 'MAZE_MICRO_PROGRESSION_', 'MAZE_BATCH_MICRO_PROGRESSION_', 'SLEEP_CYCLE_', 'STM_', 'SEMANTIC_', 'MACHINE_VISION_']
self_tuning_contains = ['_EMA_', '_LEARNING_', '_AUTO_', '_DECAY']
def is_self_tuning(name):
    if any(name.startswith(p) for p in self_tuning_prefixes): return True
    if any(c in name for c in self_tuning_contains): return True
    return False
found_vars = set()
def scan_file(path):
    try:
        with open(path, 'r', errors='ignore') as f:
            content = f.read()
            for p in patterns:
                found_vars.update(p.findall(content))
    except: pass
for t in kernel_targets:
    if os.path.isfile(t):
        scan_file(t)
    elif os.path.isdir(t):
        for root, dirs, files in os.walk(t):
            if any(exc in root for exc in exclude_dirs): continue
            for file in files:
                if file.endswith('.py'):
                    scan_file(os.path.join(root, file))
kernel_vars = sorted([v for v in found_vars if v not in infra_vars])
self_tuning = [v for v in kernel_vars if is_self_tuning(v)]
hand_tuned = [v for v in kernel_vars if not is_self_tuning(v)]
print(f'Total Kernel Env Vars: {len(kernel_vars)}')
print(f'Self-Tuning: {len(self_tuning)}')
print(f'Hand-Tuned: {len(hand_tuned)}')
def print_bucket(name, items):
    print(f'\n{name} ({len(items)}):')
    for i in items[:40]: print(f'  - {i}')
    if len(items) > 40: print(f'  ... ({len(items)-40} more)')
print_bucket('SELF-TUNING', self_tuning)
print_bucket('HAND-TUNED', hand_tuned)
