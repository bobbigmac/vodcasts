"""Parakeet TDT backend via parakeet-stream (phrase-level timestamps from stream)."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


def _ts(sec: float) -> str:
    """Format seconds as HH:MM:SS,mmm."""
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h:02d}:{m:02d}:{int(s):02d},{int(s % 1 * 1000):03d}"


def _segments_to_srt(segments: list[tuple[float, float, str]]) -> str:
    out = []
    for i, (start, end, text) in enumerate(segments, 1):
        if not (text or "").strip():
            continue
        out.append(f"{i}\n{_ts(start)} --> {_ts(end)}\n{text.strip()}\n")
    return "\n".join(out) + "\n" if out else ""


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


class ParakeetBackend:
    """Parakeet TDT via parakeet-stream. Uses stream() for phrase-level timestamps."""

    def __init__(
        self,
        *,
        device: str = "cuda",
        config: str = "balanced",
    ) -> None:
        self.device = str(device or "cuda").strip() or "cuda"
        self.config = str(config or "balanced").strip() or "balanced"

    def transcribe(self, audio_path: Path, language: str) -> tuple[str, str]:
        """Transcribe WAV to (srt, vtt). Raises if empty."""
        from parakeet_stream import Parakeet

        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"audio not found: {audio_path}")

        pk = Parakeet(device=self.device, config=self.config)
        raw_segments: list[tuple[float, str]] = []

        for chunk in pk.stream(str(audio_path)):
            if not chunk.is_final or not (chunk.text or "").strip():
                continue
            start = float(getattr(chunk, "timestamp_start", 0) or 0)
            text = (chunk.text or "").strip()
            raw_segments.append((start, text))

        segments: list[tuple[float, float, str]] = []
        for i, (start, text) in enumerate(raw_segments):
            end = raw_segments[i + 1][0] if i + 1 < len(raw_segments) else start + 5.0
            segments.append((start, end, text))

        if not segments:
            # Fallback: transcribe without stream (no timestamps)
            result = pk.transcribe(str(audio_path))
            text = (getattr(result, "text", None) or str(result) or "").strip()
            if not text:
                raise ValueError("parakeet produced empty transcript")
            segments = [(0.0, 5.0, text)]

        srt = _segments_to_srt(segments)
        vtt = _srt_to_vtt(srt)
        return srt, vtt
