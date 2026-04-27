import glob
import os
import re

patterns = [
    'parallel_reasoning_profile=',
    'reasoning_profile=',
    'immune_clamp_active=',
    'override_challenge_active=',
    'reasoning_budget',
    'parallel_reasoning:'
]

files = sorted(glob.glob("Log Dump/15_mazes_*.txt"))

for filepath in files:
    found = {}
    with open(filepath, 'r') as f:
        lines = f.readlines()
        
    for i, line in enumerate(lines):
        line = line.strip()
        for p in patterns:
            if p in line:
                if p == 'reasoning_budget':
                    block = []
                    for j in range(i, min(i+10, len(lines))):
                        l = lines[j].strip()
                        block.append(l)
                        if '}' in l: break
                    found[p] = " ".join(block)
                else:
                    found[p] = line
                    
    if found:
        print(f"{os.path.basename(filepath)}:", end=" ")
        parts = []
        for p in patterns:
            if p in found:
                parts.append(found[p])
        print(" | ".join(parts))
