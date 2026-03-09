"""Search the answer-engine index for clips matching a theme. Output JSON of segments with timestamps."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_AE_ROOT = _REPO_ROOT / "scripts" / "answer-engine"
for p in (_REPO_ROOT, _AE_ROOT, Path(__file__).resolve().parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from _lib import (
    clip_has_render_requirements,
    clip_id,
    default_cache_dir,
    default_env,
    default_transcripts_root,
    load_used_clips,
    search_segments_cached,
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Search transcript index for themed clips.")
    p.add_argument("--theme", required=True, help="Search query / theme (e.g. forgiveness, prayer, suffering).")
    p.add_argument("--env", default="", help="Cache env (default: from .vodcasts-env).")
    p.add_argument("--cache", default="", help="Cache dir override.")
    p.add_argument("--limit", type=int, default=10, help="Max clips to return (default: 10).")
    p.add_argument("--candidates", type=int, default=400, help="FTS candidates for rerank (default: 400).")
    p.add_argument("--include-noncontent", action="store_true", help="Allow intro/ad/outro segments.")
    p.add_argument("--output", "-o", default="", help="Write JSON to file (default: stdout).")
    p.add_argument("--exclude-used", default="", help="Path to used-clips.json to exclude already-used clips.")
    p.add_argument("--max-duration", type=float, default=120.0, help="Favor clips under this seconds (default: 120).")
    p.add_argument("--min-duration", type=float, default=15.0, help="Minimum clip length in seconds (default: 15).")
    p.add_argument("--target-duration", type=float, default=900.0, help="Target total video duration in seconds (default: 900 = 15min).")
    p.add_argument("--allow-audio", action="store_true", help="Allow audio-only enclosures in search results.")
    p.add_argument("--allow-missing-transcript", action="store_true", help="Allow clips without local transcript files.")
    p.add_argument("--no-cache", action="store_true", help="Bypass query cache; run fresh search.")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    env = (args.env or "").strip() or default_env()
    cache_dir = Path(args.cache).resolve() if args.cache else default_cache_dir(env)
    db_path = cache_dir / "answer-engine" / "answer_engine.sqlite"
    transcripts_root = default_transcripts_root()

    if not db_path.exists():
        print(f"[search_clips] DB not found: {db_path}. Run: ae.sh analyze && ae.sh index", file=sys.stderr)
        sys.exit(1)

    payload = search_segments_cached(
        cache_dir=cache_dir,
        db_path=db_path,
        q=args.theme,
        limit=int(args.candidates),
        candidates=int(args.candidates),
        include_noncontent=bool(args.include_noncontent),
        no_cache=bool(args.no_cache),
    )

    if payload.get("error"):
        print(f"[search_clips] {payload['error']}", file=sys.stderr)
        sys.exit(2)

    results = payload.get("results") or []
    used_ids = load_used_clips(Path(args.exclude_used)) if args.exclude_used else set()
    max_dur = float(args.max_duration)
    min_dur = float(args.min_duration)
    target_dur = float(args.target_duration)
    require_video = not bool(args.allow_audio)
    require_transcript = not bool(args.allow_missing_transcript)

    clips = []
    seen_feeds = set()
    total_dur = 0.0
    rejected = {
        "duplicate_feed": 0,
        "used_clip": 0,
        "too_short": 0,
        "not_renderable": 0,
        "too_long": 0,
    }
    for r in results:
        feed = r.get("feed")
        ep_slug = r.get("episode_slug")
        start = float(r.get("start_sec") or 0)
        end = float(r.get("end_sec") or start)
        dur = end - start
        cid = clip_id(feed, ep_slug, start)

        if feed in seen_feeds:
            rejected["duplicate_feed"] += 1
            continue
        if cid in used_ids:
            rejected["used_clip"] += 1
            continue
        if dur < min_dur:
            rejected["too_short"] += 1
            continue
        if not clip_has_render_requirements(
            cache_dir=cache_dir,
            transcripts_root=transcripts_root,
            feed_slug=str(feed or ""),
            episode_slug=str(ep_slug or ""),
            require_video=require_video,
            require_transcript=require_transcript,
        ):
            rejected["not_renderable"] += 1
            continue

        over_max = dur > max_dur
        if over_max and total_dur >= target_dur * 0.8:
            rejected["too_long"] += 1
            continue
        if over_max and len(clips) >= 3:
            rejected["too_long"] += 1
            continue

        seen_feeds.add(feed)
        clips.append(
            {
                "feed": feed,
                "episode_slug": ep_slug,
                "episode_title": r.get("episode_title"),
                "episode_date": r.get("episode_date"),
                "start_sec": start,
                "end_sec": end,
                "duration_sec": dur,
                "snippet": r.get("snippet"),
                "score": float(r.get("score") or 0),
                "share_path": r.get("share_path"),
            }
        )
        total_dur += dur
        if len(clips) >= args.limit:
            break
        if total_dur >= target_dur:
            break

    out = {
        "query": args.theme,
        "clips": clips,
        "total_duration_sec": total_dur,
        "filters": {
            "require_video": require_video,
            "require_transcript": require_transcript,
            "min_duration": min_dur,
            "max_duration": max_dur,
            "target_duration": target_dur,
        },
        "rejected_counts": rejected,
    }
    out_json = json.dumps(out, ensure_ascii=False, indent=2)

    if args.output:
        Path(args.output).write_text(out_json, encoding="utf-8")
        print(f"[search_clips] wrote {len(clips)} clips to {args.output}", file=sys.stderr)
    else:
        print(out_json)


if __name__ == "__main__":
    main()
