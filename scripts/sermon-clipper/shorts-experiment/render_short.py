"""Render vertical short from script: split screen (speaker + context), subtitles."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PARENT = Path(__file__).resolve().parent.parent
_THIS = Path(__file__).resolve().parent
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
from text_overlay import render_card, render_context_panel


_SHORT_W = 1080
_SHORT_H = 1920
_PANEL_H = 960
_OUT_FPS = 30
_ENC_PRESET = "fast"
_ENC_THREADS = 0
_SILENCE_LEAD_RE = re.compile(r"silence_start:\s*([0-9.]+)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*([0-9.]+)")


def _run_media_command(cmd: list[str], timeout: int, label: str) -> None:
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
            detail = " | ".join(line.strip() for line in lines[-4:] if line.strip())[:400]
        except Exception:
            pass
        raise RuntimeError(f"{label}: {detail or exc}") from exc
    finally:
        remove_path(log_path)


def _maybe_add_threads(cmd: list[str]) -> list[str]:
    if _ENC_THREADS > 0 and cmd and cmd[0] != "ffmpeg" and "-threads" not in cmd:
        cmd.extend(["-threads", str(_ENC_THREADS)])
    return cmd


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render vertical short from script.")
    p.add_argument("--script", required=True, help="Short script markdown path.")
    p.add_argument("--output", "-o", required=True, help="Output video path.")
    p.add_argument("--env", default="", help="Cache env.")
    p.add_argument("--work-dir", default="", help="Working directory override. Default is auto scratch under scripts/sermon-clipper/.work/.")
    p.add_argument("--content-cache", default="", help="Shared source video cache (default: cache/<env>/sermon-clipper/content).")
    p.add_argument("--intro-duration", type=float, default=1.5, help="Intro card seconds (default: 1.5).")
    p.add_argument("--outro-duration", type=float, default=1.5, help="Outro card seconds (default: 1.5).")
    p.add_argument("--no-download", action="store_true", help="Skip downloads and use only files already present in the shared content cache.")
    p.add_argument("--transcripts", default="", help="Transcripts root.")
    p.add_argument("--no-subs", action="store_true", help="Skip subtitles.")
    p.add_argument("--trim-silence", action="store_true", help="Trim leading/trailing silence from clips.")
    p.add_argument("--width", type=int, default=1080, help="Output width (default: 1080).")
    p.add_argument("--height", type=int, default=1920, help="Output height (default: 1920).")
    p.add_argument("--fps", type=int, default=30, help="Output fps (default: 30).")
    p.add_argument("--preset", default="fast", help="x264 preset (default: fast).")
    p.add_argument("--threads", type=int, default=0, help="ffmpeg encoder threads override (default: auto).")
    p.add_argument("--context-top", action="store_true", default=True, help="Context panel on top (default).")
    p.add_argument("--context-bottom", action="store_false", dest="context_top", help="Context panel on bottom.")
    p.add_argument("--register", default="", help="Path to used-clips.json to register.")
    p.add_argument("--min-clips", type=int, default=2, help="Require at least this many rendered clips before publishing output (default: 2).")
    p.add_argument("--keep-work", action="store_true", help="Keep scratch work directory after a successful render.")
    return p.parse_args()


def _download_url(url: str, out_path: Path) -> bool:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-i", url, "-c", "copy", "-movflags", "+faststart", str(out_path)]
    try:
        _run_media_command(cmd, timeout=600, label="download failed")
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


def _ffmpeg_subtitles_path(vtt_path: Path) -> str:
    s = str(vtt_path.resolve()).replace("\\", "/")
    return s.replace(":", "\\:")


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

    if last_start is not None:
        if last_end is None or last_end >= clip_dur - 0.05:
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


def _ffmpeg_text_card(duration: float, out: Path, card_img_path: Path) -> bool:
    if not card_img_path.exists():
        return False
    cmd = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        str(card_img_path),
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=48000:cl=mono",
        "-t",
        str(duration),
        "-vf",
        f"scale={_SHORT_W}:{_SHORT_H}:force_original_aspect_ratio=decrease,pad={_SHORT_W}:{_SHORT_H}:(ow-iw)/2:(oh-ih)/2,fps={_OUT_FPS}",
        "-c:v",
        "libx264",
        "-preset",
        _ENC_PRESET,
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(_OUT_FPS),
        "-c:a",
        "aac",
        "-ar",
        "48000",
        "-ac",
        "1",
        "-shortest",
        "-f",
        "mp4",
        "-movflags",
        "+faststart",
        str(out),
    ]
    try:
        _run_media_command(_maybe_add_threads(cmd), timeout=60, label="text card failed")
        return True
    except Exception as exc:
        print(f"[render_short] text card failed: {exc}", file=sys.stderr)
        return False


def _ffmpeg_extract_short_clip(
    src: Path,
    start: float,
    end: float,
    out: Path,
    context_img_path: Path,
    subtitles_path: Path | None,
    context_top: bool,
    trim_silence: bool = False,
    has_audio: bool = True,
) -> bool:
    """Extract clip and compose vertical: speaker half + context panel."""
    trim_start, trim_end = _detect_av_trim_bounds(src, start, end, has_audio) if trim_silence else (start, end)
    dur = trim_end - trim_start
    if dur <= 0:
        return False
    if context_top:
        filter_complex = (
            f"[1:v]scale={_SHORT_W}:{_PANEL_H},fps={_OUT_FPS}[ctx];"
            f"[0:v]scale={_SHORT_W}:{_PANEL_H}:force_original_aspect_ratio=increase,crop={_SHORT_W}:{_PANEL_H},fps={_OUT_FPS}[vid];"
            f"[ctx][vid]vstack=inputs=2[stack]"
        )
        sub_style = "FontSize=22,PrimaryColour=&HFFFFFF&,OutlineColour=&H000000&,Outline=2,MarginV=80"
    else:
        filter_complex = (
            f"[0:v]scale={_SHORT_W}:{_PANEL_H}:force_original_aspect_ratio=increase,crop={_SHORT_W}:{_PANEL_H},fps={_OUT_FPS}[vid];"
            f"[1:v]scale={_SHORT_W}:{_PANEL_H},fps={_OUT_FPS}[ctx];"
            f"[vid][ctx]vstack=inputs=2[stack]"
        )
        sub_style = "FontSize=22,PrimaryColour=&HFFFFFF&,OutlineColour=&H000000&,Outline=2,Alignment=8,MarginV=400"

    if subtitles_path and subtitles_path.exists():
        sub_esc = _ffmpeg_subtitles_path(subtitles_path)
        filter_complex += f";[stack]subtitles=filename='{sub_esc}':force_style='{sub_style}'[out]"
    else:
        filter_complex += ";[stack]format=yuv420p[out]"
    common = [
        "-c:v",
        "libx264",
        "-preset",
        _ENC_PRESET,
        "-crf",
        "22",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(_OUT_FPS),
        "-c:a",
        "aac",
        "-ar",
        "48000",
        "-ac",
        "1",
        "-f",
        "mp4",
        "-movflags",
        "+faststart",
        str(out),
    ]

    if has_audio:
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            str(trim_start),
            "-i",
            str(src),
            "-loop",
            "1",
            "-i",
            str(context_img_path),
            "-t",
            str(dur),
            "-filter_complex",
            filter_complex,
            "-map",
            "[out]",
            "-map",
            "0:a?",
        ] + common
    else:
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            str(trim_start),
            "-i",
            str(src),
            "-loop",
            "1",
            "-i",
            str(context_img_path),
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=mono",
            "-t",
            str(dur),
            "-filter_complex",
            filter_complex,
            "-map",
            "[out]",
            "-map",
            "2:a",
            "-shortest",
        ] + common

    try:
        _run_media_command(_maybe_add_threads(cmd), timeout=300, label="extract failed")
        return True
    except RuntimeError:
        if has_audio:
            cmd_alt = [
                "ffmpeg",
                "-y",
                "-ss",
                str(start),
                "-i",
                str(src),
                "-loop",
                "1",
                "-i",
                str(context_img_path),
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=48000:cl=mono",
                "-t",
                str(dur),
                "-filter_complex",
                filter_complex,
                "-map",
                "[out]",
                "-map",
                "2:a",
                "-shortest",
            ] + common
            try:
                _run_media_command(_maybe_add_threads(cmd_alt), timeout=300, label="extract failed")
                return True
            except Exception as exc:
                print(f"[render_short] extract failed: {exc}", file=sys.stderr)
                return False
        print("[render_short] extract failed", file=sys.stderr)
        return False
    except Exception as exc:
        print(f"[render_short] extract failed: {exc}", file=sys.stderr)
        return False


def _ffmpeg_concat(files: list[Path], out: Path, list_path: Path) -> bool:
    with open(list_path, "w", encoding="utf-8") as handle:
        for path in files:
            handle.write(f"file '{path.resolve()}'\n")
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_path),
        "-c:v",
        "libx264",
        "-preset",
        _ENC_PRESET,
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(_OUT_FPS),
        "-c:a",
        "aac",
        "-ar",
        "48000",
        "-ac",
        "1",
        "-f",
        "mp4",
        "-movflags",
        "+faststart",
        str(out),
    ]
    try:
        _run_media_command(_maybe_add_threads(cmd), timeout=120, label="concat failed")
        return True
    except Exception as exc:
        print(f"[render_short] concat failed: {exc}", file=sys.stderr)
        return False


def main() -> None:
    args = _parse_args()
    global _SHORT_W, _SHORT_H, _PANEL_H, _OUT_FPS, _ENC_PRESET, _ENC_THREADS
    script_path = Path(args.script)
    if not script_path.exists():
        print(f"[render_short] Script not found: {script_path}", file=sys.stderr)
        sys.exit(1)

    env = (args.env or "").strip() or default_env()
    _SHORT_W = max(240, int(args.width))
    _SHORT_H = max(426, int(args.height))
    _PANEL_H = max(120, _SHORT_H // 2)
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
    clip_count = sum(1 for item in items if item.get("type") == "clip")
    if clip_count < 2:
        print("[render_short] Need at least 2 clips. Single-clip shorts are not acceptable.", file=sys.stderr)
        sys.exit(5)

    out_segments: list[Path] = []
    rendered_clip_ids: list[str] = []
    rendered_clip_files: list[Path] = []
    intro_text = ""
    outro_text = ""

    for index, item in enumerate(items):
        if item["type"] == "intro":
            intro_text = item.get("text", "")[:120]
            continue
        if item["type"] == "outro":
            outro_text = item.get("text", "")[:120]
            continue
        if item["type"] != "clip":
            continue

        feed = item.get("feed")
        episode = item.get("episode")
        start = float(item.get("start_sec") or 0)
        end = float(item.get("end_sec") or start)
        context = str(item.get("context") or "").replace("\n", " ").strip()
        decorators = str(item.get("decorators") or "").replace("\n", " ").strip()
        feed_title = str(item.get("feed_title") or feed or "").strip()
        if not feed or not episode or end <= start:
            continue

        media_info = get_episode_media_info(cache_dir, feed, episode)
        if not media_info or not media_info.get("url"):
            print(f"[render_short] No media for {feed}/{episode}", file=sys.stderr)
            continue
        if not media_info.get("pickedIsVideo"):
            print(f"[render_short] Skipping {feed}/{episode}: audio-only enclosure (video required)", file=sys.stderr)
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

        context_text = context[:120] if context else "A concise clip worth hearing in full context."
        if decorators:
            context_text = f"{context_text} {decorators[:36]}"
        context_img = work_dir / f"clip_{index:02d}_ctx.png"
        footer = feed_title[:44]
        if not render_context_panel(
            context_text,
            _SHORT_W,
            _PANEL_H,
            context_img,
            label="Why it matters",
            footer=footer,
        ):
            continue

        subs_path: Path | None = None
        if not args.no_subs:
            transcript_path = get_transcript_path(transcripts_root, feed, episode)
            if transcript_path:
                subs_path = work_dir / f"clip_{index:02d}_subs.vtt"
                if not clip_transcript_to_vtt(transcript_path, start, end, subs_path):
                    subs_path = None
            else:
                print(f"[render_short] No transcript for {feed}/{episode}", file=sys.stderr)

        clip_path = work_dir / f"clip_{index:02d}.mp4"
        has_audio = _source_has_audio(src_path)
        if _ffmpeg_extract_short_clip(
            src=src_path,
            start=start,
            end=end,
            out=clip_path,
            context_img_path=context_img,
            subtitles_path=subs_path,
            context_top=bool(args.context_top),
            trim_silence=bool(args.trim_silence),
            has_audio=has_audio,
        ):
            rendered_clip_files.append(clip_path)
            rendered_clip_ids.append(clip_id(feed, episode, start))

    if len(rendered_clip_files) < max(2, int(args.min_clips)):
        print(
            f"[render_short] Only {len(rendered_clip_files)} clips rendered; need at least {args.min_clips}.",
            file=sys.stderr,
        )
        sys.exit(6)

    if intro_text:
        intro_card_img = work_dir / "intro_card.png"
        if render_card(intro_text, _SHORT_W, _SHORT_H, intro_card_img, label=theme.title()):
            intro_path = work_dir / "intro.mp4"
            if _ffmpeg_text_card(args.intro_duration, intro_path, intro_card_img):
                out_segments.append(intro_path)

    out_segments.extend(rendered_clip_files)

    if outro_text:
        outro_card_img = work_dir / "outro_card.png"
        if render_card(outro_text, _SHORT_W, _SHORT_H, outro_card_img, label="Watch full sermons"):
            outro_path = work_dir / "outro.mp4"
            if _ffmpeg_text_card(args.outro_duration, outro_path, outro_card_img):
                out_segments.append(outro_path)

    if not out_segments:
        print("[render_short] No segments to concatenate", file=sys.stderr)
        sys.exit(3)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    concat_list = work_dir / "concat_list.txt"
    if not _ffmpeg_concat(out_segments, out_path, concat_list):
        sys.exit(4)

    print(f"[render_short] wrote {out_path}", file=sys.stderr)
    if args.register and rendered_clip_ids:
        reg_path = Path(args.register)
        save_used_clips(reg_path, set(rendered_clip_ids), video_title=out_path.stem)
        print(f"[render_short] registered {len(rendered_clip_ids)} clips", file=sys.stderr)

    remove_path(concat_list)
    if auto_work_dir and not args.keep_work:
        remove_path(work_dir)


if __name__ == "__main__":
    main()
