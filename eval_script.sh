#!/bin/zsh
FILES_FILE="files_to_check.txt"
PYTHON="/Users/dakotabrown/Desktop/CodingProjects/AIAssistant/.venv/bin/python"
SCRIPT="preflight_dump_gate.py"

total_files_checked=0
pass_count=0
fail_count=0
failed_files=()

# First 25 for drift check
drift_total=0
drift_passed=0

while IFS= read -r file; do
    total_files_checked=$((total_files_checked + 1))
    $PYTHON "$SCRIPT" --profile batch4 --json "$file" > /dev/null 2>&1
    cmd_status=$?
    
    if [ $cmd_status -eq 0 ]; then
        pass_count=$((pass_count + 1))
        if [ $total_files_checked -le 25 ]; then
            drift_passed=$((drift_passed + 1))
        fi
    else
        fail_count=$((fail_count + 1))
        failed_files+=("$file")
    fi
    
    if [ $total_files_checked -le 25 ]; then
        drift_total=$((drift_total + 1))
    fi
done < "$FILES_FILE"

echo "total_files_checked: $total_files_checked"
echo "pass_count: $pass_count"
echo "fail_count: $fail_count"
if [ $total_files_checked -gt 0 ]; then
    pass_rate=$(echo "scale=2; $pass_count / $total_files_checked" | bc)
    echo "pass_rate: $pass_rate"
fi
echo "drift_25_pass: $drift_passed"
echo "drift_25_fail: $((drift_total - drift_passed))"

if [ $fail_count -gt 0 ]; then
    echo "failed_files:"
    relaxed_passed=0
    relaxed_failed=0
    for f in $failed_files; do
        echo "  - $f"
        $PYTHON "$SCRIPT" --profile relaxed --json "$f" > /dev/null 2>&1
        if [ $? -eq 0 ]; then
            relaxed_passed=$((relaxed_passed + 1))
        else
            relaxed_failed=$((relaxed_failed + 1))
        fi
    done
    echo "relaxed_pass_count: $relaxed_passed"
    echo "relaxed_fail_count: $relaxed_failed"
fi

if [ $fail_count -eq 0 ]; then
    echo "verdict: GO"
else
    echo "verdict: NO-GO"
fi
