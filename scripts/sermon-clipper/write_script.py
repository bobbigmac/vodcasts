"""Write a video script (markdown) from search clips."""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
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
    get_feed_title,
    load_clips_json,
    load_used_clips,
    search_segments_cached,
)

_STOPWORDS = {
    "about",
    "after",
    "again",
    "against",
    "being",
    "before",
    "could",
    "every",
    "forgiveness",
    "grace",
    "their",
    "there",
    "these",
    "those",
    "through",
    "where",
    "which",
    "while",
    "would",
    "still",
    "prayer",
    "suffering",
    "people",
    "thing",
    "things",
    "christ",
    "jesus",
    "lord",
    "today",
    "really",
    "gonna",
    "going",
    "your",
    "what",
    "when",
    "with",
    "that",
    "this",
    "have",
    "from",
    "into",
    "just",
    "them",
    "they",
    "then",
    "than",
    "were",
    "been",
    "them",
    "ourselves",
}

_CANONICAL_TERMS = [
    "own strength",
    "new creation",
    "new life",
    "holy spirit",
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
    "community",
    "patience",
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
    "relationships",
    "enemy",
    "renewal",
    "calling",
    "trust",
    "confession",
    "worship",
    "generosity",
]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Write video script (markdown) from themed clips.")
    p.add_argument("--theme", required=True, help="Theme/topic for the video (e.g. forgiveness, prayer).")
    p.add_argument("--title", default="", help="Video title override.")
    p.add_argument("--clips", default="", help="Path to clips JSON from search_clips (or run search if omitted).")
    p.add_argument("--env", default="", help="Cache env.")
    p.add_argument("--limit", type=int, default=6, help="Clips to include if running search (default: 6).")
    p.add_argument("--output", "-o", required=True, help="Output markdown path.")
    p.add_argument("--intro", default="", help="Intro text override.")
    p.add_argument("--outro", default="", help="Outro text override.")
    p.add_argument("--target-minutes", type=int, default=15, help="Target video length in minutes (default: 15).")
    p.add_argument("--exclude-used", default="", help="Path to used-clips.json to exclude (when running search internally).")
    p.add_argument("--no-cache", action="store_true", help="Bypass query cache when running search internally.")
    return p.parse_args()


def _clean_text(text: str, max_chars: int = 180) -> str:
    text = (text or "").replace("\n", " ").replace("\r", " ")
    text = text.replace("…", "...").replace("’", "'").replace("“", '"').replace("”", '"')
    text = re.sub(r"\s+", " ", text).strip().strip('"')
    if len(text) <= max_chars:
        return text
    clipped = text[: max_chars - 3].rsplit(" ", 1)[0].strip()
    return f"{clipped}..."


