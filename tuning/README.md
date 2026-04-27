# Canonical Tuning Tooling

This folder contains the official full-system tuning analysis path.

## Contracts

- Status source of truth: `preflight_dump_gate.py --json`
- Canonical metric schema: `tuning/canonical_metrics_schema.json`

## Tools

- `tuning/canonical_compare.py`
  - Compares newest ID vs OOD run sets.
  - Uses preflight JSON for status and streamed parsing for telemetry means.

- `tuning/progression_consistency.py`
  - Checks phase/micro progression consistency across recent logs.

- `tuning/generate_tuning_report.py`
  - Produces a markdown report artifact combining canonical comparison and progression checks.

## Quick Start

```bash
/Users/dakotabrown/Desktop/CodingProjects/AIAssistant/.venv/bin/python -m tuning.generate_tuning_report \
  --python-exe /Users/dakotabrown/Desktop/CodingProjects/AIAssistant/.venv/bin/python \
  --preflight-script preflight_dump_gate.py
```

Default output:
- `phase_plans/reports/FULL_SYSTEM_TUNING_REPORT_<YYYY-MM-DD>.md`
