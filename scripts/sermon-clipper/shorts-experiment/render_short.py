"""Render vertical shorts by prepping clips with ffmpeg and composing with Remotion."""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PARENT = Path(__file__).resolve().parent.parent
_THIS = Path(__file__).resolve().parent
_REMOTION_ENTRY = _THIS / "remotion" / "index.jsx"
_REMOTION_PUBLIC = _REPO_ROOT / "public"
_REMOTION_COMPOSITION = "SermonShort"
_MVE_LIB_PATH = _REPO_ROOT / "scripts" / "markdown-video-editor" / "_lib.py"
_AUTOCROP_RUNNER = _THIS / "autocrop_vertical_runner.py"
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_PARENT))

from _lib import (
    clip_id,
    clip_transcript_to_vtt,
    default_cache_dir,
    default_content_cache_dir,
    default_env,
    default_transcripts_root,
    get_episode_media_info,
    get_source_path,
    get_transcript_path,
    parse_short_script,
    remove_path,
    resolve_work_dir,
    reset_directory,
    save_used_clips,
)


def _load_mve_lib():
    spec = importlib.util.spec_from_file_location("markdown_video_editor_lib", _MVE_LIB_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load markdown-video-editor helpers from {_MVE_LIB_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_MVE = _load_mve_lib()

_SHORT_W = 1080
_SHORT_H = 1920
_OUT_FPS = 30
_ENC_PRESET = "fast"
_ENC_THREADS = 0
_AUTOCROP_REPO_URL = "https://github.com/kamilstanuch/Autocrop-vertical.git"
_AUTOCROP_REPO_DIR: Path | None = None
_SILENCE_LEAD_RE = re.compile(r"silence_start:\s*([0-9.]+)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*([0-9.]+)")
_NAME_SPLIT_RE = re.compile(r"\s*(?:\||//|-)\s*")


def _run_logged_command(cmd: list[str], timeout: int, label: str) -> None:
    run_cmd = cmd
    if cmd and cmd[0] == "ffmpeg" and "-loglevel" not in cmd:
        run_cmd = [cmd[0], "-hide_banner", "-loglevel", "error", "-nostats"]
        if _ENC_THREADS > 0:
            run_cmd.extend(
                [
                    "-threads",
                    str(_ENC_THREADS),
                    "-filter_threads",
                    str(_ENC_THREADS),
                    "-filter_complex_threads",
                    str(_ENC_THREADS),
                ]
            )
        run_cmd.extend(cmd[1:])
    with tempfile.NamedTemporaryFile(prefix="sermon-clipper-", suffix=".log", delete=False) as handle:
        log_path = Path(handle.name)
    try:
        with log_path.open("wb") as log_handle:
            subprocess.run(
                run_cmd,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=timeout,
            )
    except Exception as exc:
        detail = ""
        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            detail = " | ".join(line.strip() for line in lines[-8:] if line.strip())[:1000]
        except Exception:
            pass
        raise RuntimeError(f"{label}: {detail or exc}") from exc
    finally:
        remove_path(log_path)


def _maybe_add_threads(cmd: list[str]) -> list[str]:
    if _ENC_THREADS > 0 and cmd and cmd[0] not in {"ffmpeg", "ffprobe"} and "--concurrency" not in " ".join(cmd):
        cmd.append(f"--concurrency={_ENC_THREADS}")
    return cmd


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render vertical short from script.")
    p.add_argument("--script", required=True, help="Short script markdown path.")
    p.add_argument("--output", "-o", required=True, help="Output video path.")
    p.add_argument("--env", default="", help="Cache env.")
    p.add_argument("--work-dir", default="", help="Working directory override. Default is auto scratch under scripts/sermon-clipper/.work/.")
    p.add_argument("--content-cache", default="", help="Shared source video cache (default: cache/<env>/sermon-clipper/content).")
    p.add_argument("--no-download", action="store_true", help="Skip downloads and use only files already present in the shared content cache.")
    p.add_argument("--transcripts", default="", help="Transcripts root.")
    p.add_argument("--no-subs", action="store_true", help="Skip subtitle extraction and subtitle-track muxing.")
    p.add_argument("--trim-silence", action="store_true", help="Trim leading/trailing silence from clips.")
    p.add_argument("--no-compress", action="store_true", help="Disable interior gap compression.")
    p.add_argument("--width", type=int, default=1080, help="Output width (default: 1080).")
    p.add_argument("--height", type=int, default=1920, help="Output height (default: 1920).")
    p.add_argument("--fps", type=int, default=30, help="Output fps (default: 30).")
    p.add_argument("--preset", default="fast", help="ffmpeg preset for prepared clips (default: fast).")
    p.add_argument("--threads", type=int, default=0, help="ffmpeg thread override; also used as Remotion concurrency when set.")
    p.add_argument("--no-autocrop", action="store_true", help="Disable AutoCrop-Vertical and fall back to the legacy static crop.")
    p.add_argument("--register", default="", help="Path to used-clips.json to register.")
    p.add_argument("--min-clips", type=int, default=8, help="Require at least this many rendered clips before publishing output (default: 8).")
    p.add_argument("--keep-work", action="store_true", help="Keep scratch work directory and staged Remotion assets after a successful render.")
    return p.parse_args()


def _download_url(url: str, out_path: Path) -> bool:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-i", url, "-c", "copy", "-movflags", "+faststart", str(out_path)]
    try:
        _run_logged_command(cmd, timeout=600, label="download failed")
        return True
    except Exception as exc:
        print(f"[render_short] download failed: {exc}", file=sys.stderr)
        return False


def _source_has_video(path: Path) -> bool:
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "csv=p=0",
                str(path),
            ],
            capture_output=True,
            timeout=10,
        )
        return r.returncode == 0 and b"video" in (r.stdout or b"")
    except Exception:
        return False


