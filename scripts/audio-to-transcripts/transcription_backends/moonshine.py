"""Moonshine backend via moonshine-voice."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from moonshine_voice import Transcriber

from .subtitle_utils import estimate_audio_duration_seconds, normalize_segments, segments_to_srt, srt_to_vtt


class MoonshineBackend:
    """Moonshine via moonshine-voice."""

    def __init__(self, *, language: str = "en") -> None:
        self.language = str(language or "en").strip() or "en"
        self._transcriber: Transcriber | None = None
        self._loaded_language = ""

    def _get_transcriber(self, language: str) -> Any:
        language = str(language or self.language).strip() or "en"
        if self._transcriber is not None and self._loaded_language == language:
            return self._transcriber
        if self._transcriber is not None:
            self._transcriber.close()
            self._transcriber = None
        try:
            from moonshine_voice import Transcriber, get_model_for_language
        except ImportError as exc:
            raise RuntimeError(
                "Moonshine backend requires `moonshine-voice`. Run scripts/audio-to-transcripts/setup-venv.ps1."
            ) from exc
        model_path, model_arch = get_model_for_language(language)
        self._transcriber = Transcriber(model_path=model_path, model_arch=model_arch, update_interval=0.5)
        self._loaded_language = language
        return self._transcriber

    def transcribe(self, audio_path: Path, language: str) -> tuple[str, str]:
        """Transcribe WAV to (srt, vtt). Raises if empty."""
        from moonshine_voice import load_wav_file

        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"audio not found: {audio_path}")

        lang = str(language or self.language).strip() or "en"
        audio_data, sample_rate = load_wav_file(str(audio_path))
        transcript = self._get_transcriber(lang).transcribe_without_streaming(audio_data, sample_rate=sample_rate)

        segments: list[tuple[float, float, str]] = []
        for line in getattr(transcript, "lines", []) or []:
            text = (getattr(line, "text", None) or "").strip()
            if not text:
                continue
            start = float(getattr(line, "start_time", 0.0) or 0.0)
            duration = float(getattr(line, "duration", 0.0) or 0.0)
            segments.append((start, start + duration, text))

        if not segments:
            joined_text = " ".join(
                (getattr(line, "text", None) or "").strip()
                for line in (getattr(transcript, "lines", None) or [])
                if (getattr(line, "text", None) or "").strip()
            ).strip()
            if not joined_text:
                raise ValueError("moonshine produced empty transcript")
            duration = estimate_audio_duration_seconds(audio_path)
            segments = [(0.0, max(1.0, duration), joined_text)]

        srt = segments_to_srt(normalize_segments(segments))
        vtt = srt_to_vtt(srt)
        return srt, vtt
