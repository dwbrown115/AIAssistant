import sys
content = sys.stdin.read()
lines = content.splitlines()
start = -1
for i, line in enumerate(lines):
    if "--- Files" in line:
        start = i
if start != -1:
    print("\n".join(lines[start:]))
else:
    print(content[-2000:])