def _source_has_audio(path: Path) -> bool:
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "csv=p=0",
                str(path),
            ],
            capture_output=True,
            timeout=10,
        )
        return r.returncode == 0 and b"audio" in (r.stdout or b"")
    except Exception:
        return False


def _detect_av_trim_bounds(
    src: Path,
    start: float,
    end: float,
    has_audio: bool,
    min_silence: float = 0.25,
    noise_db: int = -45,
) -> tuple[float, float]:
    if not has_audio:
        return start, end
    clip_dur = max(0.0, end - start)
    if clip_dur <= 1.0:
        return start, end

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-threads",
        "1",
        "-ss",
        str(start),
        "-t",
        str(clip_dur),
        "-i",
        str(src),
        "-vn",
        "-af",
        f"silencedetect=n={noise_db}dB:d={min_silence}",
        "-f",
        "null",
        "-",
    ]
    try:
        probe = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=min(120, max(15, int(clip_dur * 2))),
            check=False,
        )
    except Exception:
        return start, end

    log_text = (probe.stderr or "") + "\n" + (probe.stdout or "")
    leading_end: float | None = None
    trailing_start: float | None = None
    last_start: float | None = None
    last_end: float | None = None

    for raw_line in log_text.splitlines():
        line = raw_line.strip()
        m_start = _SILENCE_LEAD_RE.search(line)
        if m_start:
            last_start = float(m_start.group(1))
            continue
        m_end = _SILENCE_END_RE.search(line)
        if m_end:
            last_end = float(m_end.group(1))
            if last_start is not None and last_start <= 0.05 and leading_end is None:
                leading_end = last_end

    if last_start is not None and (last_end is None or last_end >= clip_dur - 0.05):
        trailing_start = last_start

    trim_lead = min(max(leading_end or 0.0, 0.0), clip_dur * 0.2)
    trim_trail = 0.0
    if trailing_start is not None:
        trim_trail = min(max(clip_dur - trailing_start, 0.0), clip_dur * 0.2)

    new_start = start + trim_lead
    new_end = end - trim_trail
    if new_end - new_start < max(1.5, clip_dur * 0.5):
        return start, end
    return new_start, new_end


def _ffmpeg_extract_raw_clip(src: Path, start: float, end: float, out: Path) -> bool:
    dur = max(0.0, end - start)
    if dur <= 0:
        return False
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(start),
        "-i",
        str(src),
        "-t",
        str(dur),
        "-c:v",
        "libx264",
        "-preset",
        _ENC_PRESET,
        "-crf",
        "18",
        "-c:a",
        "aac",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        str(out),
    ]
    try:
        _run_logged_command(cmd, timeout=max(120, int(dur * 8)), label="raw clip extraction failed")
        return True
    except Exception as exc:
        print(f"[render_short] raw clip extraction failed: {exc}", file=sys.stderr)
        return False


