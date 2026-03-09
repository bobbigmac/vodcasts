from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from typing import Any


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run a persistent local LLM service for answer-engine query helpers.")
    p.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1).")
    p.add_argument("--port", type=int, default=8765, help="Bind port (default: 8765).")
    p.add_argument("--provider", choices=("local", "openai"), default="", help="Optional provider override for this server process.")
    p.add_argument("--model", default="", help="Optional model override for this server process.")
    p.add_argument("--openai-model", default="", help="Optional OpenAI model override when provider=openai.")
    p.add_argument("--device", default="", help="Optional device override, e.g. cuda or cpu.")
    p.add_argument("--warmup", action="store_true", help="Load the tokenizer/model before accepting requests.")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    if args.provider:
        os.environ["VOD_ANSWER_LLM_PROVIDER"] = str(args.provider)
    if args.model:
        os.environ["VOD_ANSWER_LLM_MODEL"] = str(args.model)
    if args.openai_model:
        os.environ["VOD_ANSWER_OPENAI_MODEL"] = str(args.openai_model)
    if args.device:
        os.environ["VOD_ANSWER_LLM_DEVICE"] = str(args.device)
    os.environ["VOD_ANSWER_LLM_SERVER"] = "1"

    from answer_engine_llm import (  # type: ignore
        model_info,
        plan_query,
        summarize_answer_candidate,
        review_answer_candidate,
        warmup_model,
    )

    gpu_lock = Lock()

    class Handler(BaseHTTPRequestHandler):
        server_version = "vodcasts-answer-engine-llm/1"

        def _send_json(self, code: int, payload: dict[str, Any]) -> None:
            raw = json.dumps(payload, ensure_ascii=True).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length) if length > 0 else b"{}"
            body = json.loads(raw.decode("utf-8", errors="replace"))
            return body if isinstance(body, dict) else {}

        def log_message(self, fmt: str, *args: Any) -> None:
            sys.stderr.write("[answer-engine] " + (fmt % args) + "\n")

        def do_GET(self) -> None:
            if self.path == "/health":
                self._send_json(200, {"ok": True, **model_info()})
                return
            self._send_json(404, {"ok": False, "error": "not_found"})

        def do_POST(self) -> None:
            try:
                body = self._read_json()
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": f"invalid_json: {exc}"})
                return
            try:
                if self.path == "/plan-query":
                    with gpu_lock:
                        plan = plan_query(question=str(body.get("question") or ""))
                    payload = (
                        {"intent": plan.intent, "search_queries": plan.search_queries, "related_topics": plan.related_topics}
                        if plan
                        else {}
                    )
                    self._send_json(200, payload)
                    return
                if self.path == "/review-answer":
                    with gpu_lock:
                        review = review_answer_candidate(
                            question=str(body.get("question") or ""),
                            episode_title=str(body.get("episode_title") or ""),
                            chapter_hint=str(body.get("chapter_hint") or ""),
                            retrieval_queries=list(body.get("retrieval_queries") or []),
                            context_segments=list(body.get("context_segments") or []),
                        )
                    payload = (
                        {
                            "relevant": review.relevant,
                            "relevance": review.relevance,
                            "start_segment_id": review.start_segment_id,
                            "quote_segment_id": review.quote_segment_id,
                            "summary": review.summary,
                            "why_relevant": review.why_relevant,
                            "quote": review.quote,
                            "tags": review.tags,
                        }
                        if review
                        else {}
                    )
                    self._send_json(200, payload)
                    return
                if self.path == "/summarize-answer":
                    with gpu_lock:
                        summary = summarize_answer_candidate(
                            question=str(body.get("question") or ""),
                            episode_title=str(body.get("episode_title") or ""),
                            source_title=str(body.get("source_title") or ""),
                            source_category=str(body.get("source_category") or ""),
                            source_tags=list(body.get("source_tags") or []),
                            content_label=str(body.get("content_label") or ""),
                            chapter_hint=str(body.get("chapter_hint") or ""),
                            retrieval_queries=list(body.get("retrieval_queries") or []),
                            context_segments=list(body.get("context_segments") or []),
                        )
                    payload = (
                        {
                            "relevant": summary.relevant,
                            "relevance": summary.relevance,
                            "summary": summary.summary,
                            "why_relevant": summary.why_relevant,
                            "tags": summary.tags,
                        }
                        if summary
                        else {}
                    )
                    self._send_json(200, payload)
                    return
                self._send_json(404, {"ok": False, "error": "not_found"})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})

    if args.warmup:
        info = warmup_model()
        print(
            f"[answer-engine] warmed LLM model={info.get('model')} device={info.get('device')} dtype={info.get('dtype')}",
            flush=True,
        )
    else:
        info = model_info()
        print(
            f"[answer-engine] starting lazy LLM server model={info.get('model')} device={info.get('device')}",
            flush=True,
        )

    server = ThreadingHTTPServer((str(args.host), int(args.port)), Handler)
    print(f"[answer-engine] listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[answer-engine] shutting down LLM server", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
