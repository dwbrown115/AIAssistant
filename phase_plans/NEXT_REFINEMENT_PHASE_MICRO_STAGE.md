# Kernel Adaptive Phase Program (One Phase Per Capability)

## Purpose
Move kernel learning depth forward with one adaptive phase per capability gap:
- weak causal world modeling
- metric circularity
- limited abstraction bottleneck
- moderate representation depth

Each phase has training-first micro stages and integration micro stages. Promotion is data-driven and adaptive, not fixed by static phase thresholds.

## Phase Map
- Phase 1: Guess Ledger
  - Capability: assumption provenance and uncertainty lineage
  - Module id: `guess_ledger`
- Phase 2: Contradiction Accounting
  - Capability: contradiction debt and assumption blame
  - Module id: `contradiction_accounting`
- Phase 3: Falsification Planner
  - Capability: information-gain-driven falsification moves
  - Module id: `falsification_planner`
- Phase 4: Metric Decoupler
  - Capability: separate optimization signals from evaluation signals
  - Module id: `metric_decoupler`
- Phase 5: Abstraction Memory
  - Capability: reusable motifs, compositional transfer, schema reuse
  - Module id: `abstraction_memory`
- Phase 6: Causal Counterfactual Planner
  - Capability: bounded causal what-if planning before irreversible actions
  - Module id: `causal_counterfactual_planner`

## Micro Stages (Per Phase)
Every phase uses the same micro skeleton, with module-specific signals:

1. `m1_shadow_train`
   - Train in shadow mode with no policy impact.
   - Exit requires stable training and positive introspection gain.
2. `m2_counterfactual_train`
   - Train on contradiction/failure replay and counterfactual traces.
   - Exit requires transfer improvement under held-out scenarios.
3. `m3_advisory_integrate`
   - Integrate module as advisory signal into kernel scoring.
   - Exit requires stable safety and reduced loop/deadlock pressure.
4. `m4_control_integrate`
   - Promote to bounded control path in kernel decisions.
   - Exit requires sustained transfer gains with no safety regressions.

## Adaptive Promotion Logic
Use rolling EMAs and adaptive weighting, not fixed hardcoded phase cutoffs.

Core signals:
- train_quality
- integration_quality
- stability
- transfer
- safety
- introspection_gain

Composite score:

$$
s_t = \sum_i w_{i,t} \cdot x_{i,t}
$$

Adaptive target:

$$
	au_{t+1} = (1-\alpha)\tau_t + \alpha\,\mathrm{clip}(0.50 + 0.38\,r_t, 0.45, 0.90)
$$

where $r_t$ is robustness from stability/transfer/safety/introspection blend.

Promotion gate for current micro:
- observations >= micro minimum
- score_ema >= promotion_target
- safety_ema and stability_ema above adaptive floors

## Disable-Specific-Phase Semantics
Required behavior:
- Disabling a phase pauses that phase only.
- Progression cursor skips disabled phases and continues.
- Re-enabling resumes from saved micro index (no reset).
- History and completed micro count remain monotonic.

Control surface:
- `KERNEL_PHASE_DISABLE_LIST=phase_2_contradiction_accounting,phase_4_metric_decoupler`
- `KERNEL_PHASE_AUTOSTEP=1`
- `KERNEL_PHASE_OBSERVATION_FLOOR` (optional global minimum override)

## Integration Notes
- The runtime controller is implemented in `adaptive_phase_program.py`.
- `AdaptiveKernelPhaseProgram.observe_micro_metrics(...)` should be called each cycle from the kernel loop with current telemetry.
- On returned transition events, emit governance records and persist snapshots.
- `current_active_target()` gives the phase/micro to execute after skipping disabled or completed phases.

## Immediate Execution Order
1. Instantiate default phase specs with `build_default_kernel_phase_specs()`.
2. Wire telemetry -> `observe_micro_metrics(...)` in kernel runtime.
3. Add disable-list config ingestion before phase selection.
4. Emit transition/snapshot events into governance introspection output.
