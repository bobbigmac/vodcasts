"""Helpers for building subtitle files from backend transcript data."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

Segment = tuple[float, float, str]

_NO_SPACE_BEFORE = {".", ",", "!", "?", ";", ":", "%", ")", "]", "}", "'s"}
_NO_SPACE_AFTER = {"(", "[", "{", "$", "#", '"', "'"}


def _coerce_seconds(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def _join_tokens(tokens: list[str]) -> str:
    out = ""
    for token in tokens:
        token = _clean_text(token)
        if not token:
            continue
        if not out:
            out = token
            continue
        if token in _NO_SPACE_BEFORE or token.startswith("'"):
            out += token
        elif out[-1] in _NO_SPACE_AFTER:
            out += token
        else:
            out += " " + token
    return _clean_text(out)


def format_srt_timestamp(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0.0))
    millis = int(round(seconds * 1000.0))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def srt_to_vtt(srt_text: str) -> str:
    if not (srt_text or "").strip():
        return ""
    out: list[str] = ["WEBVTT", ""]
    for raw in srt_text.splitlines():
        line = raw.rstrip("\n")
        if line.strip().isdigit():
            continue
        if "-->" in line and "," in line:
            line = line.replace(",", ".")
        out.append(line)
    return "\n".join(out).rstrip() + "\n"


def normalize_segments(segments: list[Segment], *, min_duration_seconds: float = 0.35) -> list[Segment]:
    normalized: list[Segment] = []
    for start, end, text in segments:
        text = _clean_text(text)
        if not text:
            continue
        start = max(0.0, float(start or 0.0))
        end = max(start + float(min_duration_seconds), float(end or start))
        normalized.append((start, end, text))

    normalized.sort(key=lambda item: (item[0], item[1], item[2]))

    deduped: list[Segment] = []
    for start, end, text in normalized:
        if deduped and deduped[-1][2] == text and abs(deduped[-1][0] - start) < 0.05:
            prev_start, prev_end, prev_text = deduped[-1]
            deduped[-1] = (prev_start, max(prev_end, end), prev_text)
            continue
        deduped.append((start, end, text))
    return deduped


def segments_to_srt(segments: list[Segment]) -> str:
    out: list[str] = []
    for index, (start, end, text) in enumerate(normalize_segments(segments), start=1):
        out.append(f"{index}\n{format_srt_timestamp(start)} --> {format_srt_timestamp(end)}\n{text}\n")
    return "\n".join(out).rstrip() + ("\n" if out else "")


def _timestamp_text(entry: dict[str, Any]) -> str:
    for key in ("word", "text", "token", "value"):
        value = entry.get(key)
        if value is not None:
            return _clean_text(str(value))
    return ""


def _timestamp_start(entry: dict[str, Any]) -> float | None:
    for key in ("start", "start_time", "timestamp_start", "start_offset", "begin", "offset"):
        value = _coerce_seconds(entry.get(key))
        if value is not None:
            return value
    return None


def _timestamp_end(entry: dict[str, Any]) -> float | None:
    for key in ("end", "end_time", "timestamp_end", "end_offset", "stop"):
        value = _coerce_seconds(entry.get(key))
        if value is not None:
            return value
    return None


def segments_from_word_timestamps(
    timestamps: list[dict[str, Any]],
    *,
    max_gap_seconds: float = 0.85,
    max_segment_seconds: float = 6.5,
    max_words_per_segment: int = 14,
    max_chars_per_segment: int = 84,
) -> list[Segment]:
    words: list[tuple[float, float, str]] = []
    for entry in timestamps or []:
        if not isinstance(entry, dict):
            continue
        text = _timestamp_text(entry)
        start = _timestamp_start(entry)
        end = _timestamp_end(entry)
        if not text or start is None:
            continue
        if end is None or end < start:
            end = start
        words.append((float(start), float(end), text))

    if not words:
        return []

    words.sort(key=lambda item: (item[0], item[1], item[2]))

    segments: list[Segment] = []
    current_words: list[str] = []
    current_start: float | None = None
    current_end: float | None = None
    previous_end: float | None = None

    def flush() -> None:
        nonlocal current_words, current_start, current_end, previous_end
        if current_words and current_start is not None and current_end is not None:
            segments.append((current_start, current_end, _join_tokens(current_words)))
        current_words = []
        current_start = None
        current_end = None
        previous_end = None

    for start, end, text in words:
        proposed_words = current_words + [text]
        proposed_text = _join_tokens(proposed_words)
        gap = start - previous_end if previous_end is not None else 0.0
        span = end - (current_start if current_start is not None else start)
        punctuation_break = bool(current_words) and current_words[-1][-1:] in ".!?"

        if current_words and (
            gap > max_gap_seconds
            or span > max_segment_seconds
            or len(proposed_words) > max_words_per_segment
            or len(proposed_text) > max_chars_per_segment
            or (punctuation_break and gap > 0.3)
        ):
            flush()

        if current_start is None:
            current_start = start
        current_words.append(text)
        current_end = max(end, start)
        previous_end = max(end, start)

    flush()
    return normalize_segments(segments)


def estimate_audio_duration_seconds(audio_path: Path) -> float:
    try:
        import wave

        with wave.open(str(audio_path), "rb") as wav:
            frames = int(wav.getnframes() or 0)
            rate = int(wav.getframerate() or 0)
        return float(frames) / float(rate) if frames > 0 and rate > 0 else 0.0
    except Exception:
        return 0.0
