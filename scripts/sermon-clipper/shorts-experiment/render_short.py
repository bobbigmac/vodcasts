"""Render vertical short from script: split screen (speaker + context), subtitles."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PARENT = Path(__file__).resolve().parent.parent
_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_PARENT))

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
from text_overlay import render_card, render_context_panel


# Vertical shorts: 1080x1920 (9:16)
_SHORT_W = 1080
_SHORT_H = 1920
_PANEL_H = 960  # Half each
_OUT_FPS = 30


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render vertical short from script.")
    p.add_argument("--script", required=True, help="Short script markdown path.")
    p.add_argument("--output", "-o", required=True, help="Output video path.")
    p.add_argument("--env", default="", help="Cache env.")
    p.add_argument("--work-dir", default="", help="Working directory for clips/cards (default: <output_dir>/work).")
    p.add_argument("--content-cache", default="", help="Shared source video cache (default: cache/<env>/sermon-clipper/content).")
    p.add_argument("--intro-duration", type=float, default=1.5, help="Intro card seconds (default: 1.5).")
    p.add_argument("--outro-duration", type=float, default=1.5, help="Outro card seconds (default: 1.5).")
    p.add_argument("--no-download", action="store_true", help="Skip download; use existing sources in content cache (for re-renders).")
    p.add_argument("--transcripts", default="", help="Transcripts root.")
    p.add_argument("--no-subs", action="store_true", help="Skip subtitles.")
    p.add_argument("--trim-silence", action="store_true", help="Trim leading/trailing silence from clips.")
    p.add_argument("--context-top", action="store_true", default=True, help="Context panel on top (default).")
    p.add_argument("--context-bottom", action="store_false", dest="context_top", help="Context panel on bottom.")
    p.add_argument("--register", default="", help="Path to used-clips.json to register.")
    return p.parse_args()


def _parse_script(script_path: Path) -> dict:
    """Parse short script: intro, clip (with context, decorators), outro."""
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
    for s in sections:
        t = s["type"]
        c = s["content"]
        if t == "metadata":
            continue
        if t == "intro":
            items.append({"type": "intro", "text": c})
            continue
        if t == "outro":
            items.append({"type": "outro", "text": c})
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
                "context": kv.get("context", ""),
                "decorators": kv.get("decorators", ""),
                "episode_title": kv.get("episode_title") or "",
                "feed_title": kv.get("feed_title") or "",
            })
            continue

    return {"items": items}


def _download_url(url: str, out_path: Path) -> bool:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-i", url, "-c", "copy", "-movflags", "+faststart", str(out_path)]
    try:
        subprocess.run(cmd, capture_output=True, check=True, timeout=600)
        return True
    except Exception as e:
        print(f"[render_short] download failed: {e}", file=sys.stderr)
        return False


def _source_has_video(path: Path) -> bool:
    """Probe media file for video stream."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
            capture_output=True,
            timeout=10,
        )
        return r.returncode == 0 and b"video" in (r.stdout or b"")
    except Exception:
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


def _ffmpeg_subtitles_path(vtt_path: Path) -> str:
    s = str(vtt_path.resolve()).replace("\\", "/")
    return s.replace(":", "\\:")


