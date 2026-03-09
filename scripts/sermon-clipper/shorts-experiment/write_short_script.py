"""Write a short script (markdown) from search clips. Format for vertical shorts."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_AE_ROOT = _REPO_ROOT / "scripts" / "answer-engine"
_PARENT = Path(__file__).resolve().parent
for p in (_REPO_ROOT, _AE_ROOT, _PARENT.parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from _lib import default_env, get_feed_title, load_clips_json


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Write short script (markdown) from clips.")
    p.add_argument("--theme", required=True, help="Theme (e.g. forgiveness, prayer).")
    p.add_argument("--clips", required=True, help="Path to clips JSON from search_shorts.")
    p.add_argument("--env", default="", help="Cache env.")
    p.add_argument("--output", "-o", required=True, help="Output markdown path.")
    p.add_argument("--intro", default="", help="1-sentence intro hook (or placeholder).")
    p.add_argument("--outro", default="", help="1-sentence outro (or placeholder).")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    env = (args.env or "").strip() or default_env()
    clips = load_clips_json(Path(args.clips))
    if len(clips) < 2:
        print("[write_short_script] Need at least 2 clips. Single-clip shorts are not acceptable. Run search_shorts with broader query or relax --min-duration/--max-duration.", file=sys.stderr)
        sys.exit(1)

    intro = args.intro or f"[1 sentence hook: why {args.theme}?]"
    outro = args.outro or "[1 sentence CTA or punchline]"

    lines = [
        f"# Short: {args.theme.title()}",
        "",
        "## metadata",
        f"theme: {args.theme}",
        f"clips: {len(clips)}",
        "",
        "## intro",
        intro,
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
            "context: [1-2 sentences. What is the pastor saying? Why does it matter?]",
            "decorators: [Optional: keywords, emojis, related ideas for onscreen flair]",
            "",
        ])

    lines.extend([
        "## outro",
        outro,
        "",
    ])

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[write_short_script] wrote {out_path} ({len(clips)} clips)", file=sys.stderr)


if __name__ == "__main__":
    main()
