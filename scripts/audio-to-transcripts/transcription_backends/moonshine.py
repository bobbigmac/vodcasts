"""Moonshine backend via moonshine-voice (phrase-level timestamps from Transcriber)."""
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


class MoonshineBackend:
    """Moonshine via moonshine-voice. Uses Transcriber + stream for phrase-level timestamps."""

    def __init__(self, *, language: str = "en") -> None:
        self.language = str(language or "en").strip() or "en"

    def transcribe(self, audio_path: Path, language: str) -> tuple[str, str]:
        """Transcribe WAV to (srt, vtt). Raises if empty."""
        from moonshine_voice import (
            Transcriber,
            TranscriptEventListener,
            get_model_for_language,
            load_wav_file,
        )

        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"audio not found: {audio_path}")

        lang = str(language or self.language).strip() or "en"
        model_path, model_arch = get_model_for_language(lang)
        transcriber = Transcriber(model_path=model_path, model_arch=model_arch)
        stream = transcriber.create_stream(update_interval=0.5)
        stream.start()

        segments: list[tuple[float, float, str]] = []

        class Listener(TranscriptEventListener):
            def on_line_completed(self, event):
                line = event.line
                start = getattr(line, "start_time", 0) or 0
                duration = getattr(line, "duration", 3.0) or 3.0
                end = start + duration
                text = (getattr(line, "text", None) or "").strip()
                if text:
                    segments.append((float(start), float(end), text))

        listener = Listener()
        stream.add_listener(listener)

        chunk_duration = 0.1
        audio_data, sample_rate = load_wav_file(str(audio_path))
        chunk_size = int(chunk_duration * sample_rate)
        for i in range(0, len(audio_data), chunk_size):
            chunk = audio_data[i : i + chunk_size]
            stream.add_audio(chunk, sample_rate)

        stream.stop()
        stream.close()

        if not segments:
            raise ValueError("moonshine produced empty transcript")

        srt = _segments_to_srt(segments)
        vtt = _srt_to_vtt(srt)
        return srt, vtt
