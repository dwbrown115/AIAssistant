# Pre-Minesweeper OOD Readiness Plan

## Objective

Prepare OOD evaluation infrastructure before Minesweeper work begins, without over-investing in full OOD optimization early.

Definition:
- OOD (out-of-distribution) means task conditions that differ materially from the tuning/training distribution.

## Scope and Intent

This is a readiness plan, not a full OOD optimization program.

What this plan does:
- Creates stable baseline and measurement contracts.
- Defines OOD shift taxonomy and test harness shape.
- Adds robust telemetry and diagnostics that make later OOD iteration fast.

What this plan does not do:
- Force broad policy redesign before Minesweeper starts.
- Block development on aggressive OOD thresholds too early.

## Step 1: Lock In-Distribution Baseline

Actions:
- Freeze baseline seeds and run protocol.
- Freeze baseline config profile and key policy toggles.
- Record baseline medians and variance bands for primary metrics.

Required baseline metrics:
- completion rate
- reset pressure
- intervention frequency
- unresolved override rate
- learned-only rate
- memory integrity pass rate

Exit criteria:
- Re-running baseline protocol yields stable values within agreed variance band.

## Step 2: Define OOD Shift Taxonomy

Create shift buckets now so Minesweeper plugs into an existing framework.

Recommended shift classes:
- topology shift (new map geometry families)
- observation noise shift (sensor uncertainty / partial observability)
- dynamics shift (stochasticity in transitions or outcomes)
- objective shift (reward/task weighting changes)
- sparsity shift (rarer useful signals)

Severity levels:
- near-OOD: mild shift from baseline
- mid-OOD: clear but manageable shift
- far-OOD: strong distribution change likely to degrade performance

Exit criteria:
- Each test case is tagged by shift class and severity level.

## Step 3: Build OOD Harness Skeleton

Actions:
- Add test-suite tags: `id`, `ood_near`, `ood_mid`, `ood_far`.
- Add result schema fields for shift class and severity.
- Keep OOD suites report-only initially (non-blocking).

Minimum harness outputs:
- per-suite success and failure counts
- degradation vs ID baseline
- intervention and override deltas
- recovery latency summaries

Exit criteria:
- Harness runs end-to-end with placeholder suites and logs structured outputs.

## Step 4: Expand Robustness Telemetry

Add telemetry now so attribution is possible later.

Required telemetry channels:
- confidence and confidence drift
- module disagreement (adaptive vs deliberative vs local)
- intervention utility by context bucket
- unresolved override trend
- step-limit reset context

Exit criteria:
- Telemetry available in run artifacts for ID and OOD-tagged executions.

## Step 5: Add Ablation Discipline

Actions:
- Define mandatory module ablations per milestone.
- Run A/B: full system vs one mechanism removed.
- Track quality delta and intervention utility delta.

Why this matters:
- Prevents hidden coupling and pseudo-adaptivity.
- Improves confidence in what is truly learned vs forced.

Exit criteria:
- Ablation report produced for each major mechanism change.

## Step 6: Introduce Progressive OOD Gates

Rollout policy:
- Stage A: report-only OOD checks in CI.
- Stage B: warning thresholds for severe regressions.
- Stage C: blocking gates after threshold stability is proven.

Suggested gating dimensions:
- max allowed OOD degradation vs ID baseline
- max intervention spike tolerance
- max unresolved override increase
- minimum recovery speed floor

Exit criteria:
- CI produces OOD gate report every run.

## Step 7: Build Failure Bank

Actions:
- Capture representative failures by shift type and severity.
- Store short root-cause notes per failure.
- Link failure signatures to mitigation experiments.

Minimum failure bank fields:
- test id
- shift class and severity
- failure mode label
- primary suspect subsystem
- attempted mitigation and outcome

Exit criteria:
- Failure bank used in review before major policy changes.

## Operating Cadence

Weekly cadence:
- 1 baseline integrity run
- 1 near-OOD smoke suite
- 1 targeted ablation batch
- 1 failure-bank triage update

Milestone cadence:
- broaden shift severity only after stability at prior severity
- never promote to blocking CI gates without two consecutive stable cycles

## Immediate 7-Day Kickoff

1. Freeze baseline seeds/config and record baseline bands.
2. Create OOD taxonomy tags (`ood_near`, `ood_mid`, `ood_far`).
3. Add harness schema fields for shift metadata and degradation outputs.
4. Add confidence/disagreement/intervention utility telemetry channels.
5. Run first near-OOD smoke suite in report-only mode.
6. Produce first mini failure bank from observed regressions.

## Definition of Ready for Minesweeper OOD Work

You are ready when:
- ID baseline is stable and reproducible.
- OOD taxonomy and harness tags are in place.
- OOD runs produce structured metrics and telemetry.
- Ablation and failure-bank process is operational.
- CI includes at least report-only OOD outputs.
