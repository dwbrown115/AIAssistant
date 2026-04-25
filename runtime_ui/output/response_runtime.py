from __future__ import annotations

import tkinter as tk


def set_debug_text(app: object, text: str) -> None:
    safe_text = app._redact_text(text)
    app.debug_output.config(state=tk.NORMAL)
    app.debug_output.delete("1.0", tk.END)
    app.debug_output.insert(tk.END, safe_text)
    app.debug_output.config(state=tk.DISABLED)


def set_response(app: object, text: str) -> None:
    safe_text = app._redact_text(text)
    app.response_output.config(state=tk.NORMAL)
    app.response_output.delete("1.0", tk.END)
    app.response_output.insert(tk.END, safe_text)
    app.response_output.config(state=tk.DISABLED)

    app.send_btn.config(state=tk.NORMAL, text="Send")
    app.status_var.set("Done")


def set_error(app: object, message: str) -> None:
    safe_message = app._redact_text(message)
    app.response_output.config(state=tk.NORMAL)
    app.response_output.delete("1.0", tk.END)
    app.response_output.insert(tk.END, safe_message)
    app.response_output.config(state=tk.DISABLED)

    app.send_btn.config(state=tk.NORMAL, text="Send")
    app.status_var.set("Error")
