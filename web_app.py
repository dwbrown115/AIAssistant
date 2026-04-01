import os
import threading
import webbrowser
import re

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from openai import OpenAI

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
load_dotenv(os.path.join(BASE_DIR, ".env.secret"), override=True)

_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"(OPENAI_API_KEY\s*=\s*)([^\s]+)"), r"\1[REDACTED_API_KEY]"),
    (re.compile(r"(Authorization:\s*Bearer\s+)([^\s]+)", flags=re.IGNORECASE), r"\1[REDACTED_TOKEN]"),
)


def redact_secrets(text: str) -> str:
    if not text:
        return text
    redacted = text
    for pattern, replacement in _SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted

app = Flask(__name__)


def ask_openai(user_prompt: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return "Missing OPENAI_API_KEY. Add it to your .env or .env.secret file before sending prompts."

    client = OpenAI(api_key=api_key)
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    response = client.responses.create(
        model=model,
        input=user_prompt,
    )
    return redact_secrets(response.output_text.strip() or "No text response returned.")


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/ask", methods=["POST"])
def ask():
    prompt = request.form.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "Please enter some text before submitting."}), 400

    try:
        answer = ask_openai(prompt)
        return jsonify({"answer": answer})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": redact_secrets(f"Request failed: {exc}")}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5050"))
    url = f"http://127.0.0.1:{port}"

    # Open the app in the default browser once the debug reloader process starts.
    if os.getenv("WERKZEUG_RUN_MAIN") == "true" and os.getenv("AUTO_OPEN_BROWSER", "1") == "1":
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    app.run(debug=True, port=port)
