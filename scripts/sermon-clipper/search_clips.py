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

from _lib import clip_id, default_env, load_used_clips
from answer_engine_lib import search_segments


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
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    env = (args.env or "").strip() or default_env()
    cache_dir = Path(args.cache).resolve() if args.cache else Path(__file__).resolve().parents[2] / "cache" / env
    db_path = cache_dir / "answer-engine" / "answer_engine.sqlite"

    if not db_path.exists():
        print(f"[search_clips] DB not found: {db_path}. Run: ae.sh analyze && ae.sh index", file=sys.stderr)
        sys.exit(1)

    # Request more results than needed so one-per-feed filtering yields enough
    payload = search_segments(
        db_path=db_path,
        q=args.theme,
        limit=int(args.candidates),
        candidates=int(args.candidates),
        include_noncontent=bool(args.include_noncontent),
    )

    if payload.get("error"):
        print(f"[search_clips] {payload['error']}", file=sys.stderr)
        sys.exit(2)

    results = payload.get("results") or []
    used_ids = load_used_clips(Path(args.exclude_used)) if args.exclude_used else set()
    max_dur = float(args.max_duration)
    min_dur = float(args.min_duration)
    target_dur = float(args.target_duration)

    clips = []
    seen_feeds = set()
    total_dur = 0.0
    for r in results:
        feed = r.get("feed")
        ep_slug = r.get("episode_slug")
        start = float(r.get("start_sec") or 0)
        end = float(r.get("end_sec") or start)
        dur = end - start
        cid = clip_id(feed, ep_slug, start)

        if feed in seen_feeds:
            continue
        if cid in used_ids:
            continue
        if dur < min_dur:
            continue

        # Prefer clips under max_duration; allow longer if needed to reach target
        over_max = dur > max_dur
        if over_max and total_dur >= target_dur * 0.8:
            continue  # Skip long clips if we already have enough
        if over_max and len(clips) >= 3:
            continue  # Prefer shorter clips once we have a few

        seen_feeds.add(feed)
        clips.append({
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
        })
        total_dur += dur
        if len(clips) >= args.limit:
            break
        if total_dur >= target_dur:
            break

    out = {"query": args.theme, "clips": clips, "total_duration_sec": total_dur}
    out_json = json.dumps(out, ensure_ascii=False, indent=2)

    if args.output:
        Path(args.output).write_text(out_json, encoding="utf-8")
        print(f"[search_clips] wrote {len(clips)} clips to {args.output}", file=sys.stderr)
    else:
        print(out_json)


if __name__ == "__main__":
    main()
