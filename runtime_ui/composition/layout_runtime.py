from __future__ import annotations

import tkinter as tk
from tkinter import scrolledtext


def build_ui(app: object) -> None:
    container = tk.Frame(app.root, padx=14, pady=14)
    container.pack(fill=tk.BOTH, expand=True)

    title_row = tk.Frame(container)
    title_row.pack(fill=tk.X, pady=(0, 8))

    title = tk.Label(title_row, text="AI Assistant", font=("Helvetica", 18, "bold"))
    title.pack(side=tk.LEFT, anchor="w")

    app.micro_progress_label = tk.Label(
        title_row,
        textvariable=app.micro_progress_header_var,
        font=("Helvetica", 10),
        fg="#3b4d69",
        anchor="e",
        justify=tk.RIGHT,
    )
    app.micro_progress_label.pack(side=tk.RIGHT, anchor="e")
    app._update_micro_progress_header(announce_transition=False)

    panes = tk.PanedWindow(container, orient=tk.HORIZONTAL, sashwidth=6)
    panes.pack(fill=tk.BOTH, expand=True)
    app.main_panes = panes
    app.main_panes.bind("<ButtonRelease-1>", app._on_pane_resize)

    assistant_frame = tk.Frame(panes)
    game_frame = tk.Frame(panes)
    panes.add(assistant_frame, minsize=440)
    panes.add(game_frame, minsize=280)

    instruction_label = tk.Label(assistant_frame, text="Assistant Instructions (optional)")
    instruction_label.pack(anchor="w")

    app.instructions_input = scrolledtext.ScrolledText(assistant_frame, wrap=tk.WORD, height=4)
    app.instructions_input.pack(fill=tk.X, expand=False, pady=(4, 10))

    prompt_label = tk.Label(assistant_frame, text="Enter text")
    prompt_label.pack(anchor="w")

    app.prompt_input = scrolledtext.ScrolledText(assistant_frame, wrap=tk.WORD, height=7)
    app.prompt_input.pack(fill=tk.X, expand=False, pady=(4, 10))
    if not app.prompt_input.get("1.0", tk.END).strip():
        app.prompt_input.insert("1.0", app.default_prompt_text)
        app.prompt_input.mark_set(tk.INSERT, tk.END)

    controls = tk.Frame(assistant_frame)
    controls.pack(fill=tk.X, pady=(0, 10))

    app.send_btn = tk.Button(controls, text="Send", width=12, command=app.on_send)
    app.send_btn.pack(side=tk.LEFT)

    clear_btn = tk.Button(controls, text="Clear", width=12, command=app.clear_text)
    clear_btn.pack(side=tk.LEFT, padx=(8, 0))

    copy_btn = tk.Button(controls, text="Copy Output", width=12, command=app.copy_pipeline_bundle)
    copy_btn.pack(side=tk.LEFT, padx=(8, 0))

    status = tk.Label(controls, textvariable=app.status_var, anchor="w")
    status.pack(side=tk.LEFT, padx=(16, 0))

    response_label = tk.Label(assistant_frame, text="Response")
    response_label.pack(anchor="w")

    app.response_output = scrolledtext.ScrolledText(assistant_frame, wrap=tk.WORD, height=10, state=tk.DISABLED)
    app.response_output.pack(fill=tk.BOTH, expand=True, pady=(4, 10))

    debug_label = tk.Label(assistant_frame, text="Pipeline Debug")
    debug_label.pack(anchor="w")

    app.debug_output = scrolledtext.ScrolledText(assistant_frame, wrap=tk.WORD, height=10, state=tk.DISABLED)
    app.debug_output.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

    game_title = tk.Label(game_frame, text="Mini Game", font=("Helvetica", 14, "bold"))
    game_title.pack(anchor="w")

    game_note = tk.Label(game_frame, text="Move the square to the blue ball. Use Arrow keys or WASD.")
    game_note.pack(anchor="w", pady=(2, 8))

    visual_row = tk.Frame(game_frame, bg="#0b0b0b")
    visual_row.pack(anchor="w")

    app.game_canvas = tk.Canvas(
        visual_row,
        width=app.canvas_width,
        height=app.canvas_height,
        bg="#f5f7ff",
        highlightthickness=1,
        highlightbackground="#b6bfd3",
    )
    app.game_canvas.pack(side=tk.LEFT, fill=tk.NONE, expand=False)

    app.mv_render_debug_panel_container = tk.Frame(
        visual_row,
        width=300,
        height=app.canvas_height,
        bg="#0b0b0b",
        highlightthickness=1,
        highlightbackground="#2d2d2d",
    )
    app.mv_render_debug_panel_container.pack(side=tk.LEFT, fill=tk.Y, padx=(8, 0))
    app.mv_render_debug_panel_container.pack_propagate(False)

    if not hasattr(app, "mv_render_debug_panel_var"):
        app.mv_render_debug_panel_var = tk.StringVar(value="")
    app.mv_render_debug_panel = tk.Label(
        app.mv_render_debug_panel_container,
        textvariable=app.mv_render_debug_panel_var,
        justify=tk.LEFT,
        anchor="nw",
        bg="#0b0b0b",
        fg="#f8edc6",
        font=("Helvetica", 8, "bold"),
        padx=6,
        pady=6,
        wraplength=286,
    )
    app.mv_render_debug_panel.pack(fill=tk.BOTH, expand=True)

    if not bool(getattr(app, "mv_render_debug_enable", True)):
        app.mv_render_debug_panel_var.set("MVDBG disabled (F8 to toggle)")

    if app.enable_pseudo3d_view:
        pseudo3d_label = tk.Label(game_frame, text="Pseudo-3D Visualizer (preview)")
        pseudo3d_label.pack(anchor="w", pady=(8, 4))

        app.pseudo3d_canvas = tk.Canvas(
            game_frame,
            width=app.pseudo3d_width,
            height=app.pseudo3d_height,
            bg="#0f1220",
            highlightthickness=1,
            highlightbackground="#3b4667",
        )
        app.pseudo3d_canvas.pack(fill=tk.NONE, expand=False)

    runtime_controls = tk.LabelFrame(game_frame, text="Runtime Controls", padx=8, pady=8)
    runtime_controls.pack(fill=tk.X, pady=(8, 0))

    layout_row = tk.Frame(runtime_controls)
    layout_row.pack(fill=tk.X, pady=(0, 6))
    tk.Label(layout_row, text="Layout").pack(side=tk.LEFT)
    mode_menu = tk.OptionMenu(layout_row, app.layout_mode, "grid", "maze", command=app._on_layout_settings_changed)
    mode_menu.config(width=7)
    mode_menu.pack(side=tk.LEFT, padx=(6, 12))

    tk.Label(layout_row, text="Difficulty").pack(side=tk.LEFT)
    diff_menu = tk.OptionMenu(
        layout_row,
        app.maze_difficulty,
        "easy",
        "medium",
        "hard",
        "very hard",
        command=app._on_layout_settings_changed,
    )
    diff_menu.config(width=10)
    diff_menu.pack(side=tk.LEFT, padx=(6, 10))

    tk.Label(layout_row, text="Start #").pack(side=tk.LEFT)
    tk.Entry(layout_row, textvariable=app.maze_map_start_var, width=7).pack(side=tk.LEFT, padx=(4, 6))
    tk.Button(layout_row, text="Random #", command=app._randomize_maze_start_number).pack(side=tk.LEFT)
    tk.Button(layout_row, text="Set Start", command=app._set_maze_start_number).pack(side=tk.LEFT, padx=(6, 0))

    toggle_row = tk.Frame(runtime_controls)
    toggle_row.pack(fill=tk.X, pady=(0, 6))
    tk.Label(toggle_row, text="Toggles").pack(side=tk.LEFT)
    tk.Checkbutton(
        toggle_row,
        text="MV Enable",
        variable=app.machine_vision_master_enable_var,
        command=app._on_machine_vision_master_toggled,
        anchor="w",
    ).pack(side=tk.LEFT, padx=(8, 8))

    app.mv_route_mode_checkbutton = tk.Checkbutton(
        toggle_row,
        text="MV Route Mode (Deprecated)",
        variable=app.mv_route_planning_mode_var,
        command=app._on_mv_route_mode_toggled,
        anchor="w",
    )
    app.mv_route_mode_checkbutton.pack(side=tk.LEFT, padx=(0, 10))
    app._sync_machine_vision_toggle_controls()

    tk.Checkbutton(
        toggle_row,
        text="Fast Mode",
        variable=app.fast_mode_enabled_var,
        command=app._on_fast_mode_toggled,
        anchor="w",
    ).pack(side=tk.LEFT)

    tk.Checkbutton(
        toggle_row,
        text="Long-Run Mode",
        variable=app.long_run_mode_enabled_var,
        command=app._on_long_run_mode_toggled,
        anchor="w",
    ).pack(side=tk.LEFT, padx=(8, 0))

    app._build_kernel_phase_toggle_panel(runtime_controls)

    action_row = tk.Frame(runtime_controls)
    action_row.pack(fill=tk.X)
    tk.Label(action_row, text="Actions").pack(side=tk.LEFT)
    tk.Button(action_row, text="Reset Target", command=app._spawn_target).pack(side=tk.LEFT, padx=(8, 0))
    tk.Button(action_row, text="New Layout", command=app._regenerate_blockers).pack(side=tk.LEFT, padx=(6, 0))
    tk.Button(action_row, text="Next Maze", command=app._next_maze_layout).pack(side=tk.LEFT, padx=(6, 0))
    tk.Button(action_row, text="Reset Score", command=app._reset_score).pack(side=tk.LEFT, padx=(6, 0))
    tk.Label(action_row, textvariable=app.score_var).pack(side=tk.LEFT, padx=(12, 0))

    memory_tools = tk.LabelFrame(game_frame, text="Memory Tools", padx=8, pady=8)
    memory_tools.pack(fill=tk.X, pady=(10, 4))

    memory_top_row = tk.Frame(memory_tools)
    memory_top_row.pack(fill=tk.X, pady=(0, 6))
    tk.Label(memory_top_row, text="Run #").pack(side=tk.LEFT)
    tk.Entry(memory_top_row, textvariable=app.memory_run_id_var, width=8).pack(side=tk.LEFT, padx=(4, 10))
    tk.Button(memory_top_row, text="Refresh", command=app._refresh_memory_viewer).pack(side=tk.LEFT)
    tk.Button(memory_top_row, text="Sleep Cycle", command=app.run_sleep_cycle_now).pack(side=tk.LEFT, padx=(6, 0))
    tk.Button(memory_top_row, text="Copy Run Logs", command=app.copy_run_logs_bundle).pack(side=tk.LEFT, padx=(6, 0))

    memory_bottom_row = tk.Frame(memory_tools)
    memory_bottom_row.pack(fill=tk.X)
    tk.Button(memory_bottom_row, text="Log Dump", command=app.dump_memory_bundle).pack(side=tk.LEFT)
    tk.Button(memory_bottom_row, text="Log Dump Full", command=app.dump_memory_bundle_full).pack(side=tk.LEFT, padx=(6, 0))
    tk.Button(memory_bottom_row, text="Export Snapshot", command=app.export_memory_snapshot).pack(side=tk.LEFT, padx=(6, 0))
    tk.Button(memory_bottom_row, text="Import Snapshot", command=app.import_memory_snapshot).pack(side=tk.LEFT, padx=(6, 0))
    tk.Button(memory_bottom_row, text="Reset Memory", command=app.reset_memory_store).pack(side=tk.LEFT, padx=(6, 0))

    app.memory_view_output = scrolledtext.ScrolledText(game_frame, wrap=tk.WORD, height=11, state=tk.DISABLED)
    app.memory_view_output.pack(fill=tk.BOTH, expand=True)

    hormone_header = tk.Frame(game_frame)
    hormone_header.pack(fill=tk.X, pady=(8, 4))
    tk.Label(hormone_header, text="Hormone Monitor", font=("Helvetica", 10, "bold")).pack(side=tk.LEFT)

    app.hormone_panel_output = scrolledtext.ScrolledText(game_frame, wrap=tk.WORD, height=8, state=tk.DISABLED)
    app.hormone_panel_output.pack(fill=tk.X, expand=False)

    app._init_game()
    app._refresh_memory_viewer()
    app._refresh_hormone_panel()

    app.root.bind("<Command-Return>", app._on_cmd_enter)


def on_window_configure(app: object, event: tk.Event) -> None:
    if event.widget is not app.root:
        return
    if app._geometry_save_after_id is not None:
        app.root.after_cancel(app._geometry_save_after_id)
    app._geometry_save_after_id = app.root.after(300, app._save_window_geometry)


def on_pane_resize(app: object, _event: tk.Event) -> None:
    if app._geometry_save_after_id is not None:
        app.root.after_cancel(app._geometry_save_after_id)
    app._geometry_save_after_id = app.root.after(120, app._save_window_geometry)


def on_cmd_enter(app: object, _event: tk.Event) -> str:
    app.on_send()
    return "break"
