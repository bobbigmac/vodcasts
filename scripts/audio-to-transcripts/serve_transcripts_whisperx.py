from __future__ import annotations

import argparse
import io
import json
import os
import queue
import sys
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import torch  # type: ignore
from whisperx import alignment, asr
from whisperx.utils import WriteSRT, WriteVTT

from whisperx_worker_common import WorkerWhisperxOptions, parse_worker_extra_args

_TRANSCRIBE_WORKER_POOL = 2


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run a persistent local WhisperX transcription service.")
    p.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1).")
    p.add_argument("--port", type=int, default=8776, help="Bind port (default: 8776).")
    p.add_argument("--model", default="medium", help="WhisperX model name (default: medium).")
    p.add_argument("--language", default="en", help="Default language code (default: en).")
    p.add_argument("--device", default="cuda", help="WhisperX device (default: cuda).")
    p.add_argument("--compute-type", default="float16", help="WhisperX compute type (default: float16).")
    p.add_argument("--extra-args", default="", help="Supported WhisperX CLI-style extra args for the worker runtime.")
    p.add_argument("--warmup", action="store_true", help="Load ASR and alignment models before accepting requests.")
    return p.parse_args()


@dataclass
class Job:
    payload: dict[str, Any]
    done: threading.Event
    result: dict[str, Any] | None = None
    error: str = ""


@dataclass
class WorkerState:
    slot: int
    asr_model: Any | None = None
    align_cache: dict[tuple[str, str], tuple[Any, dict[str, Any]]] = field(default_factory=dict)


class WhisperXService:
    def __init__(
        self,
        *,
        model_name: str,
        default_language: str,
        device: str,
        compute_type: str,
        options: WorkerWhisperxOptions,
    ) -> None:
        self.model_name = str(model_name or "medium").strip()
        self.default_language = str(default_language or "en").strip() or "en"
        self.device = str(device or "cuda").strip() or "cuda"
        self.compute_type = str(compute_type or "float16").strip() or "float16"
        self.options = options
        self._jobs: queue.Queue[Job | None] = queue.Queue()
        self._stats_lock = threading.Lock()
        self._active_jobs = 0
        self._processed_jobs = 0
        self._states = [WorkerState(slot=i + 1) for i in range(_TRANSCRIBE_WORKER_POOL)]
        self._workers = [
            threading.Thread(target=self._run_loop, args=(state,), name=f"whisperx-worker-{state.slot}", daemon=True)
            for state in self._states
        ]
        for worker in self._workers:
            worker.start()

    def shutdown(self) -> None:
        for _ in self._workers:
            self._jobs.put(None)
        for worker in self._workers:
            worker.join(timeout=5.0)

    def _run_loop(self, state: WorkerState) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                return
            with self._stats_lock:
                self._active_jobs += 1
            try:
                job.result = self._transcribe(job.payload, state=state)
            except Exception as exc:
                job.error = str(exc)
            finally:
                with self._stats_lock:
                    self._active_jobs = max(0, self._active_jobs - 1)
                    self._processed_jobs += 1
                job.done.set()

    def model_info(self) -> dict[str, Any]:
        with self._stats_lock:
            active_jobs = self._active_jobs
            processed_jobs = self._processed_jobs
        return {
            "model": self.model_name,
            "language": self.default_language,
            "device": self.device,
            "compute_type": self.compute_type,
            "loaded": any(state.asr_model is not None for state in self._states),
            "loaded_workers": sum(1 for state in self._states if state.asr_model is not None),
            "worker_pool_size": len(self._states),
            "queue_size": self._jobs.qsize(),
            "active_jobs": active_jobs,
            "processed_jobs": processed_jobs,
            "options": self.options.to_payload(),
        }

    def warmup(self) -> dict[str, Any]:
        for state in self._states:
            self._ensure_asr_model(state=state)
            if not self.options.no_align:
                self._get_align_model(state=state, language=self.default_language, align_model_name=self.options.align_model)
        info = self.model_info()
        info["cuda_available"] = bool(getattr(torch, "cuda", None) and torch.cuda.is_available())
        return info

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        job = Job(payload=payload, done=threading.Event())
        self._jobs.put(job)
        job.done.wait()
        if job.error:
            raise RuntimeError(job.error)
        return job.result or {}

    def _ensure_asr_model(self, *, state: WorkerState) -> Any:
        if state.asr_model is not None:
            return state.asr_model
        vad_options: dict[str, Any] = {"chunk_size": int(self.options.chunk_size or 30)}
        if self.options.vad_onset is not None:
            vad_options["vad_onset"] = float(self.options.vad_onset)
        if self.options.vad_offset is not None:
            vad_options["vad_offset"] = float(self.options.vad_offset)
        state.asr_model = asr.load_model(
            self.model_name,
            device=self.device,
            compute_type=self.compute_type,
            language=self.default_language,
            vad_method=self.options.vad_method,
            vad_options=vad_options,
            threads=int(self.options.threads or 4),
        )
        return state.asr_model

    def _get_align_model(self, *, state: WorkerState, language: str, align_model_name: str) -> tuple[Any, dict[str, Any]]:
        key = (str(language or "en").strip() or "en", str(align_model_name or "").strip())
        if key not in state.align_cache:
            state.align_cache[key] = alignment.load_align_model(
                language_code=key[0],
                device=self.device,
                model_name=(key[1] or None),
            )
        return state.align_cache[key]

    def _validate_request(self, payload: dict[str, Any]) -> None:
        req_model = str(payload.get("model") or self.model_name).strip() or self.model_name
        req_device = str(payload.get("device") or self.device).strip() or self.device
        req_compute = str(payload.get("compute_type") or self.compute_type).strip() or self.compute_type
        req_vad = str(payload.get("vad_method") or self.options.vad_method).strip().lower() or self.options.vad_method
        if req_model != self.model_name:
            raise ValueError(f"worker model mismatch: requested={req_model} server={self.model_name}")
        if req_device != self.device:
            raise ValueError(f"worker device mismatch: requested={req_device} server={self.device}")
        if req_compute != self.compute_type:
            raise ValueError(f"worker compute_type mismatch: requested={req_compute} server={self.compute_type}")
        if req_vad != self.options.vad_method:
            raise ValueError(f"worker vad_method mismatch: requested={req_vad} server={self.options.vad_method}")

    def _transcribe(self, payload: dict[str, Any], *, state: WorkerState) -> dict[str, Any]:
        self._validate_request(payload)
        audio_path = Path(str(payload.get("audio_path") or "")).resolve()
        if not audio_path.exists():
            raise FileNotFoundError(f"audio path not found: {audio_path}")

        model = self._ensure_asr_model(state=state)
        language = str(payload.get("language") or self.default_language).strip() or self.default_language
        batch_size = payload.get("batch_size", self.options.batch_size)
        chunk_size = int(payload.get("chunk_size") or self.options.chunk_size or 30)
        no_align = bool(payload.get("no_align", self.options.no_align))
        align_model_name = str(payload.get("align_model") or self.options.align_model).strip()
        interpolate_method = str(payload.get("interpolate_method") or self.options.interpolate_method).strip() or "nearest"
        return_char_alignments = bool(payload.get("return_char_alignments", self.options.return_char_alignments))
        highlight_words = bool(payload.get("highlight_words", self.options.highlight_words))
        max_line_count = payload.get("max_line_count", self.options.max_line_count)
        max_line_width = payload.get("max_line_width", self.options.max_line_width)
        verbose = bool(payload.get("verbose", self.options.verbose))
        print_progress = bool(payload.get("print_progress", self.options.print_progress))

        result = model.transcribe(
            str(audio_path),
            batch_size=(int(batch_size) if batch_size else None),
            chunk_size=chunk_size,
            language=language,
            print_progress=print_progress,
            verbose=verbose,
        )
        if not no_align and result.get("segments"):
            align_model, align_meta = self._get_align_model(
                state=state,
                language=result.get("language") or language,
                align_model_name=align_model_name,
            )
            result = alignment.align(
                result["segments"],
                align_model,
                align_meta,
                str(audio_path),
                self.device,
                interpolate_method=interpolate_method,
                return_char_alignments=return_char_alignments,
                print_progress=print_progress,
            )

        result["language"] = str(result.get("language") or language or self.default_language)
        writer_opts = {
            "highlight_words": highlight_words,
            "max_line_count": max_line_count,
            "max_line_width": max_line_width,
        }
        srt_writer = WriteSRT(output_dir=".")
        vtt_writer = WriteVTT(output_dir=".")
        srt_buf = io.StringIO()
        vtt_buf = io.StringIO()
        srt_writer.write_result(result, srt_buf, writer_opts)
        vtt_writer.write_result(result, vtt_buf, writer_opts)
        return {
            "ok": True,
            "language": result.get("language") or language,
            "segments": len(result.get("segments") or []),
            "srt_text": srt_buf.getvalue(),
            "vtt_text": vtt_buf.getvalue(),
        }


