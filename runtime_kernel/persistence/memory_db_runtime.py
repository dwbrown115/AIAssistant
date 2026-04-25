from __future__ import annotations

import sqlite3


def init_memory_db(app: object) -> None:
    try:
        with sqlite3.connect(app.memory_db_path) as conn:
            conn.execute("DROP TABLE IF EXISTS maze_layout_memory")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS maze_structural_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    mode TEXT NOT NULL,
                    difficulty TEXT NOT NULL,
                    grid_size INTEGER NOT NULL,
                    start_cell TEXT NOT NULL,
                    player_cell TEXT NOT NULL,
                    open_cells INTEGER NOT NULL,
                    blocked_cells INTEGER NOT NULL,
                    unknown_cells INTEGER NOT NULL,
                    frontier_cells INTEGER NOT NULL,
                    junction_cells INTEGER NOT NULL,
                    corridor_cells INTEGER NOT NULL,
                    dead_end_cells INTEGER NOT NULL,
                    loop_estimate INTEGER NOT NULL,
                    details_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS maze_layout_cell_memory (
                    maze_layout_id INTEGER NOT NULL,
                    difficulty TEXT NOT NULL,
                    grid_size INTEGER NOT NULL,
                    cell_row INTEGER NOT NULL,
                    cell_col INTEGER NOT NULL,
                    cell_token TEXT NOT NULL,
                    last_seen_step INTEGER NOT NULL DEFAULT 0,
                    seen_count INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (
                        maze_layout_id,
                        difficulty,
                        grid_size,
                        cell_row,
                        cell_col
                    )
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS maze_pattern_catalog (
                    pattern_signature TEXT PRIMARY KEY,
                    pattern_name TEXT NOT NULL,
                    seen_count INTEGER NOT NULL DEFAULT 1,
                    last_reason TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            app._ensure_pattern_catalog_uncertainty_schema(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS maze_short_term_memory (
                    pattern_signature TEXT PRIMARY KEY,
                    pattern_name TEXT NOT NULL,
                    ascii_pattern TEXT NOT NULL,
                    recall_count INTEGER NOT NULL DEFAULT 0,
                    strength REAL NOT NULL DEFAULT 0.0,
                    created_step INTEGER NOT NULL DEFAULT 0,
                    last_recalled_step INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS maze_semantic_memory (
                    pattern_signature TEXT PRIMARY KEY,
                    pattern_name TEXT NOT NULL,
                    ascii_pattern TEXT NOT NULL,
                    recall_count INTEGER NOT NULL DEFAULT 0,
                    strength REAL NOT NULL DEFAULT 0.0,
                    promoted_from_stm INTEGER NOT NULL DEFAULT 1,
                    first_promoted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS maze_action_outcome_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    maze_layout_id INTEGER NOT NULL DEFAULT 0,
                    step_index INTEGER NOT NULL,
                    mode TEXT NOT NULL,
                    difficulty TEXT NOT NULL,
                    player_cell TEXT NOT NULL,
                    action_taken TEXT NOT NULL,
                    outcome_label TEXT NOT NULL,
                    outcome_value REAL NOT NULL,
                    reward_signal REAL NOT NULL DEFAULT 0.0,
                    penalty_signal REAL NOT NULL DEFAULT 0.0,
                    reason_tags TEXT NOT NULL DEFAULT '',
                    details_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            app._ensure_action_outcome_memory_schema(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS maze_cause_effect_stm (
                    cause_key TEXT PRIMARY KEY,
                    action_taken TEXT NOT NULL,
                    reason_tags TEXT NOT NULL,
                    vector_json TEXT NOT NULL,
                    avg_outcome REAL NOT NULL DEFAULT 0.0,
                    recall_count INTEGER NOT NULL DEFAULT 1,
                    strength REAL NOT NULL DEFAULT 0.25,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS maze_cause_effect_semantic (
                    cause_key TEXT PRIMARY KEY,
                    action_taken TEXT NOT NULL,
                    reason_tags TEXT NOT NULL,
                    vector_json TEXT NOT NULL,
                    avg_outcome REAL NOT NULL DEFAULT 0.0,
                    recall_count INTEGER NOT NULL DEFAULT 1,
                    strength REAL NOT NULL DEFAULT 0.25,
                    promoted_from_stm INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS maze_prediction_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    resolved_at TEXT,
                    maze_layout_id INTEGER NOT NULL,
                    step_created INTEGER NOT NULL,
                    step_resolved INTEGER,
                    cell_row INTEGER NOT NULL,
                    cell_col INTEGER NOT NULL,
                    predicted_label TEXT NOT NULL,
                    predicted_shape TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    p_open REAL NOT NULL,
                    p_blocked REAL NOT NULL,
                    shape_distribution_json TEXT NOT NULL DEFAULT '{}',
                    prior_shape_distribution_json TEXT NOT NULL DEFAULT '{}',
                    prediction_context_key TEXT NOT NULL DEFAULT '',
                    prediction_context_json TEXT NOT NULL DEFAULT '{}',
                    confidence_bucket INTEGER NOT NULL DEFAULT 0,
                    local_open_prob REAL NOT NULL,
                    prior_open_prob REAL NOT NULL,
                    resolution_status TEXT NOT NULL DEFAULT 'pending',
                    expiry_reason TEXT NOT NULL DEFAULT '',
                    actual_label TEXT NOT NULL DEFAULT '',
                    actual_shape TEXT NOT NULL DEFAULT '',
                    is_correct INTEGER,
                    is_shape_correct INTEGER,
                    occupancy_brier REAL NOT NULL DEFAULT 0.0,
                    shape_brier REAL NOT NULL DEFAULT 0.0,
                    occupancy_score_delta REAL NOT NULL DEFAULT 0.0,
                    shape_score_delta REAL NOT NULL DEFAULT 0.0,
                    score_delta REAL NOT NULL DEFAULT 0.0
                )
                """
            )
            app._ensure_prediction_memory_schema(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS maze_machine_vision_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    mode TEXT NOT NULL,
                    difficulty TEXT NOT NULL,
                    grid_size INTEGER NOT NULL,
                    maze_layout_id INTEGER NOT NULL,
                    step_index INTEGER NOT NULL,
                    facing TEXT NOT NULL,
                    signature_key TEXT NOT NULL,
                    predicted_row INTEGER NOT NULL,
                    predicted_col INTEGER NOT NULL,
                    predicted_confidence REAL NOT NULL DEFAULT 0.0,
                    predicted_support INTEGER NOT NULL DEFAULT 0,
                    actual_row INTEGER NOT NULL,
                    actual_col INTEGER NOT NULL,
                    manhattan_error INTEGER NOT NULL,
                    is_exact INTEGER NOT NULL DEFAULT 0,
                    model_source TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_machine_vision_signature
                ON maze_machine_vision_memory(signature_key)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_machine_vision_step
                ON maze_machine_vision_memory(step_index)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS maze_machine_vision_exit_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    mode TEXT NOT NULL,
                    difficulty TEXT NOT NULL,
                    grid_size INTEGER NOT NULL,
                    maze_layout_id INTEGER NOT NULL,
                    step_index INTEGER NOT NULL,
                    facing TEXT NOT NULL,
                    signature_key TEXT NOT NULL,
                    predicted_row INTEGER NOT NULL,
                    predicted_col INTEGER NOT NULL,
                    predicted_confidence REAL NOT NULL DEFAULT 0.0,
                    predicted_support INTEGER NOT NULL DEFAULT 0,
                    actual_row INTEGER NOT NULL,
                    actual_col INTEGER NOT NULL,
                    manhattan_error INTEGER NOT NULL,
                    is_exact INTEGER NOT NULL DEFAULT 0,
                    model_source TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_machine_vision_exit_signature
                ON maze_machine_vision_exit_memory(signature_key)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_machine_vision_exit_step
                ON maze_machine_vision_exit_memory(step_index)
                """
            )
            conn.commit()
    except Exception:  # noqa: BLE001
        return


def ensure_prediction_memory_schema(app: object, conn: sqlite3.Connection) -> None:
    try:
        rows = conn.execute("PRAGMA table_info(maze_prediction_memory)").fetchall()
    except Exception:  # noqa: BLE001
        return

    column_names = {str(row[1]) for row in rows if len(row) > 1}
    required_columns = {
        "shape_distribution_json": "TEXT NOT NULL DEFAULT '{}'",
        "prior_shape_distribution_json": "TEXT NOT NULL DEFAULT '{}'",
        "prediction_context_key": "TEXT NOT NULL DEFAULT ''",
        "prediction_context_json": "TEXT NOT NULL DEFAULT '{}'",
        "confidence_bucket": "INTEGER NOT NULL DEFAULT 0",
        "resolution_status": "TEXT NOT NULL DEFAULT 'pending'",
        "expiry_reason": "TEXT NOT NULL DEFAULT ''",
        "is_shape_correct": "INTEGER",
        "occupancy_brier": "REAL NOT NULL DEFAULT 0.0",
        "shape_brier": "REAL NOT NULL DEFAULT 0.0",
        "occupancy_score_delta": "REAL NOT NULL DEFAULT 0.0",
        "shape_score_delta": "REAL NOT NULL DEFAULT 0.0",
    }
    for column_name, column_spec in required_columns.items():
        if column_name in column_names:
            continue
        conn.execute(f"ALTER TABLE maze_prediction_memory ADD COLUMN {column_name} {column_spec}")

    if "resolution_status" in required_columns:
        conn.execute(
            """
            UPDATE maze_prediction_memory
            SET resolution_status = CASE
                WHEN actual_label IN ('open', 'blocked') THEN 'resolved'
                ELSE 'pending'
            END
            WHERE resolution_status IS NULL OR resolution_status = '' OR resolution_status = 'pending'
            """
        )


def ensure_action_outcome_memory_schema(app: object, conn: sqlite3.Connection) -> None:
    _ = app
    try:
        rows = conn.execute("PRAGMA table_info(maze_action_outcome_memory)").fetchall()
    except Exception:  # noqa: BLE001
        return

    column_names = {str(row[1]) for row in rows if len(row) > 1}
    if "maze_layout_id" not in column_names:
        conn.execute(
            "ALTER TABLE maze_action_outcome_memory ADD COLUMN maze_layout_id INTEGER NOT NULL DEFAULT 0"
        )


def ensure_pattern_catalog_uncertainty_schema(app: object, conn: sqlite3.Connection) -> None:
    _ = app
    try:
        rows = conn.execute("PRAGMA table_info(maze_pattern_catalog)").fetchall()
    except Exception:  # noqa: BLE001
        return

    column_names = {str(row[1]) for row in rows if len(row) > 1}
    required_columns = {
        "uncertainty_score": "REAL NOT NULL DEFAULT 0.0",
        "confidence_score": "REAL NOT NULL DEFAULT 1.0",
        "uncertainty_hits": "INTEGER NOT NULL DEFAULT 0",
        "last_uncertainty_note": "TEXT NOT NULL DEFAULT ''",
        "last_uncertainty_step": "INTEGER NOT NULL DEFAULT 0",
    }
    for column_name, column_spec in required_columns.items():
        if column_name in column_names:
            continue
        conn.execute(f"ALTER TABLE maze_pattern_catalog ADD COLUMN {column_name} {column_spec}")