def _theme_words(theme: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']+", (theme or "").lower()) if len(w) > 2}


def _canonical_terms(theme: str, text: str, limit: int = 4) -> list[str]:
    theme_words = _theme_words(theme)
    lowered = (text or "").lower()
    found = []
    for term in _CANONICAL_TERMS:
        words = set(term.split())
        if theme_words.intersection(words):
            continue
        if term in lowered:
            found.append(term)
    return found[:limit]


def _focus_terms(theme: str, clips: list[dict], limit: int = 5) -> list[str]:
    theme_words = _theme_words(theme)
    canonical_counts: Counter[str] = Counter()
    counts: Counter[str] = Counter()
    for clip in clips:
        text = " ".join(
            str(clip.get(key) or "")
            for key in ("snippet", "quote", "episode_title", "episode_slug")
        ).lower()
        for term in _canonical_terms(theme, text, limit=limit):
            canonical_counts[term] += 1
        for word in re.findall(r"[a-z0-9']+", text):
            if len(word) < 4 or word in _STOPWORDS or word in theme_words or not word.isalpha():
                continue
            counts[word] += 1
    if canonical_counts:
        return [word for word, _count in canonical_counts.most_common(limit)]
    return [word for word, _count in counts.most_common(limit)]


def _clip_focus(clip: dict, theme: str) -> str:
    joined_text = " ".join(str(clip.get(key) or "") for key in ("snippet", "quote", "episode_title"))
    terms = _canonical_terms(theme, joined_text, limit=2)
    if terms:
        if len(terms) == 1:
            return terms[0]
        return f"{terms[0]} and {terms[1]}"
    return "ordinary faith"


def _build_title(theme: str, keywords: list[str]) -> str:
    theme_text = (theme or "This Theme").strip()
    if re.search(r"\b(when|why|how|can|should|what)\b", theme_text.lower()):
        return theme_text[:1].upper() + theme_text[1:]
    if keywords and all(keyword.isalpha() or " " in keyword for keyword in keywords[:1]):
        return f"When {theme_text.title()} Meets {keywords[0].title()}"
    return f"When {theme_text.title()} Gets Real"


def _build_intro(theme: str, keywords: list[str]) -> str:
    theme_text = theme.strip()
    if len(keywords) >= 2:
        return (
            f"{theme_text.title()} is rarely abstract. It shows up in wounds, habits, and decisions that cost us something. "
            f"These clips trace the theme through {keywords[0]}, {keywords[1]}, and the hard work of living it out."
        )
    return (
        f"{theme_text.title()} sounds simple until it reaches real life. "
        f"These clips stay with the question long enough to show what it demands and what it gives back."
    )


def _build_title_card_intro(theme: str, keywords: list[str]) -> str:
    theme_text = theme.strip().lower()
    if keywords:
        lead = ", ".join(word.title() for word in keywords[:3])
        return f"A guided listen through {theme_text}, moving through {lead} toward lived obedience."
    return f"A guided listen through {theme_text}, moving from tension to practice."


def _build_transition(theme: str, current_clip: dict, next_clip: dict) -> str:
    current_focus = _clip_focus(current_clip, theme)
    next_focus = _clip_focus(next_clip, theme)
    return (
        f"That clip keeps {theme.lower()} close to {current_focus}. "
        f"The next voice turns toward {next_focus}, showing how the same theme lands in a different part of life."
    )


def _build_outro(theme: str, keywords: list[str]) -> str:
    if keywords:
        joined = ", ".join(keywords[:3])
        return (
            f"{theme.title()} is not one slogan or one technique. Across these clips it takes shape through {joined}. "
            "If one of these voices helped, the full sermons give the surrounding context and the slower pastoral work."
        )
    return (
        f"{theme.title()} takes more than a strong line or a single clip. "
        "The full sermons give the wider context behind these excerpts."
    )


def _load_or_search_clips(args: argparse.Namespace, env: str) -> list[dict]:
    if args.clips:
        return load_clips_json(Path(args.clips))

    cache_dir = default_cache_dir(env)
    db_path = cache_dir / "answer-engine" / "answer_engine.sqlite"
    transcripts_root = default_transcripts_root()
    if not db_path.exists():
        print("[write_script] DB not found. Run: ae.sh analyze && ae.sh index", file=sys.stderr)
        sys.exit(1)

    used_ids = load_used_clips(Path(args.exclude_used)) if args.exclude_used else set()
    payload = search_segments_cached(
        cache_dir=cache_dir,
        db_path=db_path,
        q=args.theme,
        limit=400,
        candidates=400,
        include_noncontent=False,
        no_cache=bool(args.no_cache),
    )
    if payload.get("error"):
        print(f"[write_script] {payload['error']}", file=sys.stderr)
        sys.exit(2)

    clips = []
    seen_feeds = set()
    for r in payload.get("results") or []:
        feed = r.get("feed")
        episode_slug = r.get("episode_slug")
        start = float(r.get("start_sec") or 0)
        end = float(r.get("end_sec") or start)
        cid = clip_id(feed, episode_slug, start)
        if feed in seen_feeds or cid in used_ids:
            continue
        if end - start < 15:
            continue
        if not clip_has_render_requirements(
            cache_dir=cache_dir,
            transcripts_root=transcripts_root,
            feed_slug=str(feed or ""),
            episode_slug=str(episode_slug or ""),
            require_video=True,
            require_transcript=True,
        ):
            continue
        seen_feeds.add(feed)
        clips.append(
            {
                "feed": feed,
                "episode_slug": episode_slug,
                "episode_title": r.get("episode_title"),
                "start_sec": start,
                "end_sec": end,
                "duration_sec": end - start,
                "snippet": r.get("snippet"),
            }
        )
        if len(clips) >= args.limit:
            break
    return clips


def main() -> None:
    args = _parse_args()
    env = (args.env or "").strip() or default_env()
    clips = _load_or_search_clips(args, env)
    if not clips:
        print("[write_script] No clips available to write script.", file=sys.stderr)
        sys.exit(3)

    keywords = _focus_terms(args.theme, clips)
    title = args.title or _build_title(args.theme, keywords)
    intro = args.intro or _build_intro(args.theme, keywords)
    outro = args.outro or _build_outro(args.theme, keywords)
    title_card_intro = _build_title_card_intro(args.theme, keywords)

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

    for i, clip in enumerate(clips):
        feed = clip.get("feed") or ""
        feed_title = clip.get("feed_title") or (get_feed_title(env, feed) if feed else "")
        episode_title = clip.get("episode_title") or clip.get("episode_slug") or ""
        quote = _clean_text(str(clip.get("snippet") or clip.get("quote") or ""))
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
                "",
            ]
        )
        if i < len(clips) - 1:
            lines.extend(
                [
                    "## transition",
                    _build_transition(args.theme, clip, clips[i + 1]),
                    "",
                ]
            )

    lines.extend(
        [
            "## outro",
            outro,
            "",
            "## title_card",
            "id: outro",
            "text: Full episodes and full context at prays.be",
            "",
        ]
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[write_script] wrote {out_path} ({len(clips)} clips)", file=sys.stderr)


if __name__ == "__main__":
    main()
