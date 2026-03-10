"""WhisperX backend: worker HTTP or CLI."""
from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from whisperx_worker_common import WorkerWhisperxOptions, parse_worker_extra_args


def _post_json(url: str, payload: dict[str, Any], *, timeout_seconds: int) -> dict[str, Any]:
    raw = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=raw,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=max(1, int(timeout_seconds))) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"worker http {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"worker unavailable: {e}") from e
    obj = json.loads(body.decode("utf-8", errors="replace"))
    if not isinstance(obj, dict):
        raise RuntimeError("worker returned non-object json")
    if obj.get("ok") is False:
        raise RuntimeError(str(obj.get("error") or "worker_error"))
    return obj


def _run(cmd: list[str]) -> None:
    p = subprocess.Popen(cmd, start_new_session=(os.name != "nt"))
    try:
        rc = p.wait()
        if rc != 0:
            raise subprocess.CalledProcessError(rc, cmd)
    except KeyboardInterrupt:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(int(p.pid)), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            try:
                os.killpg(int(p.pid), signal.SIGTERM)
            except Exception:
                p.terminate()
        raise


def _srt_to_vtt(srt: str) -> str:
    if not (srt or "").strip():
        return ""
    out: list[str] = ["WEBVTT", ""]
    for raw in (srt or "").splitlines():
        line = raw.rstrip("\n")
        if line.strip().isdigit():
            continue
        if "-->" in line and "," in line:
            line = line.replace(",", ".")
        out.append(line)
    return "\n".join(out).rstrip() + "\n"


def _ensure_non_empty(srt_text: str, vtt_text: str) -> None:
    effective = (vtt_text or "").strip() or (_srt_to_vtt(srt_text or "").strip() if (srt_text or "").strip() else "")
    if not effective:
        raise ValueError("whisperx produced empty transcript (no speech detected)")


class WhisperXBackend:
    """WhisperX via worker HTTP or CLI."""

    def __init__(
        self,
        *,
        worker_url: str = "",
        whisperx_cmd: str = "whisperx",
        model: str = "medium",
        device: str = "cuda",
        compute_type: str = "float16",
        extra_args: str = "",
    ) -> None:
        self.worker_url = str(worker_url or "").strip().rstrip("/")
        self.whisperx_cmd = str(whisperx_cmd or "whisperx")
        self.model = str(model or "medium").strip() or "medium"
        self.device = str(device or "cuda").strip() or "cuda"
        self.compute_type = str(compute_type or "float16").strip() or "float16"
        self.extra_args = str(extra_args or "").strip() or "--vad_method silero"

    def transcribe(self, audio_path: Path, language: str) -> tuple[str, str]:
        """Transcribe WAV to (srt, vtt). Raises if empty."""
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"audio not found: {audio_path}")
        lang = str(language or "en").strip() or "en"

        worker_options, worker_unsupported = parse_worker_extra_args(self.extra_args)

        if self.worker_url and not worker_unsupported:
            payload: dict[str, Any] = {
                "audio_path": str(audio_path),
                "model": self.model,
                "language": lang,
                "device": self.device,
                "compute_type": self.compute_type,
                "vad_method": str(worker_options.vad_method or "silero"),
                **worker_options.to_payload(),
            }
            res = _post_json(f"{self.worker_url}/transcribe", payload, timeout_seconds=600)
            srt = str(res.get("srt_text") or "")
            vtt = str(res.get("vtt_text") or "")
            if srt or vtt:
                _ensure_non_empty(srt, vtt)
                return srt, vtt or _srt_to_vtt(srt)

        # CLI fallback
        with tempfile.TemporaryDirectory(prefix="whisperx_out.") as td:
            out_dir = Path(td)
            cmd = [
                self.whisperx_cmd,
                str(audio_path),
                "--model", self.model,
                "--language", lang,
                "--device", self.device,
                "--compute_type", self.compute_type,
                "--output_dir", str(out_dir),
                "--output_format", "srt",
                "--verbose", "False",
            ]
            cmd += shlex.split(self.extra_args)
            _run(cmd)

            base = audio_path.stem
            srt_path = out_dir / f"{base}.srt"
            vtt_path = out_dir / f"{base}.vtt"
            if srt_path.exists():
                srt = srt_path.read_text(encoding="utf-8", errors="replace")
                _ensure_non_empty(srt, "")
                return srt, _srt_to_vtt(srt)
            if vtt_path.exists():
                vtt = vtt_path.read_text(encoding="utf-8", errors="replace")
                if vtt.strip():
                    _ensure_non_empty("", vtt)
                    return "", vtt
            any_srt = next(iter(out_dir.glob("*.srt")), None)
            if any_srt and any_srt.exists():
                srt = any_srt.read_text(encoding="utf-8", errors="replace")
                _ensure_non_empty(srt, "")
                return srt, _srt_to_vtt(srt)
        raise ValueError(f"whisperx produced no .srt/.vtt for {audio_path}")
