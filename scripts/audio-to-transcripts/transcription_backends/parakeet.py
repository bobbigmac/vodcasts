"""Parakeet TDT backend via parakeet-stream."""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from parakeet_stream import Parakeet

from .subtitle_utils import coerce_subtitle_output, estimate_audio_duration_seconds, segments_from_word_timestamps, segments_to_srt, srt_to_vtt


def _ensure_utf8_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None or not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


class ParakeetBackend:
    """Parakeet TDT via parakeet-stream."""

    def __init__(
        self,
        *,
        device: str = "cuda",
        config: str = "balanced",
        model_name: str = "nvidia/parakeet-tdt-0.6b-v3",
    ) -> None:
        self.device = str(device or "cuda").strip() or "cuda"
        self.config = str(config or "balanced").strip() or "balanced"
        self.model_name = str(model_name or "nvidia/parakeet-tdt-0.6b-v3").strip() or "nvidia/parakeet-tdt-0.6b-v3"
        self._model: Parakeet | None = None
        self._lock = threading.Lock()

    def _get_model(self) -> Any:
        if self._model is not None:
            return self._model
        _ensure_utf8_stdio()
        try:
            from parakeet_stream import Parakeet
        except ImportError as exc:
            raise RuntimeError(
                "Parakeet backend requires `parakeet-stream`. Run scripts/audio-to-transcripts/setup-venv.ps1."
            ) from exc
        self._model = Parakeet(
            model_name=self.model_name,
            device=self.device,
            config=self.config,
            lazy=True,
        )
        return self._model

    def transcribe(self, audio_path: Path, language: str) -> tuple[str, str]:
        """Transcribe WAV to (srt, vtt). Raises if empty."""
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"audio not found: {audio_path}")

        with self._lock:
            result = self._get_model().transcribe(str(audio_path), timestamps=True, _quiet=True)
            text = (getattr(result, "text", None) or "").strip()
            if not text:
                raise ValueError("parakeet produced empty transcript")

            segments = segments_from_word_timestamps(list(getattr(result, "timestamps", None) or []))
            if not segments:
                duration = float(getattr(result, "duration", 0.0) or 0.0) or estimate_audio_duration_seconds(audio_path)
                segments = [(0.0, max(1.0, duration), text)]

            srt = segments_to_srt(segments)
            vtt = srt_to_vtt(srt)
            return coerce_subtitle_output(srt, vtt)