def _crop_filter() -> str:
    crop_w = "min(iw\\,ih*9/16)"
    crop_h = "min(ih\\,iw*16/9)"
    crop_x = f"(iw-{crop_w})/2"
    crop_y = f"max(0\\,(ih-{crop_h})*0.12)"
    return (
        f"crop=w='{crop_w}':h='{crop_h}':x='{crop_x}':y='{crop_y}',"
        f"scale={_SHORT_W}:{_SHORT_H}:flags=lanczos,fps={_OUT_FPS},format=yuv420p"
    )


def _build_keep_filter_complex(
    keep_ranges: list[tuple[float, float]],
    has_audio: bool,
    *,
    apply_static_crop: bool,
) -> str:
    parts: list[str] = []
    for index, (start, end) in enumerate(keep_ranges):
        parts.append(f"[0:v]trim=start={start:.6f}:end={end:.6f},setpts=PTS-STARTPTS[v{index}]")
        if has_audio:
            parts.append(f"[0:a]atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS[a{index}]")
    if has_audio:
        concat_inputs = "".join(f"[v{index}][a{index}]" for index in range(len(keep_ranges)))
        parts.append(f"{concat_inputs}concat=n={len(keep_ranges)}:v=1:a=1[vcat][acat]")
        if apply_static_crop:
            parts.append(f"[vcat]{_crop_filter()}[vout]")
    else:
        concat_inputs = "".join(f"[v{index}]" for index in range(len(keep_ranges)))
        parts.append(f"{concat_inputs}concat=n={len(keep_ranges)}:v=1:a=0[vcat]")
        if apply_static_crop:
            parts.append(f"[vcat]{_crop_filter()}[vout]")
    if not apply_static_crop:
        parts.append("[vcat]null[vout]")
    return ";\n".join(parts) + "\n"


def _apply_keep_ranges(
    src: Path,
    keep_ranges: list[tuple[float, float]],
    out: Path,
    has_audio: bool,
    *,
    apply_static_crop: bool,
) -> bool:
    if not keep_ranges:
        return False
    filter_script = out.with_suffix(".filter.txt")
    filter_script.write_text(
        _build_keep_filter_complex(keep_ranges, has_audio, apply_static_crop=apply_static_crop),
        encoding="utf-8",
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-filter_complex_script",
        str(filter_script),
        "-map",
        "[vout]",
    ]
    if has_audio:
        cmd.extend(["-map", "[acat]", "-c:a", "aac", "-ar", "48000", "-ac", "2"])
    else:
        cmd.append("-an")
    video_crf = "20" if apply_static_crop else "18"
    cmd.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            _ENC_PRESET,
            "-crf",
            video_crf,
            "-movflags",
            "+faststart",
            str(out),
        ]
    )
    try:
        _run_logged_command(cmd, timeout=300, label="clip compression failed")
        return True
    except Exception as exc:
        print(f"[render_short] clip compression failed: {exc}", file=sys.stderr)
        return False
    finally:
        remove_path(filter_script)


def _parse_vtt_timestamp(raw: str) -> float:
    parts = raw.strip().replace(",", ".").split(":")
    if len(parts) != 3:
        return 0.0
    hh, mm, ss = parts
    return int(hh) * 3600 + int(mm) * 60 + float(ss)


def _load_vtt_cues(vtt_path: Path) -> list[dict[str, float | str]]:
    if not vtt_path.exists():
        return []
    lines = [line.rstrip("\n") for line in vtt_path.read_text(encoding="utf-8", errors="replace").splitlines()]
    cues: list[dict[str, float | str]] = []
    idx = 0
    while idx < len(lines):
        line = lines[idx].strip()
        idx += 1
        if not line or line == "WEBVTT" or line.isdigit():
            continue
        if "-->" not in line:
            continue
        start_raw, end_raw = [part.strip() for part in line.split("-->", 1)]
        text_lines: list[str] = []
        while idx < len(lines) and lines[idx].strip():
            text_lines.append(lines[idx].strip())
            idx += 1
        text = " ".join(text_lines).strip()
        start_sec = _parse_vtt_timestamp(start_raw)
        end_sec = _parse_vtt_timestamp(end_raw)
        if text and end_sec > start_sec:
            cues.append({"start_sec": start_sec, "end_sec": end_sec, "text": text})
    return cues


