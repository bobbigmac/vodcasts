"""Transcription backends: WhisperX, Parakeet, Moonshine.
Unified interface: transcribe(audio_path, language) -> (srt_text, vtt_text).
"""
from __future__ import annotations

from typing import Any, Protocol

from .base import TranscriberBackend


def get_backend(name: str, **kwargs: Any) -> TranscriberBackend:
    """Get a transcription backend by name. kwargs are passed to the backend constructor."""
    name = (name or "whisperx").strip().lower()
    if name == "whisperx":
        from .whisperx import WhisperXBackend
        return WhisperXBackend(**kwargs)
    if name == "parakeet":
        from .parakeet import ParakeetBackend
        return ParakeetBackend(**kwargs)
    if name == "moonshine":
        from .moonshine import MoonshineBackend
        return MoonshineBackend(**kwargs)
    raise ValueError(f"unknown backend: {name!r}. Choose: whisperx, parakeet, moonshine")


def list_backends() -> list[str]:
    return ["whisperx", "parakeet", "moonshine"]
