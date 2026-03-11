"""Write a short script (markdown) from sermon thought-bite clips."""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_AE_ROOT = _REPO_ROOT / "scripts" / "answer-engine"
_PARENT = Path(__file__).resolve().parent
for p in (_REPO_ROOT, _AE_ROOT, _PARENT.parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from _lib import default_env, get_feed_title, load_clips_json

_STOPWORDS = {
    "about",
    "again",
    "because",
    "being",
    "christ",
    "grace",
    "jesus",
    "lord",
    "mercy",
    "people",
    "prayer",
    "really",
    "their",
    "there",
    "these",
    "those",
    "today",
    "with",
    "your",
}

_CANONICAL_TERMS = [
    "own strength",
    "mercy",
    "grace",
    "peace",
    "love",
    "prayer",
    "hope",
    "healing",
    "forgiveness",
    "repentance",
    "obedience",
    "truth",
    "freedom",
    "gospel",
    "reconciliation",
    "rest",
    "faith",
    "joy",
    "suffering",
    "weakness",
    "strength",
    "wounds",
    "community",
    "trust",
]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Write short script (markdown) from clips.")
    p.add_argument("--theme", required=True, help="Theme (e.g. forgiveness, prayer).")
    p.add_argument("--clips", required=True, help="Path to clips JSON from search_shorts.")
    p.add_argument("--env", default="", help="Cache env.")
    p.add_argument("--output", "-o", required=True, help="Output markdown path.")
    p.add_argument("--intro", default="", help="1-sentence intro hook override.")
    p.add_argument("--outro", default="", help="1-sentence outro override.")
    return p.parse_args()


def _clean_text(text: str, max_chars: int = 120) -> str:
    text = (text or "").replace("\n", " ").replace("\r", " ")
    text = text.replace("…", "...").replace("’", "'").replace("“", '"').replace("”", '"')
    text = re.sub(r"\s+", " ", text).strip().strip('"')
    if len(text) <= max_chars:
        return text
    clipped = text[: max_chars - 3].rsplit(" ", 1)[0].strip()
    return f"{clipped}..."


def _theme_words(theme: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9']+", theme.lower()) if len(word) > 2}


def _canonical_terms(theme: str, text: str, limit: int = 3) -> list[str]:
    theme_words = _theme_words(theme)
    lowered = (text or "").lower()
    found = []
    for term in _CANONICAL_TERMS:
        if theme_words.intersection(set(term.split())):
            continue
        if term in lowered:
            found.append(term)
    return found[:limit]


def _terms(theme: str, text: str, limit: int = 3) -> list[str]:
    theme_words = _theme_words(theme)
    canonical = _canonical_terms(theme, text, limit=limit)
    if canonical:
        return canonical
    counts: Counter[str] = Counter()
    for word in re.findall(r"[a-z0-9']+", (text or "").lower()):
        if len(word) < 4 or word in theme_words or word in _STOPWORDS or not word.isalpha():
            continue
        counts[word] += 1
    return [word for word, _count in counts.most_common(limit)]


def _build_intro(theme: str, clips: list[dict]) -> str:
    count = len(clips)
    lead_terms = _terms(theme, " ".join(str(c.get("snippet") or "") for c in clips), limit=2)
    if len(lead_terms) >= 2:
        return f"{count} quick lines on {theme.lower()}: {lead_terms[0]} and {lead_terms[1]}."
    if lead_terms:
        return f"{count} quick lines on {theme.lower()}: {lead_terms[0]}."
    return f"{count} quick lines on {theme.lower()}."


def _build_outro(theme: str) -> str:
    return f"Full sermons hold the longer context behind these {theme.lower()} lines."


def _build_context(theme: str, clip: dict) -> str:
    terms = _terms(theme, str(clip.get("snippet") or ""), limit=2)
    if len(terms) >= 2:
        return f"{terms[0].title()} / {terms[1].title()}"
    if len(terms) == 1:
        return terms[0].title()
    episode_title = _clean_text(str(clip.get("episode_title") or ""), max_chars=50)
    if episode_title:
        return episode_title
    return theme.title()


def _build_decorators(theme: str, clip: dict) -> str:
    words = _terms(theme, str(clip.get("snippet") or ""), limit=2)
    if words:
        return ", ".join(words)
    return safe_decorator(theme)


def safe_decorator(theme: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", theme.lower()).strip() or "sermon clip"


def main() -> None:
    args = _parse_args()
    env = (args.env or "").strip() or default_env()
    clips = load_clips_json(Path(args.clips))
    if len(clips) < 2:
        print(
            "[write_short_script] Need at least 2 clips. Single-clip shorts are not acceptable.",
            file=sys.stderr,
        )
        sys.exit(1)

    intro = args.intro or _build_intro(args.theme, clips)
    outro = args.outro or _build_outro(args.theme)

    lines = [
        f"# Short: {args.theme.title()}",
        "",
        "## metadata",
        f"theme: {args.theme}",
        "format: thought-bites",
        f"clips: {len(clips)}",
        "",
        "## intro",
        intro,
        "",
    ]

    for clip in clips:
        feed = clip.get("feed") or ""
        feed_title = get_feed_title(env, feed) if feed else ""
        episode_title = clip.get("episode_title") or clip.get("episode_slug") or ""
        quote = _clean_text(str(clip.get("snippet") or ""))
        lines.extend(
            [
                "## clip",
                f"feed: {feed}",
                f"episode: {clip.get('episode_slug')}",
                f"start_sec: {clip.get('start_sec')}",
                f"end_sec: {clip.get('end_sec')}",
                f'quote: "{quote}"',
                f"episode_title: {episode_title}",
                f"feed_title: {feed_title}",
                f"context: {_build_context(args.theme, clip)}",
                f"decorators: {_build_decorators(args.theme, clip)}",
                "",
            ]
        )

    lines.extend(["## outro", outro, ""])

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[write_short_script] wrote {out_path} ({len(clips)} clips)", file=sys.stderr)


if __name__ == "__main__":
    main()
