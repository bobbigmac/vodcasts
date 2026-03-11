"""Render final video from script: download sources, extract clips, concatenate with title cards."""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _lib import (
    clip_id,
    clip_transcript_to_vtt,
    default_cache_dir,
    default_content_cache_dir,
    default_env,
    default_transcripts_root,
    get_episode_media_info,
    get_feed_title,
    get_source_path,
    get_transcript_path,
    parse_long_form_script,
    remove_path,
    resolve_work_dir,
    reset_directory,
    save_used_clips,
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render video from script (download, ffmpeg compose).")
    p.add_argument("--script", required=True, help="Video script markdown path.")
    p.add_argument("--output", "-o", required=True, help="Output video path.")
    p.add_argument("--title-cards", default="", help="Directory with title card images (from make_title_cards).")
    p.add_argument("--env", default="", help="Cache env.")
    p.add_argument("--work-dir", default="", help="Working directory override. Default is auto scratch under scripts/sermon-clipper/.work/.")
    p.add_argument("--content-cache", default="", help="Shared source video cache (default: cache/<env>/sermon-clipper/content).")
    p.add_argument("--card-duration", type=float, default=4.0, help="Seconds per title card (default: 4).")
    p.add_argument("--no-download", action="store_true", help="Skip downloads and use only files already present in the shared content cache.")
    p.add_argument("--trim-silence", action="store_true", help="Trim leading/trailing silence from clips (ffmpeg silenceremove).")
    p.add_argument("--transition-duration", type=float, default=3.0, help="Seconds per transition card (default: 3).")
    p.add_argument("--register", default="", help="Path to used-clips.json to register clips after render.")
    p.add_argument("--transcripts", default="", help="Transcripts root (default: site/assets/transcripts).")
    p.add_argument("--no-subs", action="store_true", help="Skip embedding subtitles from transcripts.")
    p.add_argument("--no-overlay", action="store_true", help="Skip source overlay on clips (use if drawtext fails on your system).")
    p.add_argument("--width", type=int, default=1920, help="Output width (default: 1920).")
    p.add_argument("--height", type=int, default=1080, help="Output height (default: 1080).")
    p.add_argument("--fps", type=int, default=30, help="Output fps (default: 30).")
    p.add_argument("--preset", default="fast", help="x264 preset (default: fast).")
    p.add_argument("--threads", type=int, default=0, help="ffmpeg encoder threads override (default: auto).")
    p.add_argument("--min-clips", type=int, default=2, help="Require at least this many rendered clips before publishing output (default: 2).")
    p.add_argument("--keep-work", action="store_true", help="Keep scratch work directory after a successful render.")
    return p.parse_args()


def _download_url(url: str, out_path: Path) -> bool:
    """Download media URL using ffmpeg (handles MP4, HLS, etc.)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        url,
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    try:
        _run_media_command(cmd, timeout=600, label="ffmpeg download failed")
        return True
    except Exception as exc:
        print(f"[render] ffmpeg download failed: {exc}", file=sys.stderr)
        return False


def _source_has_audio(path: Path) -> bool:
    """Probe media file for audio stream. Concat requires all segments to have audio."""
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


def _escape_drawtext(value: str) -> str:
    value = (value or "").replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
    return (
        value.replace("\u2014", "-")
        .replace("\u2013", "-")
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .encode("ascii", "replace")
        .decode("ascii")
    )


_OUT_FPS = 30
_OUT_W = 1920
_OUT_H = 1080
_ENC_PRESET = "fast"
_ENC_THREADS = 0


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


def _ffmpeg_subtitles_path(vtt_path: Path) -> str:
    s = str(vtt_path.resolve()).replace("\\", "/")
    return s.replace(":", "\\:")


def _ffmpeg_extract_clip(
    src: Path,
    start: float,
    end: float,
    out: Path,
    trim_silence: bool = False,
    overlay_text: str | None = None,
    subtitles_path: Path | None = None,
    has_audio: bool = True,
) -> bool:
    """Extract segment with ffmpeg. Always normalize to 1080p30 with AAC audio."""
    dur = end - start
    af = []
    if trim_silence:
        af.append(
            "silenceremove=start_periods=1:start_duration=0.5:start_threshold=-50dB:detection=peak,"
            "silenceremove=stop_periods=1:stop_duration=0.5:stop_threshold=-50dB:detection=peak"
        )

    def _build_vf(include_overlay: bool) -> str:
        vf_parts = [
            f"scale={_OUT_W}:{_OUT_H}:force_original_aspect_ratio=decrease,pad={_OUT_W}:{_OUT_H}:(ow-iw)/2:(oh-ih)/2,fps={_OUT_FPS}"
        ]
        if include_overlay and overlay_text:
            font_candidates = [
                Path("C:/Windows/Fonts/arial.ttf"),
                Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            ]
            fontfile = next((str(p) for p in font_candidates if p.exists()), "")
            font_esc = fontfile.replace(":", "\\:") if fontfile else ""
            font_opt = f":fontfile='{font_esc}'" if font_esc else ""
            vf_parts.append(
                f"drawtext=text='{_escape_drawtext(overlay_text)}':fontsize=28:fontcolor=white{font_opt}:"
                "x=(w-text_w)-30:y=h-54:shadowcolor=black:shadowx=2:shadowy=2"
            )
        if subtitles_path and subtitles_path.exists():
            sub_esc = _ffmpeg_subtitles_path(subtitles_path)
            vf_parts.append(
                "subtitles="
                f"filename='{sub_esc}':force_style='FontSize=24,PrimaryColour=&HFFFFFF&,OutlineColour=&H000000&,Outline=2'"
            )
        return ",".join(vf_parts)

    def _run(include_overlay: bool, use_silent_audio: bool) -> None:
        cmd = ["ffmpeg", "-y", "-ss", str(start), "-i", str(src), "-t", str(dur)]
        if use_silent_audio:
            cmd.extend(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono"])
        cmd.extend(
            [
                "-vf",
                _build_vf(include_overlay),
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
            ]
        )
        if not use_silent_audio:
            if af:
                cmd.extend(["-af", ",".join(af)])
            cmd.extend(["-c:a", "aac", "-ar", "48000", "-ac", "1"])
        else:
            cmd.extend(
                [
                    "-map",
                    "0:v",
                    "-map",
                    "1:a",
                    "-c:a",
                    "aac",
                    "-ar",
                    "48000",
                    "-ac",
                    "1",
                    "-shortest",
                ]
            )
        cmd.extend(["-f", "mp4", "-movflags", "+faststart", str(out)])
        _run_media_command(_maybe_add_threads(cmd), timeout=180, label="ffmpeg extract failed")

    attempts = []
    if overlay_text:
        attempts.append((True, not has_audio))
    attempts.append((False, not has_audio))
    if has_audio:
        if overlay_text:
            attempts.append((True, True))
        attempts.append((False, True))

    last_error: Exception | None = None
    for include_overlay, use_silent_audio in attempts:
        try:
            _run(include_overlay, use_silent_audio)
            return True
        except Exception as exc:
            last_error = exc
            continue

    print(f"[render] ffmpeg extract failed: {last_error}", file=sys.stderr)
    return False


def _ffmpeg_image_to_video(img: Path, duration: float, out: Path, width: int = 1920, height: int = 1080) -> bool:
    """Create video from image with duration. Output 30fps, silent audio for concat compatibility."""
    cmd = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-framerate",
        str(_OUT_FPS),
        "-i",
        str(img),
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=48000:cl=mono",
        "-t",
        str(duration),
        "-vf",
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={_OUT_FPS}",
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
        _run_media_command(_maybe_add_threads(cmd), timeout=30, label="ffmpeg image-to-video failed")
        return True
    except Exception as exc:
        print(f"[render] ffmpeg image-to-video failed: {exc}", file=sys.stderr)
        return False


def _ffmpeg_concat(files: list[Path], out: Path, list_path: Path) -> bool:
    """Concatenate videos with concat demuxer. All inputs must be the same format."""
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
        "-c",
        "copy",
        "-f",
        "mp4",
        "-movflags",
        "+faststart",
        str(out),
    ]
    try:
        _run_media_command(_maybe_add_threads(cmd), timeout=120, label="ffmpeg concat failed")
        return True
    except Exception as exc:
        print(f"[render] ffmpeg concat failed: {exc}", file=sys.stderr)
        return False


def main() -> None:
    args = _parse_args()
    global _OUT_W, _OUT_H, _OUT_FPS, _ENC_PRESET, _ENC_THREADS
    script_path = Path(args.script)
    if not script_path.exists():
        print(f"[render] Script not found: {script_path}", file=sys.stderr)
        sys.exit(1)

    env = (args.env or "").strip() or default_env()
    _OUT_W = max(426, int(args.width))
    _OUT_H = max(240, int(args.height))
    _OUT_FPS = max(12, int(args.fps))
    _ENC_PRESET = str(args.preset or "fast").strip() or "fast"
    _ENC_THREADS = max(0, int(args.threads))
    cache_dir = default_cache_dir(env)
    content_cache = Path(args.content_cache).resolve() if args.content_cache else default_content_cache_dir(env)
    content_cache.mkdir(parents=True, exist_ok=True)
    transcripts_root = Path(args.transcripts).resolve() if args.transcripts else default_transcripts_root()
    out_path = Path(args.output).resolve()
    work_dir, auto_work_dir = resolve_work_dir("long-form", out_path, args.work_dir)
    if auto_work_dir:
        reset_directory(work_dir)
    else:
        work_dir.mkdir(parents=True, exist_ok=True)
    title_cards_dir = Path(args.title_cards).resolve() if args.title_cards else script_path.parent / "title-cards"
    embed_subs = not bool(args.no_subs)

    parsed = parse_long_form_script(script_path)
    items = parsed.get("items") or []
    clip_files: list[Path] = []
    rendered_clip_ids: list[str] = []

    for index, item in enumerate(items):
        if item["type"] == "title_card":
            card_id = item.get("id") or f"card_{index}"
            img_path = title_cards_dir / f"{card_id}.png"
            if not img_path.exists():
                print(f"[render] Title card not found: {img_path}. Run make_title_cards first.", file=sys.stderr)
                sys.exit(2)
            video_path = work_dir / f"card_{index:02d}.mp4"
            duration = args.transition_duration if card_id.startswith("transition_") else args.card_duration
            if _ffmpeg_image_to_video(img_path, duration, video_path):
                clip_files.append(video_path)
            continue

        if item["type"] != "clip":
            continue

        feed = item.get("feed")
        episode = item.get("episode")
        start = float(item.get("start_sec") or 0)
        end = float(item.get("end_sec") or start)
        feed_title = item.get("feed_title") or get_feed_title(env, feed or "")
        episode_title = item.get("episode_title") or ""
        overlay = feed_title
        if episode_title:
            overlay = f"{feed_title} - {episode_title}" if feed_title else episode_title
        if not feed or not episode or end <= start:
            continue

        media_info = get_episode_media_info(cache_dir, feed, episode)
        if not media_info or not media_info.get("url"):
            print(f"[render] No media URL for {feed}/{episode}", file=sys.stderr)
            continue
        if not media_info.get("pickedIsVideo"):
            print(f"[render] Skipping {feed}/{episode}: audio-only enclosure (video required)", file=sys.stderr)
            continue

        src_path = get_source_path(content_cache, feed, episode)
        if not src_path.exists():
            if args.no_download:
                print(f"[render] Missing cached source for {feed}/{episode}", file=sys.stderr)
                continue
            if not _download_url(str(media_info["url"]), src_path):
                continue

        subs_path: Path | None = None
        if embed_subs:
            transcript_path = get_transcript_path(transcripts_root, feed, episode)
            if transcript_path:
                subs_path = work_dir / f"clip_{index:02d}_subs.vtt"
                if not clip_transcript_to_vtt(transcript_path, start, end, subs_path):
                    subs_path = None
            else:
                print(f"[render] No transcript for {feed}/{episode}", file=sys.stderr)

        clip_path = work_dir / f"clip_{index:02d}.mp4"
        has_audio = _source_has_audio(src_path)
        if _ffmpeg_extract_clip(
            src=src_path,
            start=start,
            end=end,
            out=clip_path,
            trim_silence=bool(args.trim_silence),
            overlay_text=None if args.no_overlay else overlay[:96],
            subtitles_path=subs_path,
            has_audio=has_audio,
        ):
            clip_files.append(clip_path)
            rendered_clip_ids.append(clip_id(feed, episode, start))

    rendered_only = [path for path in clip_files if path.name.startswith("clip_")]
    if len(rendered_only) < max(1, int(args.min_clips)):
        print(
            f"[render] Only {len(rendered_only)} clips rendered; need at least {args.min_clips}.",
            file=sys.stderr,
        )
        sys.exit(3)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    concat_list = work_dir / "concat_list.txt"
    ok = _ffmpeg_concat(clip_files, out_path, concat_list)
    if not ok:
        sys.exit(4)

    print(f"[render] wrote {out_path}", file=sys.stderr)
    if args.register and rendered_clip_ids:
        reg_path = Path(args.register)
        save_used_clips(reg_path, set(rendered_clip_ids), video_title=out_path.stem)
        print(f"[render] registered {len(rendered_clip_ids)} clips in {reg_path}", file=sys.stderr)

    remove_path(concat_list)
    if auto_work_dir and not args.keep_work:
        remove_path(work_dir)


if __name__ == "__main__":
    main()
