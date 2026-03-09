"""Render final video from script: download sources, extract clips, concatenate with title cards."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _lib import (
    clip_id,
    clip_transcript_to_vtt,
    default_content_cache_dir,
    default_env,
    default_transcripts_root,
    get_episode_media_info,
    get_feed_title,
    get_source_path,
    get_transcript_path,
    save_used_clips,
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render video from script (download, ffmpeg compose).")
    p.add_argument("--script", required=True, help="Video script markdown path.")
    p.add_argument("--output", "-o", required=True, help="Output video path.")
    p.add_argument("--title-cards", default="", help="Directory with title card images (from make_title_cards).")
    p.add_argument("--env", default="", help="Cache env.")
    p.add_argument("--work-dir", default="", help="Working directory for clips/cards (default: <output_dir>/work).")
    p.add_argument("--content-cache", default="", help="Shared source video cache (default: cache/<env>/sermon-clipper/content).")
    p.add_argument("--card-duration", type=float, default=4.0, help="Seconds per title card (default: 4).")
    p.add_argument("--no-download", action="store_true", help="Skip download; use existing sources in work-dir (for re-renders).")
    p.add_argument("--trim-silence", action="store_true", help="Trim leading/trailing silence from clips (ffmpeg silenceremove).")
    p.add_argument("--transition-duration", type=float, default=3.0, help="Seconds per transition card (default: 3).")
    p.add_argument("--register", default="", help="Path to used-clips.json to register clips after render.")
    p.add_argument("--transcripts", default="", help="Transcripts root (default: site/assets/transcripts).")
    p.add_argument("--no-subs", action="store_true", help="Skip embedding subtitles from transcripts.")
    p.add_argument("--no-overlay", action="store_true", help="Skip source overlay on clips (use if drawtext fails on your system).")
    return p.parse_args()


def _parse_script(script_path: Path) -> dict:
    """Parse script into ordered sections: intro, title_card, clip, transition, outro."""
    text = script_path.read_text(encoding="utf-8", errors="replace")
    sections = []
    current = []
    current_type = None

    for line in text.splitlines():
        line_stripped = line.strip()
        if line_stripped.startswith("## "):
            if current_type and current:
                sections.append({"type": current_type, "content": "\n".join(current).strip()})
            current = []
            current_type = line_stripped[3:].strip().lower()
            continue
        if current_type:
            current.append(line)

    if current_type and current:
        sections.append({"type": current_type, "content": "\n".join(current).strip()})

    items = []
    transition_idx = 0
    i = 0
    while i < len(sections):
        s = sections[i]
        t = s["type"]
        c = s["content"]

        if t == "metadata":
            i += 1
            continue
        if t == "intro":
            items.append({"type": "intro", "text": c})
            i += 1
            continue
        if t == "outro":
            items.append({"type": "outro", "text": c})
            i += 1
            continue
        if t == "title_card":
            kv = {}
            for ln in c.splitlines():
                if ":" in ln:
                    k, v = ln.split(":", 1)
                    kv[k.strip()] = v.strip()
            items.append({"type": "title_card", "id": kv.get("id", ""), "text": kv.get("text", "")})
            i += 1
            continue
        if t == "transition":
            transition_idx += 1
            items.append({"type": "title_card", "id": f"transition_{transition_idx}", "text": c})
            i += 1
            continue
        if t == "clip":
            kv = {}
            for ln in c.splitlines():
                if ":" in ln:
                    k, v = ln.split(":", 1)
                    kv[k.strip()] = v.strip()
            items.append({
                "type": "clip",
                "feed": kv.get("feed"),
                "episode": kv.get("episode"),
                "start_sec": float(kv.get("start_sec") or 0),
                "end_sec": float(kv.get("end_sec") or 0),
                "episode_title": kv.get("episode_title") or "",
                "feed_title": kv.get("feed_title") or "",
            })
            i += 1
            continue
        i += 1

    return {"items": items}


def _download_url(url: str, out_path: Path) -> bool:
    """Download media URL using ffmpeg (handles MP4, HLS, etc.)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", url,
        "-c", "copy",
        "-movflags", "+faststart",
        str(out_path),
    ]
    try:
        subprocess.run(cmd, capture_output=True, check=True, timeout=600)
        return True
    except subprocess.CalledProcessError as e:
        print(f"[render] ffmpeg download failed: {e.stderr.decode()[:200] if e.stderr else e}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[render] download failed: {e}", file=sys.stderr)
        return False


