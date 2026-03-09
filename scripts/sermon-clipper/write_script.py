"""Write a video script (markdown) from search clips. Can run search internally or load from JSON."""
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

from _lib import clip_id, default_env, get_feed_title, load_clips_json, load_used_clips
from answer_engine_lib import search_segments


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Write video script (markdown) from themed clips.")
    p.add_argument("--theme", required=True, help="Theme/topic for the video (e.g. forgiveness, prayer).")
    p.add_argument("--title", default="", help="Video title (default: What Pastors Say About [theme]).")
    p.add_argument("--clips", default="", help="Path to clips JSON from search_clips (or run search if omitted).")
    p.add_argument("--env", default="", help="Cache env.")
    p.add_argument("--limit", type=int, default=8, help="Clips to include if running search (default: 8).")
    p.add_argument("--output", "-o", required=True, help="Output markdown path.")
    p.add_argument("--intro", default="", help="Intro text (or use default).")
    p.add_argument("--outro", default="", help="Outro text (or use default).")
    p.add_argument("--target-minutes", type=int, default=15, help="Target video length in minutes (default: 15).")
    p.add_argument("--exclude-used", default="", help="Path to used-clips.json to exclude (when running search internally).")
    return p.parse_args()


def _default_intro(theme: str) -> str:
    return (
        f"[Frame the issue: why does {theme} matter? What question or concern are we exploring? "
        "2–3 sentences. See AGENTS.md for guidance.]"
    )


def _default_outro(theme: str) -> str:
    return (
        "[Wrap up: what did we learn? Where might the viewer go from here? "
        "Full episodes available on prays.be.]"
    )


def _default_transition() -> str:
    return (
        "[Radio-style link: reflect on what just played, add depth, flow into the next. "
        "1–3 sentences. Can use question, concern, or conceit. See AGENTS.md.]"
    )


def _default_title_card_intro(theme: str) -> str:
    return (
        f"[Brief discussion of the issue — 1–2 sentences. Not 'here are some pastors.' "
        f"Set up the journey. Why {theme}? What's at stake?]"
    )


def main() -> None:
    args = _parse_args()
    env = (args.env or "").strip() or default_env()
    cache_dir = _REPO_ROOT / "cache" / env
    db_path = cache_dir / "answer-engine" / "answer_engine.sqlite"

    clips = []
    if args.clips:
        clips = load_clips_json(Path(args.clips))
    else:
        if not db_path.exists():
            print(f"[write_script] DB not found. Run: ae.sh analyze && ae.sh index", file=sys.stderr)
            sys.exit(1)
        used_ids = load_used_clips(Path(args.exclude_used)) if args.exclude_used else set()
        payload = search_segments(
            db_path=db_path,
            q=args.theme,
            limit=400,
            candidates=400,
            include_noncontent=False,
        )
        if payload.get("error"):
            print(f"[write_script] {payload['error']}", file=sys.stderr)
            sys.exit(2)
        results = payload.get("results") or []
        seen_feeds = set()
        for r in results:
            feed = r.get("feed")
            ep_slug = r.get("episode_slug")
            start = float(r.get("start_sec") or 0)
            cid = clip_id(feed, ep_slug, start)
            if feed in seen_feeds:
                continue
            if cid in used_ids:
                continue
            seen_feeds.add(feed)
            clips.append({
                "feed": feed,
                "episode_slug": ep_slug,
                "episode_title": r.get("episode_title"),
                "start_sec": start,
                "end_sec": float(r.get("end_sec") or 0),
                "snippet": r.get("snippet"),
            })
            if len(clips) >= args.limit:
                break

    title = args.title or f"What Pastors Say About {args.theme.title()}"
    intro = args.intro or _default_intro(args.theme)
    outro = args.outro or _default_outro(args.theme)
    title_card_intro = _default_title_card_intro(args.theme)

    lines = [
        f"# Video: {title}",
        "",
        "## metadata",
        f"theme: {args.theme}",
        f"target_duration_minutes: {args.target_minutes}",
        "",
        "## intro",
        intro,
        "",
        "## title_card",
        "id: intro",
        f"text: {title_card_intro}",
        "",
    ]

    for i, c in enumerate(clips, 1):
        feed = c.get("feed") or ""
        feed_title = get_feed_title(env, feed) if feed else ""
        episode_title = c.get("episode_title") or c.get("episode_slug") or ""
        lines.extend([
            "## clip",
            f"feed: {feed}",
            f"episode: {c.get('episode_slug')}",
            f"start_sec: {c.get('start_sec')}",
            f"end_sec: {c.get('end_sec')}",
            f"quote: \"{c.get('snippet', '')}\"",
            f"episode_title: {episode_title}",
            f"feed_title: {feed_title}",
            "",
            "## transition",
            _default_transition(),
            "",
        ])

    lines.extend([
        "## outro",
        outro,
        "",
        "## title_card",
        "id: outro",
        "text: [Closing thought or call to action]",
        "",
    ])

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[write_script] wrote {out_path} ({len(clips)} clips)", file=sys.stderr)


if __name__ == "__main__":
    main()