def _ffmpeg_text_card(text: str, duration: float, out: Path, card_img_path: Path) -> bool:
    """Create vertical card from Pillow-rendered PNG (no ffmpeg fonts)."""
    if not card_img_path.exists():
        return False
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(card_img_path),
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
        "-t", str(duration),
        "-vf", f"scale={_SHORT_W}:{_SHORT_H}:force_original_aspect_ratio=decrease,pad={_SHORT_W}:{_SHORT_H}:(ow-iw)/2:(oh-ih)/2,fps={_OUT_FPS}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(_OUT_FPS),
        "-c:a", "aac", "-ar", "48000", "-ac", "1",
        "-shortest", "-f", "mp4", "-movflags", "+faststart", str(out),
    ]
    try:
        subprocess.run(cmd, capture_output=True, check=True, timeout=60)
        return True
    except Exception as e:
        print(f"[render_short] text card failed: {e}", file=sys.stderr)
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
    """Extract clip and compose vertical: speaker half + context panel (Pillow-rendered PNG)."""
    dur = end - start

    # [0]=video [1]=context PNG. vstack: [ctx][vid] = context on top, video below
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

    # Audio: concat requires all segments to have audio. Use anullsrc when source has no audio.
    af = []
    if trim_silence:
        af.append("silenceremove=start_periods=1:start_duration=0.5:start_threshold=-50dB:detection=peak,silenceremove=stop_periods=1:stop_duration=0.5:stop_threshold=-50dB:detection=peak")

    common = [
        "-filter_complex", filter_complex,
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-r", str(_OUT_FPS),
        "-c:a", "aac", "-ar", "48000", "-ac", "1",
        "-f", "mp4", "-movflags", "+faststart", str(out),
    ]

    if has_audio:
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", str(src),
            "-loop", "1",
            "-i", str(context_img_path),
            "-t", str(dur),
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-map", "0:a?",
        ] + (["-af", ",".join(af)] if af else []) + common
    else:
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", str(src),
            "-loop", "1",
            "-i", str(context_img_path),
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
            "-t", str(dur),
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-map", "2:a",
            "-shortest",
        ] + common

    try:
        subprocess.run(cmd, capture_output=True, check=True, timeout=120)
        return True
    except subprocess.CalledProcessError:
        if has_audio:
            # Fallback: source audio may have failed (e.g. wrong codec), use anullsrc
            cmd_alt = [
                "ffmpeg", "-y",
                "-ss", str(start),
                "-i", str(src),
                "-loop", "1",
                "-i", str(context_img_path),
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
                "-t", str(dur),
                "-filter_complex", filter_complex,
                "-map", "[out]",
                "-map", "2:a",
                "-shortest",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-r", str(_OUT_FPS),
                "-c:a", "aac", "-ar", "48000", "-ac", "1",
                "-f", "mp4", "-movflags", "+faststart", str(out),
            ]
            try:
                subprocess.run(cmd_alt, capture_output=True, check=True, timeout=120)
                return True
            except Exception as e:
                print(f"[render_short] extract failed: {e}", file=sys.stderr)
                return False
        raise
    except Exception as e:
        print(f"[render_short] extract failed: {e}", file=sys.stderr)
        return False


def _ffmpeg_concat(files: list[Path], out: Path) -> bool:
    list_path = out.parent / "concat_list.txt"
    with open(list_path, "w", encoding="utf-8") as f:
        for p in files:
            f.write(f"file '{p.resolve()}'\n")
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(list_path),
        "-c", "copy",
        "-f", "mp4", "-movflags", "+faststart", str(out),
    ]
    try:
        subprocess.run(cmd, capture_output=True, check=True, timeout=60)
        return True
    except Exception as e:
        print(f"[render_short] concat failed: {e}", file=sys.stderr)
        return False