def _source_has_audio(path: Path) -> bool:
    """Probe media file for audio stream. Concat requires all segments to have audio."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
            capture_output=True,
            timeout=10,
        )
        return r.returncode == 0 and b"audio" in (r.stdout or b"")
    except Exception:
        return False


def _escape_drawtext(s: str) -> str:
    """Escape special chars for ffmpeg drawtext. Use ASCII to avoid encoding issues."""
    s = (s or "").replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
    # Replace Unicode chars that can break drawtext
    s = s.replace("\u2014", "-").replace("\u2013", "-").replace("\u2018", "'").replace("\u2019", "'")
    return s.encode("ascii", "replace").decode("ascii")


# Output format: 1080p30, yuv420p, AAC — ensures concat demuxer works correctly
_OUT_FPS = 30
_OUT_W = 1920
_OUT_H = 1080


def _ffmpeg_subtitles_path(vtt_path: Path) -> str:
    """Escape path for ffmpeg subtitles filter. Use forward slashes and escape colons."""
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
    """Extract segment with ffmpeg. Always re-encode to _OUT_Wx_OUT_H, _OUT_FPS for concat compatibility."""
    dur = end - start
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", str(src),
        "-t", str(dur),
    ]
    # Normalize to fixed format so concat produces correct duration (avoids 4x etc from frame rate/timebase mismatch)
    vf_parts = [f"scale={_OUT_W}:{_OUT_H}:force_original_aspect_ratio=decrease,pad={_OUT_W}:{_OUT_H}:(ow-iw)/2:(oh-ih)/2,fps={_OUT_FPS}"]
    if overlay_text:
        # Windows: fontconfig often fails; use explicit fontfile. Escape colon: C: -> C\:
        font_candidates = [
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ]
        fontfile = next((str(p) for p in font_candidates if p.exists()), "")
        font_esc = fontfile.replace(":", "\\:") if fontfile else ""
        font_opt = f":fontfile='{font_esc}'" if font_esc else ""
        vf_parts.append(
            f"drawtext=text='{_escape_drawtext(overlay_text)}':fontsize=28:fontcolor=white{font_opt}:"
            "x=(w-text_w)-30:y=h-50:shadowcolor=black:shadowx=2:shadowy=2"
        )
    if subtitles_path and subtitles_path.exists():
        sub_esc = _ffmpeg_subtitles_path(subtitles_path)
        vf_parts.append(f"subtitles=filename='{sub_esc}':force_style='FontSize=24,PrimaryColour=&HFFFFFF&,OutlineColour=&H000000&,Outline=2'")
    af = []
    if trim_silence:
        af.append("silenceremove=start_periods=1:start_duration=0.5:start_threshold=-50dB:detection=peak,silenceremove=stop_periods=1:stop_duration=0.5:stop_threshold=-50dB:detection=peak")
    if not has_audio:
        cmd.extend(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono"])
    cmd.extend(["-vf", ",".join(vf_parts), "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p", "-r", str(_OUT_FPS)])
    if has_audio:
        if af:
            cmd.extend(["-af", ",".join(af)])
        cmd.extend(["-c:a", "aac", "-ar", "48000", "-ac", "1"])
    else:
        cmd.extend(["-map", "0:v", "-map", "1:a", "-c:a", "aac", "-ar", "48000", "-ac", "1", "-shortest"])
    cmd.extend(["-f", "mp4", "-movflags", "+faststart", str(out)])
    try:
        # 90s max: clip encode should complete in ~1–2x realtime; fail fast if stuck
        subprocess.run(cmd, capture_output=True, check=True, timeout=90)
        return True
    except subprocess.CalledProcessError:
        if has_audio:
            # Fallback: source audio may have failed, use anullsrc
            cmd_alt = [
                "ffmpeg", "-y",
                "-ss", str(start),
                "-i", str(src),
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
                "-t", str(dur),
                "-vf", ",".join(vf_parts),
                "-map", "0:v", "-map", "1:a",
                "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p", "-r", str(_OUT_FPS),
                "-c:a", "aac", "-ar", "48000", "-ac", "1",
                "-shortest",
                "-f", "mp4", "-movflags", "+faststart", str(out),
            ]
            try:
                subprocess.run(cmd_alt, capture_output=True, check=True, timeout=90)
                return True
            except Exception as e:
                print(f"[render] ffmpeg extract failed: {e}", file=sys.stderr)
                return False
        raise
    except Exception as e:
        print(f"[render] ffmpeg extract failed: {e}", file=sys.stderr)
        return False


def _ffmpeg_image_to_video(img: Path, duration: float, out: Path, width: int = 1920, height: int = 1080) -> bool:
    """Create video from image with duration. Output 30fps, silent audio for concat compatibility."""
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-framerate", str(_OUT_FPS),
        "-i", str(img),
        "-f", "lavfi",
        "-i", f"anullsrc=r=48000:cl=mono",
        "-t", str(duration),
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={_OUT_FPS}",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-r", str(_OUT_FPS),
        "-c:a", "aac",
        "-ar", "48000",
        "-ac", "1",
        "-shortest",
        "-f", "mp4",
        "-movflags", "+faststart",
        str(out),
    ]
    try:
        # 15s max: image→video is trivial; fail fast if hung
        subprocess.run(cmd, capture_output=True, check=True, timeout=15)
        return True
    except Exception as e:
        print(f"[render] ffmpeg image-to-video failed: {e}", file=sys.stderr)
        return False


def _ffmpeg_concat(files: list[Path], out: Path) -> bool:
    """Concatenate videos with concat demuxer. All inputs must be same format (1080p30, yuv420p, AAC)."""
    list_path = out.parent / "concat_list.txt"
    with open(list_path, "w", encoding="utf-8") as f:
        for p in files:
            f.write(f"file '{p.resolve()}'\n")
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(list_path),
        "-c", "copy",
        "-f", "mp4",
        "-movflags", "+faststart",
        str(out),
    ]
    try:
        subprocess.run(cmd, capture_output=True, check=True, timeout=60)
        return True
    except Exception as e:
        print(f"[render] ffmpeg concat failed: {e}", file=sys.stderr)
        return False


def main() -> None:
    args = _parse_args()
    script_path = Path(args.script)
    if not script_path.exists():
        print(f"[render] Script not found: {script_path}", file=sys.stderr)
        sys.exit(1)

    env = (args.env or "").strip() or default_env()
    cache_dir = _REPO_ROOT / "cache" / env
    content_cache = Path(args.content_cache).resolve() if args.content_cache else default_content_cache_dir(env)
    content_cache.mkdir(parents=True, exist_ok=True)
    transcripts_root = Path(args.transcripts).resolve() if args.transcripts else default_transcripts_root()
    out_path = Path(args.output)
    work_dir = Path(args.work_dir) if args.work_dir else (out_path.parent / "work")
    work_dir.mkdir(parents=True, exist_ok=True)
    title_cards_dir = Path(args.title_cards) if args.title_cards else script_path.parent / "title-cards"
    embed_subs = not bool(args.no_subs)

    parsed = _parse_script(script_path)
    items = parsed.get("items") or []

    clip_files = []
    rendered_clip_ids = []

    for i, item in enumerate(items):
        if item["type"] == "title_card":
            card_id = item.get("id") or f"card_{i}"
            img_path = title_cards_dir / f"{card_id}.png"
            if not img_path.exists():
                print(f"[render] Title card not found: {img_path}. Run make_title_cards first.", file=sys.stderr)
                sys.exit(2)
            vid_path = work_dir / f"card_{i}.mp4"
            dur = args.transition_duration if card_id.startswith("transition_") else args.card_duration
            if _ffmpeg_image_to_video(img_path, dur, vid_path):
                clip_files.append(vid_path)
            continue

        if item["type"] == "clip":
            feed = item.get("feed")
            episode = item.get("episode")
            start = item.get("start_sec", 0)
            end = item.get("end_sec", start + 30)
            feed_title = item.get("feed_title") or get_feed_title(env, feed or "")
            episode_title = item.get("episode_title") or ""
            overlay = feed_title
            if episode_title:
                overlay = f"{feed_title} - {episode_title}" if feed_title else episode_title
            if not feed or not episode:
                continue
            media_info = get_episode_media_info(cache_dir, feed, episode)
            if not media_info or not media_info.get("url"):
                print(f"[render] No media URL for {feed}/{episode}", file=sys.stderr)
                continue
            if not media_info.get("pickedIsVideo"):
                print(f"[render] Skipping {feed}/{episode}: audio-only enclosure (video required)", file=sys.stderr)
                continue
            media_url = media_info["url"]
            src_path = get_source_path(content_cache, feed, episode)
            if not src_path.exists():
                if args.no_download:
                    continue
                if not _download_url(media_url, src_path):
                    continue
            clip_path = work_dir / f"clip_{i}.mp4"
            use_overlay = not bool(args.no_overlay)
            subs_path: Path | None = None
            if embed_subs:
                transcript_path = get_transcript_path(transcripts_root, feed, episode)
                if transcript_path:
                    subs_path = work_dir / f"clip_{i}_subs.vtt"
                    if not clip_transcript_to_vtt(transcript_path, start, end, subs_path):
                        subs_path = None
                else:
                    print(f"[render] No transcript for {feed}/{episode} (checked {transcripts_root / feed})", file=sys.stderr)
            has_audio = _source_has_audio(src_path)
            if _ffmpeg_extract_clip(
                src_path, start, end, clip_path,
                trim_silence=bool(args.trim_silence),
                overlay_text=overlay[:80] if (overlay and use_overlay) else None,
                subtitles_path=subs_path,
                has_audio=has_audio,
            ):
                clip_files.append(clip_path)
                rendered_clip_ids.append(clip_id(feed, episode, start))

    if not clip_files:
        print("[render] No clips to concatenate", file=sys.stderr)
        sys.exit(3)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if _ffmpeg_concat(clip_files, out_path):
        print(f"[render] wrote {out_path}", file=sys.stderr)
        if args.register and rendered_clip_ids:
            reg_path = Path(args.register)
            video_title = out_path.stem
            save_used_clips(reg_path, set(rendered_clip_ids), video_title=video_title)
            print(f"[render] registered {len(rendered_clip_ids)} clips in {reg_path}", file=sys.stderr)
    else:
        sys.exit(4)


if __name__ == "__main__":
    main()