def _merge_cues(cues: list[dict[str, float | str]]) -> list[dict[str, float | str]]:
    merged: list[dict[str, float | str]] = []
    for cue in sorted(cues, key=lambda item: (float(item["start_sec"]), float(item["end_sec"]))):
        if not merged:
            merged.append(cue)
            continue
        prev = merged[-1]
        if str(prev["text"]) == str(cue["text"]) and abs(float(cue["start_sec"]) - float(prev["end_sec"])) <= 0.04:
            prev["end_sec"] = cue["end_sec"]
            continue
        merged.append(cue)
    return merged


def _remap_cues_to_keep_ranges(
    cues: list[dict[str, float | str]],
    keep_ranges: list[tuple[float, float]],
) -> list[dict[str, float | str]]:
    remapped: list[dict[str, float | str]] = []
    output_cursor = 0.0
    for keep_start, keep_end in keep_ranges:
        for cue in cues:
            overlap_start = max(float(cue["start_sec"]), keep_start)
            overlap_end = min(float(cue["end_sec"]), keep_end)
            if overlap_end - overlap_start < 0.04:
                continue
            remapped.append(
                {
                    "start_sec": output_cursor + (overlap_start - keep_start),
                    "end_sec": output_cursor + (overlap_end - keep_start),
                    "text": str(cue["text"]),
                }
            )
        output_cursor += keep_end - keep_start
    return _merge_cues(remapped)


