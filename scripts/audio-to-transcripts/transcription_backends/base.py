"""Base interface for transcription backends."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class TranscriberBackend(Protocol):
    """Transcribe audio to SRT/VTT. All backends implement this interface."""

    def transcribe(self, audio_path: Path, language: str) -> tuple[str, str]:
        """Transcribe audio file (16kHz mono WAV) to subtitles.
        Returns (srt_text, vtt_text). Raises if no speech detected.
        """
        ...
