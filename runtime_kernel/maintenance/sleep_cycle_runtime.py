from __future__ import annotations

import gc
import sqlite3


def run_sleep_cycle(app: object, trigger: str = "manual", auto_mode: bool = False) -> dict[str, int | str]:
    if not app.sleep_cycle_enable:
        return {
            "trigger": str(trigger or "manual"),
            "skipped": 1,
            "reason": "disabled",
        }

    compressed_memory_events = 0
    compressed_memory_runs = 0
    compressed_endocrine_events = 0
    compressed_endocrine_runs = 0
    if app.sleep_cycle_log_rle_enable:
        compressed_memory_events, compressed_memory_runs = app._compress_log_deque_runs(
            app.memory_event_log,
            app.sleep_cycle_log_rle_min_run,
        )
        compressed_endocrine_events, compressed_endocrine_runs = app._compress_log_deque_runs(
            app.endocrine_event_log,
            app.sleep_cycle_log_rle_min_run,
        )

    removed_memory_events = app._trim_log_deque(app.memory_event_log, app.sleep_cycle_memory_event_keep)
    removed_endocrine_events = app._trim_log_deque(app.endocrine_event_log, app.sleep_cycle_endocrine_event_keep)
    usage_reinforced_stm = 0
    usage_reinforced_cause_effect = 0
    usage_pruned_stm = 0
    cause_effect_stm_pruned = 0
    cause_effect_semantic_pruned = 0
    stm_rows_pruned = 0
    semantic_rows_pruned = 0
    cause_effect_stm_rows_pruned = 0
    cause_effect_semantic_rows_pruned = 0
    hormone_prune_applied = 0
    hormone_prune_passes = 0
    hormone_saturated_before = 0
    hormone_saturated_after = 0
    action_rows_pruned = 0
    prediction_rows_pruned = 0
    db_error = ""

    try:
        with sqlite3.connect(app.memory_db_path) as conn:
            usage_cutoff = max(
                0,
                int(app.memory_step_index) - int(app.sleep_cycle_usage_recent_window_steps),
            )
            if app.sleep_cycle_usage_boost > 0.0:
                reinforced_stm = conn.execute(
                    """
                    UPDATE maze_short_term_memory
                    SET strength = strength + (? * (1.0 + (min(recall_count, 4) * 0.15))),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE last_recalled_step >= ?
                    """,
                    (float(app.sleep_cycle_usage_boost), int(usage_cutoff)),
                )
                usage_reinforced_stm = int(reinforced_stm.rowcount or 0)

                reinforced_cause_effect = conn.execute(
                    """
                    UPDATE maze_cause_effect_stm
                    SET strength = strength + (? * (1.0 + (min(recall_count, 5) * 0.12))),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE recall_count >= 2
                    """,
                    (float(app.sleep_cycle_usage_boost) * 0.7,),
                )
                usage_reinforced_cause_effect = int(reinforced_cause_effect.rowcount or 0)

            # Usage-aware stale cleanup before generic decay/prune pass.
            usage_stale_pruned = conn.execute(
                """
                DELETE FROM maze_short_term_memory
                WHERE strength < ?
                  AND recall_count <= 1
                  AND last_recalled_step < ?
                """,
                (float(app.stm_prune_threshold), int(usage_cutoff)),
            )
            usage_pruned_stm = int(usage_stale_pruned.rowcount or 0)

            cause_stale_pruned = conn.execute(
                """
                DELETE FROM maze_cause_effect_stm
                WHERE strength < ?
                  AND recall_count <= 1
                """,
                (float(app.stm_prune_threshold),),
            )
            cause_effect_stm_pruned = int(cause_stale_pruned.rowcount or 0)

            if app.sleep_cycle_cause_effect_semantic_prune_enable:
                semantic_stale_pruned = conn.execute(
                    """
                    DELETE FROM maze_cause_effect_semantic
                    WHERE recall_count <= ?
                      AND strength < ?
                      AND abs(avg_outcome) <= ?
                    """,
                    (
                        int(app.sleep_cycle_cause_effect_semantic_prune_recall_max),
                        float(app.sleep_cycle_cause_effect_semantic_prune_strength_threshold),
                        float(app.sleep_cycle_cause_effect_semantic_prune_abs_outcome_max),
                    ),
                )
                cause_effect_semantic_pruned = int(semantic_stale_pruned.rowcount or 0)

            stm_rows_pruned = app._prune_table_to_recent_timestamp_rows(
                conn,
                "maze_short_term_memory",
                app.sleep_cycle_stm_max_rows,
            )
            semantic_rows_pruned = app._prune_table_to_recent_timestamp_rows(
                conn,
                "maze_semantic_memory",
                app.sleep_cycle_semantic_max_rows,
            )
            cause_effect_stm_rows_pruned = app._prune_table_to_recent_timestamp_rows(
                conn,
                "maze_cause_effect_stm",
                app.sleep_cycle_cause_effect_stm_max_rows,
            )
            cause_effect_semantic_rows_pruned = app._prune_table_to_recent_timestamp_rows(
                conn,
                "maze_cause_effect_semantic",
                app.sleep_cycle_cause_effect_semantic_max_rows,
            )

            action_rows_pruned = app._prune_table_to_recent_rows(
                conn,
                "maze_action_outcome_memory",
                app.sleep_cycle_action_outcome_keep_rows,
            )
            prediction_rows_pruned = app._prune_table_to_recent_rows(
                conn,
                "maze_prediction_memory",
                app.sleep_cycle_prediction_keep_rows,
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        db_error = str(exc)

    stm_result = app._run_stm_pruning_cycle()
    app._run_cause_effect_pruning_cycle(force=True)

    if app.endocrine_enabled and app.sleep_cycle_hormone_prune_enable and hasattr(app, "endocrine"):
        try:
            hormone_prune = app.endocrine.sleep_cycle_prune(
                decay_passes=int(app.sleep_cycle_hormone_decay_passes),
                pull_strength=float(app.sleep_cycle_hormone_pull_strength),
                extreme_threshold=float(app.sleep_cycle_hormone_extreme_threshold),
            )
            hormone_prune_applied = int(hormone_prune.get("applied", 0) or 0)
            hormone_prune_passes = int(hormone_prune.get("passes", 0) or 0)
            hormone_saturated_before = int(hormone_prune.get("saturated_before", 0) or 0)
            hormone_saturated_after = int(hormone_prune.get("saturated_after", 0) or 0)
        except Exception:  # noqa: BLE001
            hormone_prune_applied = 0

    run_vacuum = bool(app.sleep_cycle_vacuum_on_auto if auto_mode else app.sleep_cycle_vacuum_on_manual)
    vacuum_ran = 0
    if run_vacuum and (action_rows_pruned > 0 or prediction_rows_pruned > 0):
        try:
            with sqlite3.connect(app.memory_db_path) as conn:
                conn.execute("VACUUM")
            vacuum_ran = 1
        except Exception:  # noqa: BLE001
            vacuum_ran = 0

    gc_collected = int(gc.collect())
    app._last_sleep_cycle_step = int(app.memory_step_index)

    summary: dict[str, int | str] = {
        "trigger": str(trigger or "manual"),
        "auto": 1 if auto_mode else 0,
        "compressed_memory_events": int(compressed_memory_events),
        "compressed_memory_runs": int(compressed_memory_runs),
        "compressed_endocrine_events": int(compressed_endocrine_events),
        "compressed_endocrine_runs": int(compressed_endocrine_runs),
        "removed_memory_events": int(removed_memory_events),
        "removed_endocrine_events": int(removed_endocrine_events),
        "usage_reinforced_stm": int(usage_reinforced_stm),
        "usage_reinforced_cause_effect": int(usage_reinforced_cause_effect),
        "usage_pruned_stm": int(usage_pruned_stm),
        "cause_effect_stm_pruned": int(cause_effect_stm_pruned),
        "cause_effect_semantic_pruned": int(cause_effect_semantic_pruned),
        "stm_rows_pruned": int(stm_rows_pruned),
        "semantic_rows_pruned": int(semantic_rows_pruned),
        "cause_effect_stm_rows_pruned": int(cause_effect_stm_rows_pruned),
        "cause_effect_semantic_rows_pruned": int(cause_effect_semantic_rows_pruned),
        "hormone_prune": int(hormone_prune_applied),
        "hormone_prune_passes": int(hormone_prune_passes),
        "hormone_sat_before": int(hormone_saturated_before),
        "hormone_sat_after": int(hormone_saturated_after),
        "action_rows_pruned": int(action_rows_pruned),
        "prediction_rows_pruned": int(prediction_rows_pruned),
        "stm_promoted": int(stm_result.get("promoted", 0) or 0),
        "stm_pruned": int(stm_result.get("pruned", 0) or 0),
        "vacuum_ran": int(vacuum_ran),
        "gc_collected": int(gc_collected),
        "memory_step": int(app.memory_step_index),
    }
    if db_error:
        summary["db_error"] = db_error[:180]

    summary_text = (
        "[SLEEP-CYCLE: "
        f"trigger={summary['trigger']} auto={summary['auto']} step={summary['memory_step']} "
        f"log_rle={summary['compressed_memory_events']}@{summary['compressed_memory_runs']} "
        f"endo_rle={summary['compressed_endocrine_events']}@{summary['compressed_endocrine_runs']} "
        f"mem_log_trim={summary['removed_memory_events']} endocrine_trim={summary['removed_endocrine_events']} "
        f"usage_reinforce_stm={summary['usage_reinforced_stm']} "
        f"usage_reinforce_cause={summary['usage_reinforced_cause_effect']} "
        f"usage_pruned_stm={summary['usage_pruned_stm']} "
        f"cause_stm_pruned={summary['cause_effect_stm_pruned']} "
        f"cause_sem_pruned={summary['cause_effect_semantic_pruned']} "
        f"stm_rows_pruned={summary['stm_rows_pruned']} "
        f"semantic_rows_pruned={summary['semantic_rows_pruned']} "
        f"cause_stm_rows_pruned={summary['cause_effect_stm_rows_pruned']} "
        f"cause_sem_rows_pruned={summary['cause_effect_semantic_rows_pruned']} "
        f"hormone_prune={summary['hormone_prune']} "
        f"hormone_passes={summary['hormone_prune_passes']} "
        f"hormone_sat={summary['hormone_sat_before']}->{summary['hormone_sat_after']} "
        f"action_pruned={summary['action_rows_pruned']} prediction_pruned={summary['prediction_rows_pruned']} "
        f"stm_promoted={summary['stm_promoted']} stm_pruned={summary['stm_pruned']} "
        f"vacuum={summary['vacuum_ran']} gc={summary['gc_collected']}"
        f"{(' db_error=' + str(summary.get('db_error'))) if summary.get('db_error') else ''}]"
    )
    app._append_memory_log(summary_text)
    return summary


def maybe_run_sleep_cycle(app: object) -> None:
    if not app.sleep_cycle_enable:
        return
    interval = max(0, int(app.sleep_cycle_auto_interval_steps))
    if interval <= 0:
        return
    if int(app.memory_step_index) - int(app._last_sleep_cycle_step) < interval:
        return

    summary = app._run_sleep_cycle(trigger="auto-step", auto_mode=True)
    status_text = (
        "Sleep cycle (auto): "
        f"trimmed logs={summary.get('removed_memory_events', 0)} "
        f"action_pruned={summary.get('action_rows_pruned', 0)} "
        f"prediction_pruned={summary.get('prediction_rows_pruned', 0)}"
    )
    app.status_var.set(status_text)


def run_step_hygiene(app: object) -> dict[str, int | str]:
    removed_memory_events = app._trim_log_deque(
        app.memory_event_log,
        app.step_hygiene_log_keep_soft_cap,
    )
    removed_endocrine_events = app._trim_log_deque(
        app.endocrine_event_log,
        app.step_hygiene_endocrine_log_keep_soft_cap,
    )
    pattern_cache_pruned = app._prune_pattern_uncertainty_cache(app.step_hygiene_pattern_cache_max)

    context_cache_entries = int(len(app._prediction_context_stats_cache) + len(app._prediction_context_trust_cache))
    context_cache_cleared = 0
    if context_cache_entries > int(app.step_hygiene_context_cache_max):
        app._prediction_context_stats_cache.clear()
        app._prediction_context_trust_cache.clear()
        context_cache_cleared = 1

    hazard_cache_entries = int(len(app._hazard_preparedness_cache))
    hazard_cache_cleared = 0
    if hazard_cache_entries > max(128, int(app.step_hygiene_context_cache_max)):
        app._hazard_preparedness_cache.clear()
        hazard_cache_cleared = 1

    gc_mode = "gen0"
    gc_collected = 0
    full_gc_ran = 0
    full_interval = max(0, int(app.step_hygiene_full_gc_interval_steps))
    if full_interval > 0 and (int(app.memory_step_index) - int(app._last_step_hygiene_full_gc_step)) >= full_interval:
        gc_collected = int(gc.collect())
        gc_mode = "full"
        full_gc_ran = 1
        app._last_step_hygiene_full_gc_step = int(app.memory_step_index)
    else:
        gc_collected = int(gc.collect(0))

    if (
        removed_memory_events > 0
        or removed_endocrine_events > 0
        or pattern_cache_pruned > 0
        or context_cache_cleared > 0
        or hazard_cache_cleared > 0
        or gc_collected > 0
    ):
        app._append_memory_log(
            "[STEP-HYGIENE: "
            f"step={int(app.memory_step_index)} "
            f"gc_mode={gc_mode} gc={gc_collected} "
            f"mem_trim={removed_memory_events} endocrine_trim={removed_endocrine_events} "
            f"pattern_cache_pruned={pattern_cache_pruned} "
            f"context_cache_cleared={context_cache_cleared} "
            f"hazard_cache_cleared={hazard_cache_cleared}]"
        )

    return {
        "step": int(app.memory_step_index),
        "removed_memory_events": int(removed_memory_events),
        "removed_endocrine_events": int(removed_endocrine_events),
        "pattern_cache_pruned": int(pattern_cache_pruned),
        "context_cache_cleared": int(context_cache_cleared),
        "hazard_cache_cleared": int(hazard_cache_cleared),
        "gc_collected": int(gc_collected),
        "gc_full": int(full_gc_ran),
    }


def maybe_run_step_hygiene(app: object) -> None:
    if not app.step_hygiene_enable:
        return
    if app._normalized_layout_mode() != "maze":
        return
    interval = max(0, int(app.step_hygiene_interval_steps))
    if interval <= 0:
        return
    if int(app.memory_step_index) - int(app._last_step_hygiene_step) < interval:
        return
    app._run_step_hygiene()
    app._last_step_hygiene_step = int(app.memory_step_index)
