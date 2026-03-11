"""Shared helpers for markdown-video-editor features."""
from __future__ import annotations

import hashlib
import math
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORK_ROOT = Path(__file__).resolve().parent / ".work"

_SILENCE_START_RE = re.compile(r"silence_start:\s*([0-9.]+)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*([0-9.]+)\s*\|\s*silence_duration:\s*([0-9.]+)")
_FRAME_TIME_RE = re.compile(r"frame:\s*\d+\s+pts:\s*\d+\s+pts_time:\s*([0-9.]+)")
_SCENE_SCORE_RE = re.compile(r"lavfi\.scene_score=([0-9.]+)")
_RMS_LEVEL_RE = re.compile(r"lavfi\.astats\.Overall\.RMS_level=([^\s]+)")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def safe_slug(value: str, default: str = "item", max_len: int = 64) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (value or "").lower().strip()).strip("-")
    return (s[:max_len] or default).strip("-") or default


def remove_path(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def resolve_work_dir(kind: str, output_path: Path, explicit_work_dir: str = "") -> tuple[Path, bool]:
    if explicit_work_dir:
        return Path(explicit_work_dir).resolve(), False
    digest = hashlib.sha1(str(output_path.resolve()).encode("utf-8")).hexdigest()[:10]
    work_dir = _WORK_ROOT / safe_slug(kind, default="edit") / f"{safe_slug(output_path.stem, default='output')}-{digest}"
    return work_dir, True


def parse_markdown_sections(text: str) -> list[dict]:
    sections: list[dict] = []
    current_type: str | None = None
    current_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        line_stripped = line.strip()
        if line_stripped.startswith("## "):
            if current_type is not None:
                sections.append({"type": current_type, "content": "\n".join(current_lines).strip()})
            current_type = line_stripped[3:].strip().lower()
            current_lines = []
            continue
        if current_type is not None:
            current_lines.append(line)
    if current_type is not None:
        sections.append({"type": current_type, "content": "\n".join(current_lines).strip()})
    return sections


def parse_key_value_block(text: str) -> dict[str, str]:
    data: dict[str, str] = {}
    current_key: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if ":" in line and not line.startswith((" ", "\t")):
            key, value = line.split(":", 1)
            current_key = key.strip()
            data[current_key] = value.strip()
            continue
        if current_key:
            data[current_key] = f"{data[current_key]}\n{line.strip()}".strip()
    return data


def _to_float(value: str | float | int | None, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _to_bool(value: str | bool | None, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def sec_text(value: float) -> str:
    return f"{float(value):.3f}"


def probe_media(path: Path) -> dict:
    cmd = ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30)
    payload = json.loads(result.stdout or "{}")
    streams = payload.get("streams") or []
    fmt = payload.get("format") or {}
    duration = _to_float(fmt.get("duration"), 0.0)
    if duration <= 0:
        for stream in streams:
            duration = max(duration, _to_float(stream.get("duration"), 0.0))
    return {
        "duration_sec": max(0.0, duration),
        "has_video": any(str(stream.get("codec_type")) == "video" for stream in streams),
        "has_audio": any(str(stream.get("codec_type")) == "audio" for stream in streams),
        "streams": streams,
    }


def detect_silences(path: Path, threshold_db: float, min_silence_sec: float) -> list[tuple[float, float]]:
    cmd = ["ffmpeg", "-hide_banner", "-i", str(path), "-af", f"silencedetect=n={threshold_db}dB:d={min_silence_sec}", "-f", "null", "-"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode not in {0, 255}:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(stderr or "ffmpeg silencedetect failed")
    silences: list[tuple[float, float]] = []
    current_start: float | None = None
    for line in (result.stderr or "").splitlines():
        start_match = _SILENCE_START_RE.search(line)
        if start_match:
            current_start = _to_float(start_match.group(1), 0.0)
            continue
        end_match = _SILENCE_END_RE.search(line)
        if end_match:
            silence_end = _to_float(end_match.group(1), 0.0)
            silence_duration = _to_float(end_match.group(2), 0.0)
            silence_start = current_start
            if silence_start is None:
                silence_start = max(0.0, silence_end - silence_duration)
            if silence_end > silence_start:
                silences.append((silence_start, silence_end))
            current_start = None
    return silences


def detect_video_scenes(path: Path, threshold: float, min_gap_sec: float = 2.0) -> list[dict]:
    cmd = ["ffmpeg", "-hide_banner", "-i", str(path), "-filter:v", f"select='gt(scene,{threshold})',metadata=print:file=-", "-an", "-f", "null", "-"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode not in {0, 255}:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(stderr or "ffmpeg video scene detect failed")
    markers: list[dict] = []
    current_time: float | None = None
    last_time = -1e9
    output = "\n".join(part for part in (result.stdout or "", result.stderr or "") if part)
    for line in output.splitlines():
        time_match = _FRAME_TIME_RE.search(line)
        if time_match:
            current_time = _to_float(time_match.group(1), 0.0)
            continue
        score_match = _SCENE_SCORE_RE.search(line)
        if score_match and current_time is not None:
            score = _to_float(score_match.group(1), 0.0)
            if current_time - last_time >= max(0.0, min_gap_sec):
                markers.append({"kind": "boundary", "source_sec": current_time, "detector": "video_scene", "score": score, "score_unit": "scene_score", "reason": "visual_scene_change"})
                last_time = current_time
            current_time = None
    return markers


def detect_audio_changes(path: Path, window_sec: float = 0.5, delta_threshold_db: float = 8.0, min_gap_sec: float = 2.0) -> list[dict]:
    sample_count = max(1024, int(round(max(0.05, window_sec) * 48000)))
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-i",
        str(path),
        "-af",
        f"asetnsamples=n={sample_count}:pad=1,astats=metadata=1:reset=1,ametadata=print:file=-",
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode not in {0, 255}:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(stderr or "ffmpeg audio change detect failed")
    points: list[tuple[float, float]] = []
    current_time: float | None = None
    output = "\n".join(part for part in (result.stdout or "", result.stderr or "") if part)
    for line in output.splitlines():
        time_match = _FRAME_TIME_RE.search(line)
        if time_match:
            current_time = _to_float(time_match.group(1), 0.0)
            continue
        rms_match = _RMS_LEVEL_RE.search(line)
        if rms_match and current_time is not None:
            raw = rms_match.group(1).strip().lower()
            rms_db = -120.0 if raw in {"-inf", "inf", "nan"} else _to_float(raw, -120.0)
            points.append((current_time, rms_db))
            current_time = None
    markers: list[dict] = []
    last_level: float | None = None
    last_marker_time = -1e9
    for point_time, rms_db in points:
        if last_level is None:
            last_level = rms_db
            continue
        delta_db = abs(rms_db - last_level)
        if delta_db >= max(0.0, delta_threshold_db) and point_time - last_marker_time >= max(0.0, min_gap_sec):
            markers.append({"kind": "boundary", "source_sec": point_time, "detector": "audio_change", "score": delta_db, "score_unit": "delta_db", "reason": "audio_program_change"})
            last_marker_time = point_time
        last_level = rms_db
    return markers


def normalize_ranges(ranges: list[tuple[float, float]], duration_sec: float | None = None, min_span_sec: float = 0.001) -> list[tuple[float, float]]:
    cleaned: list[tuple[float, float]] = []
    for start, end in ranges:
        s = _to_float(start, 0.0)
        e = _to_float(end, 0.0)
        if duration_sec is not None:
            s = max(0.0, min(duration_sec, s))
            e = max(0.0, min(duration_sec, e))
        if e - s >= min_span_sec:
            cleaned.append((s, e))
    cleaned.sort(key=lambda item: (item[0], item[1]))
    merged: list[list[float]] = []
    for start, end in cleaned:
        if not merged or start > merged[-1][1] + min_span_sec:
            merged.append([start, end])
            continue
        merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def invert_ranges(ranges: list[tuple[float, float]], duration_sec: float) -> list[tuple[float, float]]:
    normalized = normalize_ranges(ranges, duration_sec=duration_sec)
    keep: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in normalized:
        if start > cursor:
            keep.append((cursor, start))
        cursor = max(cursor, end)
    if duration_sec > cursor:
        keep.append((cursor, duration_sec))
    return normalize_ranges(keep, duration_sec=duration_sec)


def build_keep_ranges(audible_ranges: list[tuple[float, float]], duration_sec: float, trim_edges: bool, compress_gaps: bool, edge_pad_sec: float, interior_gap_sec: float) -> list[tuple[float, float]]:
    ranges = normalize_ranges(audible_ranges, duration_sec=duration_sec)
    if not ranges:
        return [] if duration_sec <= 0 else [(0.0, duration_sec)]
    starts = [0.0] * len(ranges)
    ends = [0.0] * len(ranges)
    starts[0] = max(0.0, ranges[0][0] - max(0.0, edge_pad_sec)) if trim_edges else 0.0
    ends[-1] = min(duration_sec, ranges[-1][1] + max(0.0, edge_pad_sec)) if trim_edges else duration_sec
    for index in range(len(ranges) - 1):
        gap_start = ranges[index][1]
        gap_end = ranges[index + 1][0]
        gap = max(0.0, gap_end - gap_start)
        keep_gap = min(gap, max(0.0, interior_gap_sec if compress_gaps else gap))
        ends[index] = gap_start + (keep_gap / 2.0)
        starts[index + 1] = gap_end - (keep_gap / 2.0)
    if len(ranges) == 1:
        ends[0] = min(duration_sec, ranges[0][1] + max(0.0, edge_pad_sec)) if trim_edges else duration_sec
    final_ranges = [(starts[index], ends[index]) for index in range(len(ranges))]
    return normalize_ranges(final_ranges, duration_sec=duration_sec)


def build_actions(keep_ranges: list[tuple[float, float]], duration_sec: float) -> list[dict]:
    normalized_keeps = normalize_ranges(keep_ranges, duration_sec=duration_sec)
    actions: list[dict] = []
    output_cursor = 0.0
    source_cursor = 0.0
    for keep_index, (start, end) in enumerate(normalized_keeps, 1):
        if start > source_cursor:
            actions.append({"kind": "cut", "source_start_sec": source_cursor, "source_end_sec": start, "duration_sec": start - source_cursor, "reason": "removed_gap", "label": f"cut_{keep_index:02d}"})
        keep_duration = end - start
        actions.append({"kind": "keep", "source_start_sec": start, "source_end_sec": end, "output_start_sec": output_cursor, "output_end_sec": output_cursor + keep_duration, "duration_sec": keep_duration, "reason": "audible_region", "label": f"keep_{keep_index:02d}"})
        output_cursor += keep_duration
        source_cursor = end
    if source_cursor < duration_sec:
        actions.append({"kind": "cut", "source_start_sec": source_cursor, "source_end_sec": duration_sec, "duration_sec": duration_sec - source_cursor, "reason": "removed_gap", "label": f"cut_{len(normalized_keeps) + 1:02d}"})
    return actions


def _sorted_markers(markers: list[dict]) -> list[dict]:
    return sorted(markers or [], key=lambda item: (_to_float(item.get("source_sec"), 0.0), str(item.get("detector") or "")))


def write_edit_plan(path: Path, *, title: str, metadata: dict, summary: str, actions: list[dict], markers: list[dict] | None = None) -> None:
    lines = [f"# Edit Plan: {title}", "", "## metadata"]
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, bool):
            text = "true" if value else "false"
        elif isinstance(value, float):
            text = sec_text(value)
        else:
            text = str(value)
        lines.append(f"{key}: {text}")
    lines.extend(["", "## summary", summary.strip(), ""])
    for action in actions:
        lines.append("## action")
        for key in ("kind", "label", "source_start_sec", "source_end_sec", "output_start_sec", "output_end_sec", "duration_sec", "reason"):
            if key not in action or action.get(key) in {"", None}:
                continue
            value = action[key]
            text = sec_text(value) if isinstance(value, float) else str(value)
            lines.append(f"{key}: {text}")
        lines.append("")
    for marker_index, marker in enumerate(_sorted_markers(markers or []), 1):
        lines.append("## marker")
        marker_label = str(marker.get("label") or "").strip() or f"marker_{marker_index:02d}"
        for key, value in (
            ("kind", marker.get("kind") or "boundary"),
            ("label", marker_label),
            ("source_sec", marker.get("source_sec")),
            ("detector", marker.get("detector")),
            ("score", marker.get("score")),
            ("score_unit", marker.get("score_unit")),
            ("reason", marker.get("reason")),
        ):
            if value in {"", None}:
                continue
            text = sec_text(value) if isinstance(value, float) else str(value)
            lines.append(f"{key}: {text}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def parse_edit_plan(plan_path: Path) -> dict:
    text = plan_path.read_text(encoding="utf-8", errors="replace")
    sections = parse_markdown_sections(text)
    metadata: dict[str, str] = {}
    summary = ""
    actions: list[dict] = []
    markers: list[dict] = []
    for section in sections:
        section_type = str(section.get("type") or "").strip().lower()
        content = str(section.get("content") or "")
        if section_type == "metadata":
            metadata = parse_key_value_block(content)
            continue
        if section_type == "summary":
            summary = content.strip()
            continue
        if section_type == "action":
            kv = parse_key_value_block(content)
            actions.append({"kind": str(kv.get("kind") or "").strip().lower(), "label": str(kv.get("label") or "").strip(), "source_start_sec": _to_float(kv.get("source_start_sec"), 0.0), "source_end_sec": _to_float(kv.get("source_end_sec"), 0.0), "output_start_sec": _to_float(kv.get("output_start_sec"), 0.0), "output_end_sec": _to_float(kv.get("output_end_sec"), 0.0), "duration_sec": _to_float(kv.get("duration_sec"), 0.0), "reason": str(kv.get("reason") or "").strip()})
            continue
        if section_type == "marker":
            kv = parse_key_value_block(content)
            markers.append({"kind": str(kv.get("kind") or "").strip().lower(), "label": str(kv.get("label") or "").strip(), "source_sec": _to_float(kv.get("source_sec"), 0.0), "detector": str(kv.get("detector") or "").strip(), "score": _to_float(kv.get("score"), math.nan), "score_unit": str(kv.get("score_unit") or "").strip(), "reason": str(kv.get("reason") or "").strip()})
    return {"metadata": metadata, "summary": summary, "actions": actions, "markers": markers}


def keep_ranges_from_actions(actions: list[dict], duration_sec: float | None = None) -> list[tuple[float, float]]:
    keep_ranges: list[tuple[float, float]] = []
    for action in actions:
        if str(action.get("kind") or "").strip().lower() != "keep":
            continue
        start = _to_float(action.get("source_start_sec"), 0.0)
        end = _to_float(action.get("source_end_sec"), 0.0)
        if end > start:
            keep_ranges.append((start, end))
    return normalize_ranges(keep_ranges, duration_sec=duration_sec)


def metadata_bool(metadata: dict, key: str, default: bool = False) -> bool:
    return _to_bool(metadata.get(key), default=default)


def metadata_float(metadata: dict, key: str, default: float = 0.0) -> float:
    return _to_float(metadata.get(key), default=default)
