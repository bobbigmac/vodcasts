"""Analyze local media and emit a markdown edit plan for spacetime compression."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_THIS = Path(__file__).resolve().parent
if str(_THIS) not in sys.path:
    sys.path.insert(0, str(_THIS))

from _lib import (
    build_actions,
    build_keep_ranges,
    detect_audio_changes,
    detect_silences,
    detect_video_scenes,
    invert_ranges,
    probe_media,
    sec_text,
    utc_now_iso,
    write_edit_plan,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze a media file and write a markdown edit plan for spacetime compression.")
    parser.add_argument("--input", required=True, help="Local source media file.")
    parser.add_argument("--output", "-o", required=True, help="Markdown edit plan output path.")
    parser.add_argument("--title", default="", help="Optional plan title override.")
    parser.add_argument("--threshold-db", type=float, default=-35.0, help="Silence threshold in dB (default: -35).")
    parser.add_argument("--min-silence-sec", type=float, default=0.35, help="Minimum silence duration to detect (default: 0.35).")
    parser.add_argument("--trim-edges", action="store_true", default=True, help="Trim leading and trailing silence (default).")
    parser.add_argument("--keep-edges", action="store_false", dest="trim_edges", help="Preserve leading and trailing silence.")
    parser.add_argument("--compress-gaps", action="store_true", default=True, help="Compress interior silent gaps (default).")
    parser.add_argument("--keep-gaps", action="store_false", dest="compress_gaps", help="Preserve interior silent gaps.")
    parser.add_argument("--edge-pad-sec", type=float, default=0.08, help="Silence pad to preserve at trimmed edges (default: 0.08).")
    parser.add_argument("--interior-gap-sec", type=float, default=0.05, help="Amount of each interior silent gap to preserve after compression (default: 0.05).")
    parser.add_argument("--detect-video-scenes", action="store_true", help="Add marker sections for early video scene-change candidates.")
    parser.add_argument("--video-scene-threshold", type=float, default=0.35, help="ffmpeg scene score threshold for video scene markers (default: 0.35).")
    parser.add_argument("--video-scene-min-gap-sec", type=float, default=2.0, help="Minimum spacing between video scene markers (default: 2.0).")
    parser.add_argument("--detect-audio-scenes", action="store_true", help="Add marker sections for early audio program-change candidates.")
    parser.add_argument("--audio-scene-window-sec", type=float, default=0.5, help="Window size for audio change analysis (default: 0.5).")
    parser.add_argument("--audio-scene-threshold-db", type=float, default=8.0, help="Minimum RMS delta in dB to mark an audio scene change (default: 8.0).")
    parser.add_argument("--audio-scene-min-gap-sec", type=float, default=2.0, help="Minimum spacing between audio scene markers (default: 2.0).")
    return parser.parse_args()


def _count_text(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def main() -> None:
    args = _parse_args()
    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    if not input_path.exists():
        print(f"[analyze_spacetime_plan] input not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    try:
        media = probe_media(input_path)
    except Exception as exc:
        print(f"[analyze_spacetime_plan] ffprobe failed: {exc}", file=sys.stderr)
        sys.exit(2)

    duration_sec = float(media.get("duration_sec") or 0.0)
    if duration_sec <= 0:
        print(f"[analyze_spacetime_plan] unable to determine duration for {input_path}", file=sys.stderr)
        sys.exit(3)
    if not media.get("has_audio"):
        print(f"[analyze_spacetime_plan] no audio stream found in {input_path}", file=sys.stderr)
        sys.exit(4)

    try:
        detected_silences = detect_silences(input_path, args.threshold_db, args.min_silence_sec)
    except Exception as exc:
        print(f"[analyze_spacetime_plan] silencedetect failed: {exc}", file=sys.stderr)
        sys.exit(5)

    audible_ranges = invert_ranges(detected_silences, duration_sec=duration_sec)
    if not audible_ranges:
        audible_ranges = [(0.0, duration_sec)]

    keep_ranges = build_keep_ranges(
        audible_ranges=audible_ranges,
        duration_sec=duration_sec,
        trim_edges=bool(args.trim_edges),
        compress_gaps=bool(args.compress_gaps),
        edge_pad_sec=max(0.0, float(args.edge_pad_sec)),
        interior_gap_sec=max(0.0, float(args.interior_gap_sec)),
    )
    actions = build_actions(keep_ranges, duration_sec=duration_sec)
    output_sec = sum(float(action.get("duration_sec") or 0.0) for action in actions if action.get("kind") == "keep")
    removed_sec = max(0.0, duration_sec - output_sec)
    markers: list[dict] = []

    if args.detect_video_scenes and media.get("has_video"):
        try:
            markers.extend(detect_video_scenes(input_path, threshold=float(args.video_scene_threshold), min_gap_sec=max(0.0, float(args.video_scene_min_gap_sec))))
        except Exception as exc:
            print(f"[analyze_spacetime_plan] video scene detect failed: {exc}", file=sys.stderr)

    if args.detect_audio_scenes:
        try:
            markers.extend(
                detect_audio_changes(
                    input_path,
                    window_sec=max(0.05, float(args.audio_scene_window_sec)),
                    delta_threshold_db=max(0.0, float(args.audio_scene_threshold_db)),
                    min_gap_sec=max(0.0, float(args.audio_scene_min_gap_sec)),
                )
            )
        except Exception as exc:
            print(f"[analyze_spacetime_plan] audio scene detect failed: {exc}", file=sys.stderr)

    metadata = {
        "generated_at": utc_now_iso(),
        "source_path": str(input_path),
        "feature": "spacetime-compression",
        "analysis_method": "silencedetect",
        "duration_sec": duration_sec,
        "has_video": bool(media.get("has_video")),
        "has_audio": bool(media.get("has_audio")),
        "trim_edges": bool(args.trim_edges),
        "compress_gaps": bool(args.compress_gaps),
        "threshold_db": float(args.threshold_db),
        "min_silence_sec": float(args.min_silence_sec),
        "edge_pad_sec": max(0.0, float(args.edge_pad_sec)),
        "interior_gap_sec": max(0.0, float(args.interior_gap_sec)),
        "detect_video_scenes": bool(args.detect_video_scenes),
        "video_scene_threshold": float(args.video_scene_threshold),
        "video_scene_min_gap_sec": max(0.0, float(args.video_scene_min_gap_sec)),
        "video_scene_markers": len([marker for marker in markers if marker.get("detector") == "video_scene"]),
        "detect_audio_scenes": bool(args.detect_audio_scenes),
        "audio_scene_window_sec": max(0.05, float(args.audio_scene_window_sec)),
        "audio_scene_threshold_db": max(0.0, float(args.audio_scene_threshold_db)),
        "audio_scene_min_gap_sec": max(0.0, float(args.audio_scene_min_gap_sec)),
        "audio_scene_markers": len([marker for marker in markers if marker.get("detector") == "audio_change"]),
        "detected_silence_regions": len(detected_silences),
        "audible_regions": len(audible_ranges),
        "kept_regions": len([action for action in actions if action.get("kind") == "keep"]),
        "estimated_output_sec": output_sec,
        "estimated_removed_sec": removed_sec,
    }
    marker_bits: list[str] = []
    if metadata["detect_video_scenes"]:
        marker_bits.append(_count_text(int(metadata["video_scene_markers"]), "video scene marker", "video scene markers"))
    if metadata["detect_audio_scenes"]:
        marker_bits.append(_count_text(int(metadata["audio_scene_markers"]), "audio scene marker", "audio scene markers"))
    marker_summary = f" It also added {', '.join(marker_bits)}." if marker_bits else ""
    summary = (
        f"Detected {len(detected_silences)} silent regions across {sec_text(duration_sec)}s of source media. "
        f"The current plan keeps {metadata['kept_regions']} ranges for an estimated output of {sec_text(output_sec)}s "
        f"and removes {sec_text(removed_sec)}s."
        f"{marker_summary} "
        "Edit the `## action` sections if you want to refine individual cuts before rendering."
    )

    write_edit_plan(output_path, title=(args.title or input_path.name).strip() or input_path.name, metadata=metadata, summary=summary, actions=actions, markers=markers)
    print(f"[analyze_spacetime_plan] wrote {output_path} (input={sec_text(duration_sec)}s output={sec_text(output_sec)}s removed={sec_text(removed_sec)}s)", file=sys.stderr)


if __name__ == "__main__":
    main()
