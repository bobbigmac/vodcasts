"""Render vertical shorts by prepping clips with ffmpeg and composing with Remotion."""
from __future__ import annotations

import argparse
import json
import re
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


_SHORT_W = 1080
_SHORT_H = 1920
_OUT_FPS = 30
_ENC_PRESET = "fast"
_ENC_THREADS = 0
_SILENCE_LEAD_RE = re.compile(r"silence_start:\s*([0-9.]+)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*([0-9.]+)")


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
            detail = " | ".join(line.strip() for line in lines[-8:] if line.strip())[:800]
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
    p.add_argument("--no-subs", action="store_true", help="Skip subtitles/captions.")
    p.add_argument("--trim-silence", action="store_true", help="Trim leading/trailing silence from clips.")
    p.add_argument("--width", type=int, default=1080, help="Output width (default: 1080).")
    p.add_argument("--height", type=int, default=1920, help="Output height (default: 1920).")
    p.add_argument("--fps", type=int, default=30, help="Output fps (default: 30).")
    p.add_argument("--preset", default="fast", help="ffmpeg preset for prepared clips (default: fast).")
    p.add_argument("--threads", type=int, default=0, help="ffmpeg thread override; also used as Remotion concurrency when set.")
    p.add_argument("--context-top", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--context-bottom", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--register", default="", help="Path to used-clips.json to register.")
    p.add_argument("--min-clips", type=int, default=7, help="Require at least this many rendered clips before publishing output (default: 7).")
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
    """Detect leading/trailing silence and trim both audio/video by adjusting bounds."""
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


def _ffmpeg_prepare_short_clip(
    src: Path,
    start: float,
    end: float,
    out: Path,
    has_audio: bool = True,
) -> bool:
    dur = max(0.0, end - start)
    if dur <= 0.0:
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    vf = f"fps={_OUT_FPS},scale='min({_SHORT_W},iw)':-2:flags=lanczos,format=yuv420p"
    common = [
        "-c:v",
        "libx264",
        "-preset",
        _ENC_PRESET,
        "-crf",
        "20",
        "-movflags",
        "+faststart",
        str(out),
    ]
    if has_audio:
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            str(start),
            "-i",
            str(src),
            "-t",
            str(dur),
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-vf",
            vf,
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "2",
        ] + common
    else:
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            str(start),
            "-i",
            str(src),
            "-t",
            str(dur),
            "-map",
            "0:v:0",
            "-vf",
            vf,
            "-an",
        ] + common

    try:
        _run_logged_command(cmd, timeout=max(120, int(dur * 8)), label="clip preparation failed")
        return True
    except Exception as exc:
        print(f"[render_short] clip preparation failed: {exc}", file=sys.stderr)
        return False


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


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return slug or "short"


def _public_rel(path: Path) -> str:
    return path.relative_to(_REMOTION_PUBLIC).as_posix()


def _remotion_bin() -> list[str]:
    local_bin = _REPO_ROOT / "node_modules" / ".bin" / "remotion"
    local_bin_cmd = _REPO_ROOT / "node_modules" / ".bin" / "remotion.cmd"
    if local_bin.exists():
        return [str(local_bin)]
    if local_bin_cmd.exists():
        return [str(local_bin_cmd)]
    return ["npx", "remotion"]


def _render_with_remotion(manifest: dict, out_path: Path) -> None:
    props_json = json.dumps({"manifest": manifest}, ensure_ascii=False, separators=(",", ":"))
    total_duration = sum(float(clip.get("duration_sec") or 0) for clip in manifest.get("clips") or [])
    cmd = _remotion_bin() + [
        "render",
        str(_REMOTION_ENTRY),
        _REMOTION_COMPOSITION,
        str(out_path),
        f"--props={props_json}",
    ]
    _run_logged_command(
        _maybe_add_threads(cmd),
        timeout=max(900, int(max(30.0, total_duration) * 40)),
        label="Remotion render failed",
    )


def main() -> None:
    args = _parse_args()
    global _SHORT_W, _SHORT_H, _OUT_FPS, _ENC_PRESET, _ENC_THREADS
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
            duration_sec = max(0.0, trim_end - trim_start)
            if duration_sec <= 0.0:
                continue

            captions: list[dict[str, float | str]] = []
            if not args.no_subs:
                transcript_path = get_transcript_path(transcripts_root, feed, episode)
                if transcript_path:
                    subs_path = work_dir / f"clip_{index:02d}.vtt"
                    if clip_transcript_to_vtt(transcript_path, trim_start, trim_end, subs_path):
                        captions = _load_vtt_cues(subs_path)
                else:
                    print(f"[render_short] No transcript for {feed}/{episode}", file=sys.stderr)

            prepared_path = public_job_dir / f"clip_{index:02d}.mp4"
            if not _ffmpeg_prepare_short_clip(
                src=src_path,
                start=trim_start,
                end=trim_end,
                out=prepared_path,
                has_audio=has_audio,
            ):
                continue

            manifest_clips.append(
                {
                    "path": _public_rel(prepared_path),
                    "duration_sec": round(duration_sec, 3),
                    "quote": str(item.get("quote") or "").strip(),
                    "context": str(item.get("context") or "").strip(),
                    "decorators": str(item.get("decorators") or "").strip(),
                    "feed_title": str(item.get("feed_title") or feed).strip(),
                    "episode_title": str(item.get("episode_title") or episode).strip(),
                    "captions": captions,
                }
            )
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
            "clips": manifest_clips,
        }
        manifest_path = work_dir / "remotion_manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        _render_with_remotion(manifest, out_path)
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
