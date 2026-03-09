"""Search for 10-25 second clips suitable for vertical shorts. Output JSON."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_AE_ROOT = _REPO_ROOT / "scripts" / "answer-engine"
_PARENT = Path(__file__).resolve().parent
for p in (_REPO_ROOT, _AE_ROOT, _PARENT.parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from _lib import clip_id, default_env, load_used_clips, search_segments_cached


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Search for short clips (10-25s) for vertical shorts.")
    p.add_argument("--theme", required=True, help="Search query (e.g. forgiveness, prayer).")
    p.add_argument("--env", default="", help="Cache env (default: from .vodcasts-env).")
    p.add_argument("--cache", default="", help="Cache dir override.")
    p.add_argument("--limit", type=int, default=4, help="Max clips (default: 4).")
    p.add_argument("--min-clips", type=int, default=2, help="Minimum clips required (default: 2). Single-clip shorts are not acceptable.")
    p.add_argument("--candidates", type=int, default=400, help="FTS candidates for rerank (default: 400).")
    p.add_argument("--include-noncontent", action="store_true", help="Allow intro/ad/outro segments.")
    p.add_argument("--output", "-o", default="", help="Write JSON to file (default: stdout).")
    p.add_argument("--exclude-used", default="", help="Path to used-clips.json to exclude.")
    p.add_argument("--min-duration", type=float, default=10.0, help="Minimum clip seconds (default: 10).")
    p.add_argument("--max-duration", type=float, default=18.0, help="Max clip seconds (default: 18). Tighter for ~50s total.")
    p.add_argument("--max-total-duration", type=float, default=55.0, help="Max total seconds across all clips (default: 55).")
    p.add_argument("--feeds", default="", help="Comma-separated feed slugs to restrict (e.g. church-of-the-highlands-weekend-video).")
    p.add_argument("--no-cache", action="store_true", help="Bypass query cache; run fresh search.")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    env = (args.env or "").strip() or default_env()
    cache_dir = Path(args.cache).resolve() if args.cache else _REPO_ROOT / "cache" / env
    db_path = cache_dir / "answer-engine" / "answer_engine.sqlite"

    if not db_path.exists():
        print(f"[search_shorts] DB not found: {db_path}. Run: ae.sh analyze && ae.sh index", file=sys.stderr)
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
        print(f"[search_shorts] {payload['error']}", file=sys.stderr)
        sys.exit(2)

    results = payload.get("results") or []
    used_ids = load_used_clips(Path(args.exclude_used)) if args.exclude_used else set()
    min_dur = float(args.min_duration)
    max_dur = float(args.max_duration)
    allowed_feeds = {f.strip() for f in (args.feeds or "").split(",") if f.strip()}

    clips = []
    seen_feeds = set()
    for r in results:
        feed = r.get("feed")
        if allowed_feeds and feed not in allowed_feeds:
            continue
        ep_slug = r.get("episode_slug")
        start = float(r.get("start_sec") or 0)
        end = float(r.get("end_sec") or start)
        dur = end - start
        cid = clip_id(feed, ep_slug, start)

        if feed in seen_feeds:
            continue
        if cid in used_ids:
            continue
        if dur < min_dur or dur > max_dur:
            continue

        seen_feeds.add(feed)
        max_total = float(args.max_total_duration or 999)
        total_so_far = sum(c["duration_sec"] for c in clips)
        if total_so_far + dur > max_total and len(clips) >= args.min_clips:
            break
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
        if len(clips) >= args.limit:
            break

    if len(clips) < args.min_clips:
        print(f"[search_shorts] Only {len(clips)} clips found; need at least {args.min_clips}. Try broader query or relax --min-duration/--max-duration.", file=sys.stderr)
        sys.exit(3)

    total_dur = sum(c["duration_sec"] for c in clips)
    out = {"query": args.theme, "clips": clips, "total_duration_sec": total_dur}
    out_json = json.dumps(out, ensure_ascii=False, indent=2)

    if args.output:
        Path(args.output).write_text(out_json, encoding="utf-8")
        print(f"[search_shorts] wrote {len(clips)} clips to {args.output}", file=sys.stderr)
    else:
        print(out_json)


if __name__ == "__main__":
    main()
