from __future__ import annotations

import argparse
import os
import queue
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any


os.environ.setdefault("VOD_ANSWER_LLM_PROVIDER", "openai")
os.environ.pop("VOD_ANSWER_LLM_URL", None)

from answer_engine_lib import active_env, answer_question, resolve_paths  # noqa: E402


APP_TITLE = "Vodcasts Answer Engine"
SITE_BASE_URL = "https://prays.be"
DEFAULT_ANSWERS = 3
DEFAULT_REVIEW_CANDIDATES = 3
DEFAULT_PER_QUERY_LIMIT = 6
DEFAULT_CANDIDATES = 120


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Small UI for experimenting with answer-engine recommendations.")
    p.add_argument("--env", default="", help="Cache env (default: active env).")
    p.add_argument("--cache", default="", help="Optional cache dir override.")
    p.add_argument("--transcripts", default="", help="Optional transcripts root override.")
    return p.parse_args()


def _full_share_url(share_path: str) -> str:
    path = str(share_path or "").strip()
    if not path:
        return SITE_BASE_URL
    return f"{SITE_BASE_URL}{path}" if path.startswith("/") else f"{SITE_BASE_URL}/{path}"


def _result_copy_text(ans: dict[str, Any]) -> str:
    recommendation = str(ans.get("recommendation") or ans.get("summary") or "").strip()
    url = _full_share_url(str(ans.get("share_path") or ""))
    title = str(ans.get("episode_title") or "").strip()
    pieces: list[str] = []
    if recommendation:
        pieces.append(recommendation)
    if title:
        pieces.append(f"Watch: {title}")
    if url:
        pieces.append(url)
    return "\n\n".join(pieces).strip()


