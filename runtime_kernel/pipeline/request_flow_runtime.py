from __future__ import annotations


def request_response(app: object, prompt: str, assistant_instructions: str) -> None:
    try:
        parsed_prompt = str(prompt or "").strip()
        if len(parsed_prompt) >= 2 and parsed_prompt[0] == parsed_prompt[-1] and parsed_prompt[0] in {'"', "'"}:
            parsed_prompt = parsed_prompt[1:-1].strip()

        sequence_segments = app._extract_maze_batch_sequence_segments(parsed_prompt)
        if sequence_segments:
            sequence_difficulty_overrides = app._extract_instruction_sequence_difficulty_overrides(
                assistant_instructions,
                len(sequence_segments),
            )
            sequence_result = app._execute_local_navigation_batch_sequence_runs(
                sequence_segments,
                assistant_instructions,
                sequence_difficulty_overrides,
            )
            app.root.after(0, app._set_debug_text, sequence_result["debug_text"])
            app.root.after(0, app._set_response, sequence_result["answer"])
            return

        batch_multiplier = app._extract_maze_batch_multiplier(parsed_prompt)
        normalized_prompt = app._strip_maze_batch_multiplier(parsed_prompt) if batch_multiplier > 1 else parsed_prompt

        local_navigation_request = app.local_navigation_kernel and app._is_local_navigation_request(normalized_prompt)
        local_navigation_result: dict | None = None
        local_navigation_debug = ""
        local_navigation_remaining = 0

        if local_navigation_request and batch_multiplier > 1:
            batch_result = app._execute_local_navigation_batch_runs(
                normalized_prompt,
                assistant_instructions,
                batch_multiplier,
            )
            app.root.after(0, app._set_debug_text, batch_result["debug_text"])
            app.root.after(0, app._set_response, batch_result["answer"])
            return

        if local_navigation_request:
            local_navigation_result = app._execute_local_navigation_request(normalized_prompt, assistant_instructions)
            local_navigation_remaining = int(local_navigation_result["remaining"])
            if (
                local_navigation_result["step_session"]["success"]
                or not app.client
                or not app.local_navigation_api_fallback
            ):
                app._present_local_navigation_result(local_navigation_result)
                return

            local_navigation_debug = app._format_local_navigation_debug(
                local_navigation_result,
                header="[LOCAL KERNEL PREFLIGHT]",
            )
            app.root.after(0, lambda: app.status_var.set("Local kernel stalled; using OpenAI fallback..."))

        if not app.client:
            raise RuntimeError("Missing OPENAI_API_KEY in .env or .env.secret")

        app.root.after(0, lambda: app.status_var.set("Logic model: interpreting request..."))
        plan = app._build_logic_plan(normalized_prompt, assistant_instructions)
        if plan["normalized_goal"]:
            app.last_normalized_goal = plan["normalized_goal"]

        repetition = {
            "is_repeat_goal": bool(plan.get("is_repeat_goal", False)),
            "execution_count": max(1, min(app.max_repeat_executions, int(plan.get("execution_count", 1) or 1))),
            "confidence": 0.0,
            "reason": "Repetition resolver disabled; using planner repetition fields.",
        }
        if app.enable_logic_repetition_resolver:
            repetition = app._logic_resolve_repetition(normalized_prompt, plan, assistant_instructions)
        if repetition["confidence"] >= app.repeat_confidence_threshold:
            plan["is_repeat_goal"] = repetition["is_repeat_goal"]
            plan["execution_count"] = repetition["execution_count"]

        if local_navigation_request and local_navigation_result is not None:
            plan["delegate"] = True
            plan["is_repeat_goal"] = local_navigation_remaining > 1
            plan["execution_count"] = max(1, local_navigation_remaining)
            plan["success_criteria"] = (
                f"Reach the current objective {plan['execution_count']} more time(s) after local-kernel progress."
            )
            if local_navigation_result["step_session"]["completed"] > 0:
                plan["intent_summary"] = (
                    f"{plan['intent_summary']} Continue from local-kernel progress; "
                    f"{local_navigation_result['step_session']['completed']} hit(s) already completed."
                ).strip()

        game_navigation_request = app._is_game_navigation_request(normalized_prompt, plan)
        low_confidence = plan["confidence"] < app.logic_confidence_threshold
        requested_count = app._extract_execution_count(plan)

        if not plan["delegate"]:
            answer = plan["direct_response"] or "No direct response returned."
            fallback_used = False
            fallback_moves: list[str] = []
            if app.enable_path_fallback and game_navigation_request and low_confidence:
                fallback_moves = app._shortest_path_moves_to_target()
                if fallback_moves:
                    fallback_used = True
                    app.root.after(0, app._apply_agent_moves, fallback_moves)

            game_state = app._get_game_state_snapshot()
            local_prefight_section = f"{local_navigation_debug}\n\n" if local_navigation_debug else ""
            debug_text = (
                f"{local_prefight_section}"
                "[LOGIC PLAN]\n"
                f"delegate: {plan['delegate']}\n"
                f"intent_summary: {plan['intent_summary']}\n"
                f"agent_task: {plan['agent_task']}\n"
                f"success_criteria: {plan['success_criteria']}\n"
                f"confidence: {plan['confidence']}\n"
                f"normalized_goal: {plan['normalized_goal']}\n"
                f"repeat_goal: {plan['is_repeat_goal']}\n"
                f"execution_count: {requested_count}\n"
                f"repetition_confidence: {repetition['confidence']}\n"
                f"repetition_reason: {repetition['reason']}\n"
                f"local_navigation_prefight: {bool(local_navigation_debug)}\n"
                f"game_navigation_request: {game_navigation_request}\n"
                f"fallback_used: {fallback_used}\n"
                f"fallback_moves: {fallback_moves}\n"
                f"game_state:\n{game_state}\n"
                "\n[AGENT OUTPUT]\nNot used (delegate=false)."
            )
            app.root.after(0, app._set_debug_text, debug_text)
            app.root.after(0, app._set_response, answer)
            return

        app.root.after(0, lambda: app.status_var.set("Agent model: executing task..."))
        step_session = {
            "requested_count": requested_count,
            "iterations": 0,
            "completed": 0,
            "remaining": 0,
            "success": False,
            "step_log": "",
        }
        agent_output = "Stepwise mode active: single-move proposals + logic move evaluation per step."
        if game_navigation_request:
            step_session = app._run_stepwise_goal_session(normalized_prompt, plan, assistant_instructions)
            app._record_last_navigation_session(
                requested_count,
                int(step_session.get("completed", 0) or 0),
            )

        game_state = app._get_game_state_snapshot()
        completed, remaining = app._goal_session_progress()
        target_cell_debug = (
            "(hidden in maze mode)" if app._normalized_layout_mode() == "maze" else str(app.current_target_cell)
        )

        local_prefight_section = f"{local_navigation_debug}\n\n" if local_navigation_debug else ""
        debug_text = (
            f"{local_prefight_section}"
            "[LOGIC PLAN]\n"
            f"delegate: {plan['delegate']}\n"
            f"intent_summary: {plan['intent_summary']}\n"
            f"agent_task: {plan['agent_task']}\n"
            f"success_criteria: {plan['success_criteria']}\n"
            f"confidence: {plan['confidence']}\n"
            f"normalized_goal: {plan['normalized_goal']}\n"
            f"repeat_goal: {plan['is_repeat_goal']}\n"
            f"execution_count: {requested_count}\n"
            f"repetition_confidence: {repetition['confidence']}\n"
            f"repetition_reason: {repetition['reason']}\n"
            f"local_navigation_prefight: {bool(local_navigation_debug)}\n"
            f"game_navigation_request: {game_navigation_request}\n"
            f"step_mode_success: {step_session['success']}\n"
            f"step_mode_iterations: {step_session['iterations']}\n"
            f"step_mode_completed_hits: {step_session['completed']}\n"
            f"step_mode_remaining_hits: {step_session['remaining']}\n"
            f"target_cell: {target_cell_debug}\n"
            f"goal_session_active: {app.goal_session_active}\n"
            f"goal_session_target_hits: {app.goal_session_target_hits}\n"
            f"goal_session_hits_completed: {completed}\n"
            f"goal_session_hits_remaining: {remaining}\n"
            f"auto_goal_hits_remaining: {app.auto_goal_hits_remaining}\n"
            f"game_state:\n{game_state}\n"
            "\n[STEP LOG]\n"
            f"{step_session['step_log'] or '(none)'}\n"
            "\n[AGENT OUTPUT]\n"
            f"{agent_output}"
        )
        app.root.after(0, app._set_debug_text, debug_text)

        app.root.after(0, lambda: app.status_var.set("Preparing final response..."))
        if game_navigation_request and not app.enable_logic_finalizer_for_navigation:
            completion_label = "maze runs" if app._normalized_layout_mode() == "maze" else "target hits"
            if step_session["success"]:
                answer = (
                    f"Navigation run complete. Completed {step_session['completed']}/{requested_count} {completion_label} "
                    f"in {step_session['iterations']} step iterations."
                )
            else:
                answer = (
                    f"Navigation progress: completed {step_session['completed']}/{requested_count} {completion_label} "
                    f"in {step_session['iterations']} step iterations; {step_session['remaining']} remaining."
                )
        else:
            answer = app._logic_finalize(normalized_prompt, plan, agent_output, assistant_instructions)
        app.root.after(0, app._set_response, answer)
    except Exception as exc:  # noqa: BLE001
        app.root.after(0, app._set_error, f"Request failed: {exc}")
