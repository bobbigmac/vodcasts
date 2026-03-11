"""Apply a markdown video edit plan to local media with ffmpeg."""
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

_THIS = Path(__file__).resolve().parent
if str(_THIS) not in sys.path:
    sys.path.insert(0, str(_THIS))

from _lib import keep_ranges_from_actions, metadata_float, parse_edit_plan, probe_media, remove_path, resolve_work_dir, sec_text


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply a markdown video edit plan.")
    parser.add_argument("--plan", required=True, help="Markdown edit plan path.")
    parser.add_argument("--output", "-o", required=True, help="Output media path.")
    parser.add_argument("--input", default="", help="Override source media path from the plan metadata.")
    parser.add_argument("--work-dir", default="", help="Working directory override. Default is auto scratch under scripts/markdown-video-editor/.work/.")
    parser.add_argument("--video-codec", default="libx264", help="Video codec for output (default: libx264).")
    parser.add_argument("--audio-codec", default="aac", help="Audio codec for output (default: aac).")
    parser.add_argument("--preset", default="fast", help="ffmpeg preset for video encoding (default: fast).")
    parser.add_argument("--crf", type=int, default=20, help="CRF for video encoding (default: 20).")
    parser.add_argument("--dry-run", action="store_true", help="Write the filter script and print the ffmpeg command without rendering.")
    parser.add_argument("--keep-work", action="store_true", help="Keep scratch work directory after a successful render.")
    return parser.parse_args()


def _build_filter_complex(keep_ranges: list[tuple[float, float]]) -> str:
    parts: list[str] = []
    for index, (start, end) in enumerate(keep_ranges):
        parts.append(f"[0:v]trim=start={start:.6f}:end={end:.6f},setpts=PTS-STARTPTS[v{index}]")
        parts.append(f"[0:a]atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS[a{index}]")
    concat_inputs = "".join(f"[v{index}][a{index}]" for index in range(len(keep_ranges)))
    parts.append(f"{concat_inputs}concat=n={len(keep_ranges)}:v=1:a=1[vout][aout]")
    return ";\n".join(parts) + "\n"


def _quote_cmd(parts: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def main() -> None:
    args = _parse_args()
    plan_path = Path(args.plan).resolve()
    if not plan_path.exists():
        print(f"[apply_edit_plan] plan not found: {plan_path}", file=sys.stderr)
        sys.exit(1)

    parsed = parse_edit_plan(plan_path)
    metadata = parsed.get("metadata") or {}
    actions = parsed.get("actions") or []
    source_path = Path(args.input).resolve() if args.input else Path(str(metadata.get("source_path") or "")).resolve()
    if not str(source_path) or not source_path.exists():
        print(f"[apply_edit_plan] source media not found: {source_path}", file=sys.stderr)
        sys.exit(2)

    try:
        media = probe_media(source_path)
    except Exception as exc:
        print(f"[apply_edit_plan] ffprobe failed: {exc}", file=sys.stderr)
        sys.exit(3)

    duration_sec = float(media.get("duration_sec") or metadata_float(metadata, "duration_sec", 0.0))
    if duration_sec <= 0:
        print(f"[apply_edit_plan] unable to determine duration for {source_path}", file=sys.stderr)
        sys.exit(4)
    if not media.get("has_video"):
        print(f"[apply_edit_plan] source has no video stream: {source_path}", file=sys.stderr)
        sys.exit(5)
    if not media.get("has_audio"):
        print(f"[apply_edit_plan] source has no audio stream: {source_path}", file=sys.stderr)
        sys.exit(6)

    keep_ranges = keep_ranges_from_actions(actions, duration_sec=duration_sec)
    if not keep_ranges:
        print(f"[apply_edit_plan] no keep actions found in {plan_path}", file=sys.stderr)
        sys.exit(7)

    out_path = Path(args.output).resolve()
    work_dir, auto_work_dir = resolve_work_dir("apply-plan", out_path, args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    filter_path = work_dir / "filter_complex.txt"
    filter_path.write_text(_build_filter_complex(keep_ranges), encoding="utf-8")

    no_op_plan = len(keep_ranges) == 1 and keep_ranges[0][0] <= 0.01 and keep_ranges[0][1] >= duration_sec - 0.01
    if no_op_plan:
        cmd = ["ffmpeg", "-y", "-i", str(source_path), "-c", "copy", "-movflags", "+faststart", str(out_path)]
    else:
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(source_path),
            "-filter_complex_script",
            str(filter_path),
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-c:v",
            args.video_codec,
            "-preset",
            args.preset,
            "-crf",
            str(int(args.crf)),
            "-c:a",
            args.audio_codec,
            "-movflags",
            "+faststart",
            str(out_path),
        ]

    if args.dry_run:
        print(f"[apply_edit_plan] filter script: {filter_path}", file=sys.stderr)
        print(f"[apply_edit_plan] ffmpeg: {_quote_cmd(cmd)}", file=sys.stderr)
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(cmd, check=True, timeout=1800, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        print(f"[apply_edit_plan] ffmpeg failed: {stderr or exc}", file=sys.stderr)
        sys.exit(8)
    except Exception as exc:
        print(f"[apply_edit_plan] ffmpeg failed: {exc}", file=sys.stderr)
        sys.exit(9)

    out_duration_sec = sum(end - start for start, end in keep_ranges)
    print(f"[apply_edit_plan] wrote {out_path} (segments={len(keep_ranges)} output~={sec_text(duration_sec if no_op_plan else out_duration_sec)}s)", file=sys.stderr)

    if auto_work_dir and not args.keep_work:
        remove_path(work_dir)


if __name__ == "__main__":
    main()