def _sec_to_srt(sec: float) -> str:
    sec = max(0.0, float(sec))
    hh = int(sec // 3600)
    mm = int((sec % 3600) // 60)
    ss = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    if ms >= 1000:
        ss += 1
        ms -= 1000
    if ss >= 60:
        mm += 1
        ss -= 60
    if mm >= 60:
        hh += 1
        mm -= 60
    return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"


def _write_srt(cues: list[dict[str, float | str]], path: Path) -> None:
    lines: list[str] = []
    for index, cue in enumerate(cues, start=1):
        lines.append(str(index))
        lines.append(f"{_sec_to_srt(float(cue['start_sec']))} --> {_sec_to_srt(float(cue['end_sec']))}")
        lines.append(str(cue["text"]))
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return slug or "short"


def _public_rel(path: Path) -> str:
    return path.relative_to(_REMOTION_PUBLIC).as_posix()


def _autocrop_quality_from_preset(preset: str) -> str:
    raw = str(preset or "").strip().lower()
    if raw in {"ultrafast", "superfast", "veryfast", "faster"}:
        return "fast"
    if raw in {"slow", "slower", "veryslow"}:
        return "high"
    return "balanced"


def _ensure_autocrop_repo() -> Path:
    repo_dir = _AUTOCROP_REPO_DIR
    if repo_dir is None:
        raise RuntimeError("AutoCrop-Vertical cache directory is not configured.")
    main_py = repo_dir / "main.py"
    if main_py.exists():
        return repo_dir
    git_bin = shutil.which("git")
    if not git_bin:
        raise RuntimeError("AutoCrop-Vertical requires git in PATH for first-time checkout.")
    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    clone_cmd = [git_bin, "clone", "--depth", "1", _AUTOCROP_REPO_URL, str(repo_dir)]
    _run_logged_command(clone_cmd, timeout=900, label="AutoCrop-Vertical checkout failed")
    if not main_py.exists():
        raise RuntimeError(f"AutoCrop-Vertical checkout is missing {main_py}")
    return repo_dir


def _media_duration_sec(path: Path) -> float:
    try:
        media = _MVE.probe_media(path)
        return float(media.get("duration_sec") or 0.0)
    except Exception:
        return 0.0


def _run_autocrop_vertical(src: Path, out: Path) -> bool:
    try:
        autocrop_repo = _ensure_autocrop_repo()
        quality = _autocrop_quality_from_preset(_ENC_PRESET)
        duration_sec = max(1.0, _media_duration_sec(src))
        cmd = [
            sys.executable,
            str(_AUTOCROP_RUNNER),
            "--repo-dir",
            str(autocrop_repo),
            "-i",
            str(src),
            "-o",
            str(out),
            "--ratio",
            "9:16",
            "--quality",
            quality,
        ]
        _run_logged_command(
            cmd,
            timeout=max(900, int(duration_sec * 90)),
            label="AutoCrop-Vertical failed",
        )
        return True
    except Exception as exc:
        print(f"[render_short] AutoCrop-Vertical failed: {exc}", file=sys.stderr)
        return False


def _remotion_bin() -> list[str]:
    local_bin = _REPO_ROOT / "node_modules" / ".bin" / "remotion"
    local_bin_cmd = _REPO_ROOT / "node_modules" / ".bin" / "remotion.cmd"
    if sys.platform.startswith("win") and local_bin_cmd.exists():
        return [str(local_bin_cmd)]
    if local_bin.exists():
        return [str(local_bin)]
    if local_bin_cmd.exists():
        return [str(local_bin_cmd)]
    if shutil.which("yarn"):
        return ["yarn", "remotion"]
    return ["npx", "remotion"]


def _render_with_remotion(manifest: dict, out_path: Path) -> None:
    with tempfile.NamedTemporaryFile(prefix="sermon-clipper-props-", suffix=".json", delete=False, mode="w", encoding="utf-8") as handle:
        props_path = Path(handle.name)
        json.dump({"manifest": manifest}, handle, ensure_ascii=False, separators=(",", ":"))
    total_duration = sum(float(clip.get("duration_sec") or 0) for clip in manifest.get("clips") or [])
    try:
        cmd = _remotion_bin() + [
            "render",
            str(_REMOTION_ENTRY),
            _REMOTION_COMPOSITION,
            str(out_path),
            f"--props={props_path}",
        ]
        _run_logged_command(
            _maybe_add_threads(cmd),
            timeout=max(900, int(max(30.0, total_duration) * 40)),
            label="Remotion render failed",
        )
    finally:
        remove_path(props_path)


def _mux_subtitle_track(video_path: Path, subtitle_path: Path) -> None:
    muxed_path = video_path.with_name(f"{video_path.stem}.muxed{video_path.suffix}")
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(subtitle_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-map",
        "1:0",
        "-c:v",
        "copy",
        "-c:a",
        "copy",
        "-c:s",
        "mov_text",
        "-metadata:s:s:0",
        "language=eng",
        "-disposition:s:0",
        "default",
        "-movflags",
        "+faststart",
        str(muxed_path),
    ]
    _run_logged_command(cmd, timeout=300, label="subtitle mux failed")
    remove_path(video_path)
    muxed_path.replace(video_path)


def _looks_like_name(part: str) -> bool:
    words = [w for w in re.findall(r"[A-Za-z']+", part) if w]
    if not (2 <= len(words) <= 4):
        return False
    return all(word[:1].isupper() for word in words if word and word[0].isalpha())


def _speaker_label(episode_title: str, feed_title: str) -> str:
    for candidate in _NAME_SPLIT_RE.split(episode_title or ""):
        candidate = candidate.strip()
        if _looks_like_name(candidate):
            return candidate
    for candidate in _NAME_SPLIT_RE.split(feed_title or ""):
        candidate = candidate.strip()
        if _looks_like_name(candidate):
            return candidate
    return ""


def _build_keep_ranges_for_clip(raw_clip_path: Path, compress: bool) -> list[tuple[float, float]]:
    media = _MVE.probe_media(raw_clip_path)
    duration_sec = float(media.get("duration_sec") or 0.0)
    if duration_sec <= 0:
        return []
    if not compress or not media.get("has_audio"):
        return [(0.0, duration_sec)]
    silences = _MVE.detect_silences(raw_clip_path, threshold_db=-34.0, min_silence_sec=0.22)
    audible_ranges = _MVE.invert_ranges(silences, duration_sec=duration_sec)
    if not audible_ranges:
        audible_ranges = [(0.0, duration_sec)]
    keep_ranges = _MVE.build_keep_ranges(
        audible_ranges=audible_ranges,
        duration_sec=duration_sec,
        trim_edges=True,
        compress_gaps=True,
        edge_pad_sec=0.05,
        interior_gap_sec=0.04,
    )
    return keep_ranges or [(0.0, duration_sec)]


def main() -> None:
    args = _parse_args()
    global _SHORT_W, _SHORT_H, _OUT_FPS, _ENC_PRESET, _ENC_THREADS, _AUTOCROP_REPO_DIR
    script_path = Path(args.script)
    if not script_path.exists():
        print(f"[render_short] Script not found: {script_path}", file=sys.stderr)
        sys.exit(1)
    if not _REMOTION_ENTRY.exists():
        print(f"[render_short] Remotion entry not found: {_REMOTION_ENTRY}", file=sys.stderr)
        sys.exit(1)

    env = (args.env or "").strip() or default_env()
    _SHORT_W = max(240, int(args.width))
    _SHORT_H = max(426, int(args.height))
    _OUT_FPS = max(12, int(args.fps))
    _ENC_PRESET = str(args.preset or "fast").strip() or "fast"
    _ENC_THREADS = max(0, int(args.threads))
    cache_dir = default_cache_dir(env)
    _AUTOCROP_REPO_DIR = cache_dir / "sermon-clipper" / "tools" / "autocrop-vertical"
    content_cache = Path(args.content_cache).resolve() if args.content_cache else default_content_cache_dir(env)
    content_cache.mkdir(parents=True, exist_ok=True)
    transcripts_root = Path(args.transcripts).resolve() if args.transcripts else default_transcripts_root()
    out_path = Path(args.output).resolve()
    work_dir, auto_work_dir = resolve_work_dir("shorts", out_path, args.work_dir)
    if auto_work_dir:
        reset_directory(work_dir)
    else:
        work_dir.mkdir(parents=True, exist_ok=True)

    parsed = parse_short_script(script_path)
    items = parsed.get("items") or []
    metadata = parsed.get("metadata") or {}
    theme = str(metadata.get("theme") or script_path.stem).strip()
    clip_items = [item for item in items if item.get("type") == "clip"]
    if len(clip_items) < max(2, int(args.min_clips)):
        print(
            f"[render_short] Script only contains {len(clip_items)} clips; need at least {args.min_clips}.",
            file=sys.stderr,
        )
        sys.exit(5)

    intro_text = ""
    outro_text = ""
    for item in items:
        if item["type"] == "intro":
            intro_text = str(item.get("text") or "").strip()[:120]
        elif item["type"] == "outro":
            outro_text = str(item.get("text") or "").strip()[:120]

    job_id = f"{_slugify(out_path.stem)}-{uuid.uuid4().hex[:8]}"
    public_job_dir = _REMOTION_PUBLIC / "sermon-shorts" / job_id
    public_job_dir.mkdir(parents=True, exist_ok=True)

    rendered_clip_ids: list[str] = []
    manifest_clips: list[dict] = []
    final_subtitle_cues: list[dict[str, float | str]] = []
    transition_sec = 0.0
    output_cursor = 0.0
    try:
        for index, item in enumerate(clip_items, start=1):
            feed = item.get("feed")
            episode = item.get("episode")
            start = float(item.get("start_sec") or 0)
            end = float(item.get("end_sec") or start)
            if not feed or not episode or end <= start:
                continue

            media_info = get_episode_media_info(cache_dir, feed, episode)
            if not media_info or not media_info.get("url"):
                print(f"[render_short] No media for {feed}/{episode}", file=sys.stderr)
                continue
            if not media_info.get("pickedIsVideo"):
                print(f"[render_short] Skipping {feed}/{episode}: audio-only enclosure", file=sys.stderr)
                continue

            src_path = get_source_path(content_cache, feed, episode)
            if not src_path.exists():
                if args.no_download:
                    print(f"[render_short] Missing cached source for {feed}/{episode}", file=sys.stderr)
                    continue
                if not _download_url(str(media_info["url"]), src_path):
                    continue
            if not _source_has_video(src_path):
                print(f"[render_short] Skipping {feed}/{episode}: no video stream", file=sys.stderr)
                continue

            has_audio = _source_has_audio(src_path)
            trim_start, trim_end = (
                _detect_av_trim_bounds(src_path, start, end, has_audio)
                if args.trim_silence
                else (start, end)
            )
            raw_duration = max(0.0, trim_end - trim_start)
            if raw_duration <= 0.0:
                continue

            raw_clip_path = work_dir / f"clip_{index:02d}_raw.mp4"
            if not _ffmpeg_extract_raw_clip(src_path, trim_start, trim_end, raw_clip_path):
                continue

            keep_ranges = _build_keep_ranges_for_clip(raw_clip_path, compress=not bool(args.no_compress))
            compressed_duration = sum(end_sec - start_sec for start_sec, end_sec in keep_ranges)
            if compressed_duration <= 0.0:
                continue

            cues: list[dict[str, float | str]] = []
            if not args.no_subs:
                transcript_path = get_transcript_path(transcripts_root, feed, episode)
                if transcript_path:
                    clip_vtt_path = work_dir / f"clip_{index:02d}.vtt"
                    if clip_transcript_to_vtt(transcript_path, trim_start, trim_end, clip_vtt_path):
                        cues = _load_vtt_cues(clip_vtt_path)
                else:
                    print(f"[render_short] No transcript for {feed}/{episode}", file=sys.stderr)
            remapped_cues = _remap_cues_to_keep_ranges(cues, keep_ranges) if cues else []

            prepared_path = public_job_dir / f"clip_{index:02d}.mp4"
            compressed_path = work_dir / f"clip_{index:02d}_compressed.mp4"
            if not _apply_keep_ranges(
                raw_clip_path,
                keep_ranges,
                compressed_path,
                has_audio=has_audio,
                apply_static_crop=bool(args.no_autocrop),
            ):
                continue
            if args.no_autocrop:
                compressed_path.replace(prepared_path)
            else:
                if not _run_autocrop_vertical(compressed_path, prepared_path):
                    continue

            episode_title = str(item.get("episode_title") or episode).strip()
            feed_title = str(item.get("feed_title") or feed).strip()
            speaker_label = _speaker_label(episode_title, feed_title)
            manifest_clips.append(
                {
                    "path": _public_rel(prepared_path),
                    "duration_sec": round(compressed_duration, 3),
                    "quote": str(item.get("quote") or "").strip(),
                    "context": str(item.get("context") or "").strip(),
                    "decorators": str(item.get("decorators") or "").strip(),
                    "feed_title": feed_title,
                    "episode_title": episode_title,
                    "speaker_label": speaker_label,
                }
            )
            for cue in remapped_cues:
                final_subtitle_cues.append(
                    {
                        "start_sec": output_cursor + float(cue["start_sec"]),
                        "end_sec": output_cursor + float(cue["end_sec"]),
                        "text": str(cue["text"]),
                    }
                )
            output_cursor += compressed_duration
            if index < len(clip_items):
                output_cursor += transition_sec
            rendered_clip_ids.append(clip_id(feed, episode, start))

        if len(manifest_clips) < max(2, int(args.min_clips)):
            print(
                f"[render_short] Only {len(manifest_clips)} clips prepared; need at least {args.min_clips}.",
                file=sys.stderr,
            )
            sys.exit(6)

        manifest = {
            "theme": theme,
            "intro": intro_text,
            "outro": outro_text,
            "width": _SHORT_W,
            "height": _SHORT_H,
            "fps": _OUT_FPS,
            "transition_sec": transition_sec,
            "clips": manifest_clips,
        }
        manifest_path = work_dir / "remotion_manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        _render_with_remotion(manifest, out_path)

        if not args.no_subs and final_subtitle_cues:
            final_sub_path = out_path.with_suffix(".srt")
            _write_srt(_merge_cues(final_subtitle_cues), final_sub_path)
            _mux_subtitle_track(out_path, final_sub_path)
    except Exception as exc:
        print(f"[render_short] {exc}", file=sys.stderr)
        print(f"[render_short] staged assets kept at {public_job_dir}", file=sys.stderr)
        sys.exit(4)

    print(f"[render_short] wrote {out_path}", file=sys.stderr)
    if args.register and rendered_clip_ids:
        reg_path = Path(args.register)
        save_used_clips(reg_path, set(rendered_clip_ids), video_title=out_path.stem)
        print(f"[render_short] registered {len(rendered_clip_ids)} clips", file=sys.stderr)

    if not args.keep_work:
        remove_path(public_job_dir)
    if auto_work_dir and not args.keep_work:
        remove_path(work_dir)


if __name__ == "__main__":
    main()