def main() -> None:
    args = _parse_args()
    options, unsupported = parse_worker_extra_args(str(args.extra_args or ""))
    if unsupported:
        raise SystemExit(f"unsupported worker extra args: {' '.join(unsupported)}")

    service = WhisperXService(
        model_name=str(args.model),
        default_language=str(args.language),
        device=str(args.device),
        compute_type=str(args.compute_type),
        options=options,
    )

    class Handler(BaseHTTPRequestHandler):
        server_version = "vodcasts-whisperx-worker/1"

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
            sys.stderr.write("[whisperx-worker] " + (fmt % args) + "\n")

        def do_GET(self) -> None:
            if self.path == "/health":
                self._send_json(200, {"ok": True, **service.model_info()})
                return
            self._send_json(404, {"ok": False, "error": "not_found"})

        def do_POST(self) -> None:
            if self.path != "/transcribe":
                self._send_json(404, {"ok": False, "error": "not_found"})
                return
            try:
                body = self._read_json()
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": f"invalid_json: {exc}"})
                return
            try:
                payload = service.submit(body)
                self._send_json(200, payload)
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})

    if args.warmup:
        info = service.warmup()
        print(
            f"[whisperx-worker] warmed model={info.get('model')} device={info.get('device')} language={info.get('language')}",
            flush=True,
        )
    else:
        info = service.model_info()
        print(
            f"[whisperx-worker] starting lazy server model={info.get('model')} device={info.get('device')} language={info.get('language')}",
            flush=True,
        )

    server = ThreadingHTTPServer((str(args.host), int(args.port)), Handler)
    server.daemon_threads = True
    print(f"[whisperx-worker] listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[whisperx-worker] shutting down", flush=True)
    finally:
        server.server_close()
        service.shutdown()


if __name__ == "__main__":
    main()