class AnswerEngineUi:
    def __init__(self, root: tk.Tk, *, db_path: Path, transcripts_root: Path, env_name: str) -> None:
        self.root = root
        self.db_path = db_path
        self.transcripts_root = transcripts_root
        self.env_name = env_name
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.running = False
        self.result_boxes: list[ScrolledText] = []

        self.root.title(APP_TITLE)
        self.root.geometry("1360x860")
        self.root.minsize(1080, 720)

        self._build_ui()
        self.root.after(120, self._drain_events)
        self._log(f"Ready. env={self.env_name} db={self.db_path}")
        if not (os.environ.get("OPENAI_API_KEY") or "").strip():
            self._log("Warning: OPENAI_API_KEY is not set.")

    def _build_ui(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Card.TFrame", background="#f5f6f8")
        style.configure("CardTitle.TLabel", font=("Segoe UI", 11, "bold"))
        style.configure("Muted.TLabel", foreground="#555555")

        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)

        top = ttk.Frame(outer)
        top.pack(fill="x")

        title = ttk.Label(top, text="Answer Engine Helper", font=("Segoe UI", 16, "bold"))
        title.grid(row=0, column=0, sticky="w")
        subtitle = ttk.Label(
            top,
            text="Paste a question, run the OpenAI-backed answer flow, then review up to 3 suggestions.",
            style="Muted.TLabel",
        )
        subtitle.grid(row=1, column=0, sticky="w", pady=(2, 10))

        input_row = ttk.Frame(outer)
        input_row.pack(fill="x")

        self.question_box = ScrolledText(input_row, height=5, wrap="word", font=("Segoe UI", 11))
        self.question_box.pack(fill="x", expand=True, side="left")
        self.question_box.insert(
            "1.0",
            "How do I deal with fear when life feels unstable?",
        )

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(8, 12))
        self.run_button = ttk.Button(actions, text="Find Recommendations", command=self._start_query)
        self.run_button.pack(side="left")
        self.clear_button = ttk.Button(actions, text="Clear Log", command=self._clear_log)
        self.clear_button.pack(side="left", padx=(8, 0))
        self.status_var = tk.StringVar(value="Idle")
        ttk.Label(actions, textvariable=self.status_var, style="Muted.TLabel").pack(side="right")

        content = ttk.Panedwindow(outer, orient="horizontal")
        content.pack(fill="both", expand=True)

        left = ttk.Frame(content)
        right = ttk.Frame(content)
        content.add(left, weight=1)
        content.add(right, weight=2)

        ttk.Label(left, text="Execution Log", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 6))
        self.log_box = ScrolledText(left, height=20, wrap="word", font=("Consolas", 10))
        self.log_box.pack(fill="both", expand=True)
        self.log_box.configure(state="disabled")

        ttk.Label(right, text="Recommendations", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 6))
        self.results_canvas = tk.Canvas(right, highlightthickness=0)
        self.results_scroll = ttk.Scrollbar(right, orient="vertical", command=self.results_canvas.yview)
        self.results_canvas.configure(yscrollcommand=self.results_scroll.set)
        self.results_scroll.pack(side="right", fill="y")
        self.results_canvas.pack(side="left", fill="both", expand=True)
        self.results_inner = ttk.Frame(self.results_canvas)
        self.results_window = self.results_canvas.create_window((0, 0), window=self.results_inner, anchor="nw")
        self.results_inner.bind("<Configure>", self._on_results_configure)
        self.results_canvas.bind("<Configure>", self._on_canvas_configure)

    def _on_results_configure(self, _event: tk.Event[Any]) -> None:
        self.results_canvas.configure(scrollregion=self.results_canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event[Any]) -> None:
        self.results_canvas.itemconfigure(self.results_window, width=event.width)

    def _clear_log(self) -> None:
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _log(self, text: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"{text}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _set_running(self, running: bool) -> None:
        self.running = running
        self.run_button.configure(state="disabled" if running else "normal")
        self.status_var.set("Running..." if running else "Idle")

    def _start_query(self) -> None:
        if self.running:
            return
        question = self.question_box.get("1.0", "end").strip()
        if len(question) < 5:
            messagebox.showwarning(APP_TITLE, "Enter a fuller question first.")
            return
        self._set_running(True)
        self._render_results([])
        self._log("")
        self._log(f"Question: {question}")
        thread = threading.Thread(target=self._run_query, args=(question,), daemon=True)
        thread.start()

    def _run_query(self, question: str) -> None:
        try:
            self.events.put(("log", "Running answer lookup..."))
            payload = answer_question(
                db_path=self.db_path,
                transcripts_root=self.transcripts_root,
                q=question,
                answers=DEFAULT_ANSWERS,
                per_query_limit=DEFAULT_PER_QUERY_LIMIT,
                candidates=DEFAULT_CANDIDATES,
                review_candidates=DEFAULT_REVIEW_CANDIDATES,
                include_noncontent=False,
            )
            self.events.put(("done", payload))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self._log(str(payload))
                elif kind == "error":
                    self._set_running(False)
                    self._log(f"Error: {payload}")
                    messagebox.showerror(APP_TITLE, str(payload))
                elif kind == "done":
                    self._handle_done(payload)
        except queue.Empty:
            pass
        finally:
            self.root.after(120, self._drain_events)

    def _handle_done(self, payload: dict[str, Any]) -> None:
        self._set_running(False)
        if payload.get("error"):
            self._log(f"Error: {payload.get('error')}")
            return
        plan = payload.get("plan") or {}
        self._log(f"Intent: {plan.get('intent') or '(none)'}")
        for query in plan.get("search_queries") or []:
            self._log(f"  query: {query}")
        for run in payload.get("search_runs") or []:
            self._log(
                f"  fts: {run.get('result_count', 0)} hits for {run.get('query')} "
                f"[{run.get('fts') or 'no-fts'}]"
            )
        answers = list(payload.get("answers") or [])[:DEFAULT_ANSWERS]
        self._log(f"Done. reviewed={payload.get('reviewed_candidates', 0)} answers={len(answers)}")
        self._render_results(answers)

    def _render_results(self, answers: list[dict[str, Any]]) -> None:
        for child in self.results_inner.winfo_children():
            child.destroy()
        self.result_boxes.clear()

        if not answers:
            empty = ttk.Label(
                self.results_inner,
                text="No recommendations yet. Run a question to see results.",
                style="Muted.TLabel",
            )
            empty.pack(anchor="w", fill="x", padx=4, pady=4)
            return

        for idx, ans in enumerate(answers, 1):
            self._render_answer_card(idx, ans)

    def _render_answer_card(self, idx: int, ans: dict[str, Any]) -> None:
        card = ttk.Frame(self.results_inner, style="Card.TFrame", padding=12)
        card.pack(fill="x", expand=True, pady=(0, 12))

        title = str(ans.get("episode_title") or "Untitled").strip()
        feed = str(ans.get("feed") or "").strip()
        timecode = str(ans.get("timecode") or "").strip()
        url = _full_share_url(str(ans.get("share_path") or ""))

        ttk.Label(card, text=f"{idx}. {title}", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(card, text=f"{feed}  |  {timecode}", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(2, 8))

        actions = ttk.Frame(card)
        actions.grid(row=0, column=1, rowspan=2, sticky="e")
        ttk.Button(actions, text="Open Link", command=lambda u=url: webbrowser.open(u)).pack(side="left")
        ttk.Button(actions, text="Copy Text", command=lambda a=ans: self._copy_text(_result_copy_text(a))).pack(side="left", padx=(8, 0))

        recommendation = str(ans.get("recommendation") or ans.get("summary") or "").strip()
        quote = str(ans.get("quote") or "").strip()
        tags = ", ".join(list(ans.get("tags") or []))

        if recommendation:
            ttk.Label(card, text="Recommendation", font=("Segoe UI", 10, "bold")).grid(row=2, column=0, sticky="w")
            ttk.Label(card, text=recommendation, wraplength=760, justify="left").grid(row=3, column=0, columnspan=2, sticky="w", pady=(2, 10))

        if quote:
            ttk.Label(card, text="Quote", font=("Segoe UI", 10, "bold")).grid(row=4, column=0, sticky="w")
            ttk.Label(card, text=f"“{quote}”", wraplength=760, justify="left").grid(row=5, column=0, columnspan=2, sticky="w", pady=(2, 10))

        if tags:
            ttk.Label(card, text=f"Tags: {tags}", style="Muted.TLabel").grid(row=6, column=0, columnspan=2, sticky="w", pady=(0, 8))

        ttk.Label(card, text="Editable Reply Text", font=("Segoe UI", 10, "bold")).grid(row=7, column=0, sticky="w")
        box = ScrolledText(card, height=7, wrap="word", font=("Segoe UI", 10))
        box.grid(row=8, column=0, columnspan=2, sticky="nsew")
        box.insert("1.0", _result_copy_text(ans))
        card.columnconfigure(0, weight=1)
        card.rowconfigure(8, weight=1)
        self.result_boxes.append(box)

    def _copy_text(self, text: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._log("Copied recommendation text to clipboard.")


def main() -> None:
    args = _parse_args()
    env_name = str(args.env or "").strip() or active_env()
    namespace = argparse.Namespace(env=args.env, cache=args.cache, transcripts=args.transcripts)
    _cache_dir, transcripts_root, db_path = resolve_paths(namespace)
    root = tk.Tk()
    app = AnswerEngineUi(root, db_path=db_path, transcripts_root=transcripts_root, env_name=env_name)
    _ = app
    root.mainloop()


if __name__ == "__main__":
    main()
