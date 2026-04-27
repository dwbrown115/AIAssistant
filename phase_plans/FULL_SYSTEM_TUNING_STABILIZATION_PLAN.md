# Full System Tuning and Stabilization Plan

## Objective

Run a full-system tuning phase that consolidates recent kernel additions into a stable, explainable, and repeatable runtime profile before further feature expansion.

This plan is about system quality, not feature count.

## Why This Plan Is Needed Now

Recent integration velocity has been high. The kernel gained new policy surfaces, richer telemetry, and additional phase/micro machinery. The system is functional, but current evidence shows tuning debt:
- OOD proxy runs are stable but show notable trust degradation versus harder in-distribution runs.
- Some ad-hoc reports have produced contradictory status interpretations even when preflight JSON says pass.
- Phase and micro counters are not yet giving a clear progression narrative in every report path.
- Heavy parsing workflows have caused runtime friction and interrupted analysis cycles.

## Areas Still Lacking

### 1) Canonical Evaluation Consistency
- We still have multiple report paths that can disagree.
- Preflight JSON is reliable, but some custom scripts infer status incorrectly.

### 2) OOD Robustness Quality, Not Just Pass Status
- Safety and pass rates are good, but deliberative trust drops under stronger shift conditions.
- This indicates adaptation quality is lagging behind gating health.

### 3) Phase and Micro Progression Interpretability
- Progression counters are present but do not always align with operator expectations.
- We need a single interpretation contract for phase/micro progression state.

### 4) Attribution of Improvements
- It is still too easy to ship a change without proving which mechanism caused gains.
- Module-level attribution and ablation discipline are not yet mandatory in every milestone.

### 5) Throughput and Diagnostics Efficiency
- Large-log analysis can be slow and interruptible.
- We need a bounded, streaming-first diagnostics pipeline for routine comparisons.

## System-Level Success Criteria

The tuning phase is complete only when all conditions hold:
1. Canonical report path produces consistent status and metric outputs across all recent run sets.
2. OOD trust degradation is reduced to an accepted bound while preserving safety pass rates.
3. Phase and micro progression summaries are consistent across logs, snapshots, and reports.
4. Every major tuning change includes an ablation or attribution result.
5. Comparison workflows complete reliably within bounded runtime budgets.

## Safety Contract

No tuning action may violate these constraints:
- Hard safety veto pathways remain non-bypassable.
- Promotion target must remain bounded by policy envelope.
- Guard strength and intervention policies may be tuned, but never disabled.
- Any regression in severe safety behavior triggers immediate rollback.

## Tuning Program Phases

## Phase ST0: Baseline Lock and Measurement Contract

Stage ids:
- st0.m1_baseline_freeze
- st0.m2_metric_contract
- st0.m3_report_contract

Actions:
- Freeze baseline seeds, baseline profiles, and run protocol.
- Define one canonical metrics schema for system comparisons.
- Declare one source-of-truth status contract: preflight JSON output.

Exit criteria:
- Baseline reruns remain within variance band.
- Canonical schema is versioned and used by all comparison scripts.

## Phase ST1: Diagnostics Hardening and Parser Unification

Stage ids:
- st1.m1_parser_unification
- st1.m2_timeout_bounded_analysis
- st1.m3_status_normalization

Actions:
- Replace fragile text-only status inference with preflight JSON normalization.
- Add bounded timeouts and fallback behavior for long-running analyses.
- Standardize status labels and failure semantics.

Exit criteria:
- No PASS versus FAIL contradictions across official reports.
- Routine comparison runs complete without manual interruption.

## Phase ST2: Progression Integrity and Visibility

Stage ids:
- st2.m1_phase_micro_contract
- st2.m2_snapshot_alignment
- st2.m3_progress_explainability

Actions:
- Formalize phase and micro counter interpretation rules.
- Align runtime snapshot fields with log extraction fields.
- Add concise progression summaries to tuning reports.

Exit criteria:
- Phase and micro values match across log, snapshot, and report layers.
- Operators can explain progression state from one report output.

## Phase ST3: Arbitration and Override Pressure Tuning

Stage ids:
- st3.m1_override_pressure_profile
- st3.m2_intervention_utility_buckets
- st3.m3_soft_override_retuning

Actions:
- Tune intervention and override thresholds by context bucket.
- Track unresolved override trends and utility deltas after each change.
- Reduce unnecessary intervention pressure while keeping safety stable.

Exit criteria:
- Lower unresolved override trend without safety regressions.
- Intervention utility improves or remains stable after retuning.

## Phase ST4: OOD Robustness Quality Lift

Stage ids:
- st4.m1_near_ood_stabilization
- st4.m2_mid_ood_reliability
- st4.m3_far_ood_guarded_trials

Actions:
- Tune confidence and trust calibration under OOD-tagged suites.
- Prioritize improving deliberative trust quality under shift.
- Expand severity only after stability at prior severity.

Exit criteria:
- OOD trust degradation reduced to accepted bound.
- OOD pass rates remain stable with no safety regressions.

## Phase ST5: Guard and Autonomy Efficiency

Stage ids:
- st5.m1_guard_budget_recalibration
- st5.m2_autonomy_quality_balance
- st5.m3_efficiency_regression_checks

Actions:
- Recalibrate guard budget usage against outcome quality.
- Tune autonomy soft scaling to avoid false confidence under shift.
- Ensure guard utility and autonomy move together in desired direction.

Exit criteria:
- Guard utility remains healthy while autonomy quality improves.
- No increase in severe intervention events.

## Phase ST6: CI Gating and Regression Discipline

Stage ids:
- st6.m1_report_only_ci
- st6.m2_warning_thresholds
- st6.m3_blocking_regressions

Actions:
- Introduce report-only full-system tuning checks in CI.
- Add warning thresholds for OOD trust and override regressions.
- Promote to blocking only after two stable cycles.

Exit criteria:
- CI emits canonical tuning report every run.
- Regression thresholds are enforced with low false-positive rate.

## Mandatory Validation for Every Major Tuning Change

Require all of the following:
- Baseline A/B comparison on matched seeds.
- In-distribution plus OOD-tagged run evaluation.
- Intervention frequency and utility delta.
- Unresolved override and drift checks.
- Phase/micro progression consistency check.
- One attribution or ablation artifact for changed mechanisms.

## Operating Cadence

Weekly:
- 1 baseline integrity batch
- 1 near-OOD and mid-OOD comparison batch
- 1 targeted arbitration and intervention tuning batch
- 1 regression triage and rollback-readiness review

Milestone rule:
- Do not move to stricter gates until two consecutive stable cycles.

## Immediate 10-Day Kickoff

1. Lock canonical metrics schema and status contract.
2. Replace non-canonical status inference in comparison scripts.
3. Add bounded-runtime analysis path for large logs.
4. Run hard versus very-hard comparison using canonical path only.
5. Produce first trust-focused OOD tuning recommendation set.
6. Validate phase/micro consistency across logs and snapshots.
7. Publish first full-system tuning report with regression flags.

## Definition of Done

You are done when:
- Canonical reports are consistent and repeatable.
- OOD trust drop is materially reduced while safety remains stable.
- Progression reporting is clear and contract-accurate.
- Attribution discipline is active for all major tuning changes.
- CI continuously reports and guards against full-system regressions.