def main() -> None:
    args = _parse_args()
    script_path = Path(args.script)
    if not script_path.exists():
        print(f"[render_short] Script not found: {script_path}", file=sys.stderr)
        sys.exit(1)

    env = (args.env or "").strip() or default_env()
    cache_dir = _REPO_ROOT / "cache" / env
    content_cache = Path(args.content_cache).resolve() if args.content_cache else default_content_cache_dir(env)
    content_cache.mkdir(parents=True, exist_ok=True)
    transcripts_root = Path(args.transcripts).resolve() if args.transcripts else default_transcripts_root()
    out_path = Path(args.output)
    work_dir = Path(args.work_dir) if args.work_dir else (out_path.parent / "work")
    work_dir.mkdir(parents=True, exist_ok=True)
    embed_subs = not bool(args.no_subs)
    context_top = bool(args.context_top)

    parsed = _parse_script(script_path)
    items = parsed.get("items") or []
    clip_count = sum(1 for it in items if it.get("type") == "clip")
    if clip_count < 2:
        print("[render_short] Need at least 2 clips. Single-clip shorts are not acceptable.", file=sys.stderr)
        sys.exit(5)

    clip_files = []
    rendered_clip_ids = []
    intro_text = ""
    outro_text = ""

    for i, item in enumerate(items):
        if item["type"] == "intro":
            intro_text = item.get("text", "")[:80]
            continue
        if item["type"] == "outro":
            outro_text = item.get("text", "")[:80]
            continue
        if item["type"] == "clip":
            feed = item.get("feed")
            episode = item.get("episode")
            start = item.get("start_sec", 0)
            end = item.get("end_sec", start + 15)
            context = item.get("context", "")
            decorators = item.get("decorators", "")
            if not feed or not episode:
                continue
            media_info = get_episode_media_info(cache_dir, feed, episode)
            if not media_info or not media_info.get("url"):
                print(f"[render_short] No media for {feed}/{episode}", file=sys.stderr)
                continue
            if not media_info.get("pickedIsVideo"):
                print(f"[render_short] Skipping {feed}/{episode}: audio-only enclosure (video required)", file=sys.stderr)
                continue
            media_url = media_info["url"]
            src_path = get_source_path(content_cache, feed, episode)
            if not src_path.exists():
                if args.no_download:
                    continue
                if not _download_url(media_url, src_path):
                    continue
            if not _source_has_video(src_path):
                print(f"[render_short] Skipping {feed}/{episode}: no video stream (audio-only)", file=sys.stderr)
                continue
            clip_path = work_dir / f"clip_{i}.mp4"
            ctx_line = (context or " ")[:60].replace("\n", " ")
            dec_line = (decorators or "")[:40]
            if dec_line:
                ctx_line = f"{ctx_line}  {dec_line}"
            ctx_img = work_dir / f"clip_{i}_ctx.png"
            subs_path: Path | None = None
            if embed_subs:
                transcript_path = get_transcript_path(transcripts_root, feed, episode)
                if transcript_path:
                    subs_path = work_dir / f"clip_{i}_subs.vtt"
                    if not clip_transcript_to_vtt(transcript_path, start, end, subs_path):
                        subs_path = None
                else:
                    print(f"[render_short] No transcript for {feed}/{episode} (checked {transcripts_root / feed})", file=sys.stderr)
            has_audio = _source_has_audio(src_path)
            if render_context_panel(ctx_line, _SHORT_W, _PANEL_H, ctx_img) and _ffmpeg_extract_short_clip(
                src_path, start, end, clip_path,
                context_img_path=ctx_img,
                subtitles_path=subs_path,
                context_top=context_top,
                trim_silence=bool(args.trim_silence),
                has_audio=has_audio,
            ):
                clip_files.append(clip_path)
                rendered_clip_ids.append(clip_id(feed, episode, start))

    # Build final: intro card + clips + outro card (all text via Pillow, no ffmpeg fonts)
    out_segments = []
    if intro_text:
        intro_card_img = work_dir / "intro_card.png"
        if render_card(intro_text, _SHORT_W, _SHORT_H, intro_card_img):
            intro_path = work_dir / "intro.mp4"
            if _ffmpeg_text_card(intro_text, args.intro_duration, intro_path, intro_card_img):
                out_segments.append(intro_path)
    for p in clip_files:
        out_segments.append(p)
    if outro_text:
        outro_card_img = work_dir / "outro_card.png"
        if render_card(outro_text, _SHORT_W, _SHORT_H, outro_card_img):
            outro_path = work_dir / "outro.mp4"
            if _ffmpeg_text_card(outro_text, args.outro_duration, outro_path, outro_card_img):
                out_segments.append(outro_path)

    if len(clip_files) < 2:
        print(f"[render_short] Only {len(clip_files)} clips rendered; need at least 2. Check media availability and transcripts.", file=sys.stderr)
        sys.exit(6)

    if not out_segments:
        print("[render_short] No segments to concatenate", file=sys.stderr)
        sys.exit(3)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if _ffmpeg_concat(out_segments, out_path):
        print(f"[render_short] wrote {out_path}", file=sys.stderr)
        if args.register and rendered_clip_ids:
            reg_path = Path(args.register)
            save_used_clips(reg_path, set(rendered_clip_ids), video_title=out_path.stem)
            print(f"[render_short] registered {len(rendered_clip_ids)} clips", file=sys.stderr)
    else:
        sys.exit(4)


if __name__ == "__main__":
    main()
