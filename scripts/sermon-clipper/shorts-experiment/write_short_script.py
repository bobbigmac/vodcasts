"""Write a short script (markdown) from sermon thought-bite clips."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_AE_ROOT = _REPO_ROOT / "scripts" / "answer-engine"
_PARENT = Path(__file__).resolve().parent
for p in (_REPO_ROOT, _AE_ROOT, _PARENT.parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from _lib import default_env, get_feed_title

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

_GENERIC_TERMS = {
    "come",
    "doing",
    "give",
    "know",
    "lord",
    "other",
    "power",
    "really",
    "work",
}

_NEGATIVE_TERMS = {
    "afraid",
    "burden",
    "empty",
    "grieve",
    "lonely",
    "pressure",
    "scared",
    "stuck",
    "weak",
    "worry",
}

_HOPE_TERMS = {
    "freedom",
    "grace",
    "healing",
    "help",
    "hope",
    "joy",
    "love",
    "mercy",
    "peace",
    "rest",
    "strength",
    "trust",
}

_ACTION_TERMS = {
    "ask",
    "believe",
    "bring",
    "choose",
    "follow",
    "open",
    "receive",
    "remember",
    "rest",
    "seek",
    "start",
    "stop",
    "trust",
}

_ROLE_FALLBACKS = {
    "question": "The Tension",
    "problem": "The Pressure",
    "insight": "The Insight",
    "advice": "The Move",
    "hope": "The Relief",
}

_DISPLAY_TERM_FIXUPS = {
    "own strength": "our own strength",
}

_EDITORIAL_VARIANTS = [
    {
        "id": "reframe",
        "opening_kicker": "A Better Frame",
        "opening_context": "Different voices keep challenging the same old instinct.",
        "closing_label": "Carry This Today",
        "reflection_prompt": "Notice where {problem} starts to loosen when {hope} is allowed to lead.",
    },
    {
        "id": "pressure",
        "opening_kicker": "What Keeps Showing Up",
        "opening_context": "This is less one sermon point and more a recurring pressure in real life.",
        "closing_label": "Sit With This",
        "reflection_prompt": "Pay attention to how {problem} disguises itself as wisdom, urgency, or self-protection.",
    },
    {
        "id": "invitation",
        "opening_kicker": "A Small Turn",
        "opening_context": "The thread here is not intensity but direction.",
        "closing_label": "For The Rest Of The Day",
        "reflection_prompt": "Let one small move toward {hope} stay ordinary enough to become real.",
    },
    {
        "id": "diagnosis",
        "opening_kicker": "Name The Drift",
        "opening_context": "Across different churches, the same drift keeps getting named from different angles.",
        "closing_label": "Keep Watch For This",
        "reflection_prompt": "Where has {problem} been forming your reflexes more than you realized?",
    },
]

_STYLE_OPTIONS = [
    "ember",
    "harbor",
    "linen",
    "nocturne",
    "moss",
    "oxide",
    "iris",
    "cobalt",
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
    text = (
        text.replace("â€¦", "...")
        .replace("â€™", "'")
        .replace("â€œ", '"')
        .replace("â€", '"')
        .replace("â€”", "-")
        .replace("—", "-")
    )
    text = re.sub(r"\s+", " ", text).strip().strip('"')
    if len(text) <= max_chars:
        return text
    clipped = text[: max_chars - 3].rsplit(" ", 1)[0].strip()
    return f"{clipped}..."


def _load_payload(path: Path) -> dict:
    if not path.exists():
        return {"clips": []}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return {"clips": raw}
    if isinstance(raw, dict):
        return raw
    return {"clips": []}


def _theme_hash(value: str) -> int:
    return sum(ord(char) for char in str(value or ""))


def _theme_words(theme: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9']+", theme.lower()) if len(word) > 2}


def _display_term(term: str) -> str:
    lowered = str(term or "").strip().lower()
    if not lowered:
        return ""
    return _DISPLAY_TERM_FIXUPS.get(lowered, lowered)


def _title_term(term: str) -> str:
    words = [word for word in re.split(r"\s+", _display_term(term)) if word]
    if not words:
        return ""
    return " ".join(word.capitalize() if word not in {"and", "or", "of", "the", "to"} else word for word in words)


def _clip_motifs(clip: dict) -> list[str]:
    raw = clip.get("motifs")
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        return [part.strip() for part in raw.split(",") if part.strip()]
    return []


def _preferred_terms(theme: str, clip: dict, limit: int = 2) -> list[str]:
    theme_words = _theme_words(theme)
    text_words = [word for word in re.findall(r"[a-z0-9']+", str(clip.get("snippet") or "").lower()) if len(word) >= 4]
    role = str(clip.get("role") or "insight")
    buckets: list[set[str]] = []
    if role == "hope":
        buckets = [_HOPE_TERMS, _ACTION_TERMS, _NEGATIVE_TERMS]
    elif role == "advice":
        buckets = [_ACTION_TERMS, _HOPE_TERMS, _NEGATIVE_TERMS]
    elif role == "problem":
        buckets = [_NEGATIVE_TERMS, _ACTION_TERMS, _HOPE_TERMS]
    else:
        buckets = [_NEGATIVE_TERMS, _HOPE_TERMS, _ACTION_TERMS]

    picked: list[str] = []
    for bucket in buckets:
        for word in text_words:
            if word in bucket and word not in picked and word not in _GENERIC_TERMS:
                picked.append(word)
                if len(picked) >= limit:
                    return picked

    for motif in _clip_motifs(clip):
        display = _display_term(motif)
        if not display:
            continue
        if display in picked or display in theme_words or display in _GENERIC_TERMS:
            continue
        picked.append(display)
        if len(picked) >= limit:
            return picked

    for word in text_words:
        if word in theme_words or word in _STOPWORDS or word in _GENERIC_TERMS:
            continue
        if word not in picked:
            picked.append(word)
            if len(picked) >= limit:
                return picked
    return picked


def _top_terms(theme: str, payload: dict, clips: list[dict], limit: int = 3) -> list[str]:
    theme_words = _theme_words(theme)
    terms: list[str] = []
    for clip in clips:
        terms.extend(_preferred_terms(theme, clip, limit=2))
    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        lowered = _display_term(term)
        if not lowered or lowered in seen:
            continue
        if lowered in _GENERIC_TERMS:
            continue
        if all(word in _STOPWORDS or word in theme_words for word in re.findall(r"[a-z0-9']+", lowered)):
            continue
        seen.add(lowered)
        deduped.append(lowered)
        if len(deduped) >= limit:
            break
    return deduped


def _role_terms(clips: list[dict], role: str, limit: int = 2) -> list[str]:
    found: list[str] = []
    for clip in clips:
        if str(clip.get("role") or "") != role:
            continue
        for motif in _preferred_terms("", clip, limit=2):
            display = _display_term(motif)
            if display and display not in found:
                found.append(display)
                if len(found) >= limit:
                    return found
    return found


def _build_intro(theme: str, payload: dict, clips: list[dict]) -> str:
    problem_terms = _role_terms(clips, "problem", limit=2)
    hope_terms = _role_terms(clips, "hope", limit=2) or _role_terms(clips, "advice", limit=2)
    top_terms = _top_terms(theme, payload, clips, limit=3)
    if theme.strip().lower() == "own strength":
        target = hope_terms[0] if hope_terms else "rest"
        if target == "strength":
            target = "received strength"
        return f"When everything leans on our own strength, the deeper invitation is toward {target}."
    if problem_terms and hope_terms:
        return f"When {problem_terms[0]} starts to feel normal, the better way keeps moving toward {hope_terms[0]}."
    if hope_terms:
        target = hope_terms[0]
        if target in _theme_words(theme):
            target = f"received {target}"
        return f"{theme.lower().capitalize()} moves out of self-reliance and toward {target}."
    if len(top_terms) >= 2:
        return f"Real life often moves from {top_terms[0]} toward {top_terms[1]} one decision at a time."
    if top_terms:
        return f"One real-life thread keeps surfacing here: {top_terms[0]}."
    return f"{theme.lower().capitalize()} gets practical when it reaches ordinary life."


def _build_outro(theme: str, payload: dict, clips: list[dict]) -> str:
    hope_terms = _role_terms(clips, "hope", limit=2) or _top_terms(theme, payload, clips, limit=2)
    if theme.strip().lower() == "own strength":
        target = hope_terms[0] if hope_terms else "received strength"
        if target == "strength":
            target = "received strength"
        return f"The way forward is not carrying this alone, but receiving {target}."
    if hope_terms:
        target = hope_terms[0]
        if target in _theme_words(theme):
            target = f"received {target}"
        return f"The way forward turns away from carrying this alone and back toward {target}."
    return f"There is another way besides carrying {theme.lower()} alone."


def _editorial_terms(theme: str, payload: dict, clips: list[dict]) -> tuple[str, str]:
    problem_terms = _role_terms(clips, "problem", limit=2)
    hope_terms = _role_terms(clips, "hope", limit=2) or _role_terms(clips, "advice", limit=2)
    top_terms = _top_terms(theme, payload, clips, limit=3)
    problem = _display_term(problem_terms[0]) if problem_terms else ""
    hope = _display_term(hope_terms[0]) if hope_terms else ""
    if not problem and top_terms:
        problem = _display_term(top_terms[0])
    if not hope:
        if len(top_terms) >= 2:
            hope = _display_term(top_terms[1])
        elif top_terms:
            hope = _display_term(top_terms[0])
    if not problem:
        problem = _display_term(theme) or "this pattern"
    if not hope:
        hope = _display_term(theme) or "a steadier way"
    return problem, hope


def _select_editorial_variant(theme: str, clips: list[dict]) -> dict:
    seed = _theme_hash(theme) + len(clips) * 17
    return _EDITORIAL_VARIANTS[seed % len(_EDITORIAL_VARIANTS)]


def _format_reflection_prompt(template: str, problem: str, hope: str) -> str:
    return template.format(
        problem=_display_term(problem) or "the pressure",
        hope=_display_term(hope) or "a steadier way",
    )


def _build_editorial(theme: str, payload: dict, clips: list[dict]) -> dict[str, str]:
    variant = _select_editorial_variant(theme, clips)
    problem, hope = _editorial_terms(theme, payload, clips)
    style = _STYLE_OPTIONS[(_theme_hash(theme) + len(clips) * 11) % len(_STYLE_OPTIONS)]
    return {
        "structure": str(variant["id"]),
        "style": style,
        "opening_kicker": str(variant["opening_kicker"]),
        "opening_context": str(variant["opening_context"]),
        "closing_label": str(variant["closing_label"]),
        "reflection_prompt": _format_reflection_prompt(str(variant["reflection_prompt"]), problem, hope),
    }


def _build_context(clip: dict) -> str:
    motifs = [_title_term(term) for term in _preferred_terms("", clip, limit=2) if _title_term(term)]
    if len(motifs) >= 2:
        return f"{motifs[0]} / {motifs[1]}"
    if len(motifs) == 1:
        return motifs[0]
    return _ROLE_FALLBACKS.get(str(clip.get("role") or "insight"), "The Insight")


def _build_decorators(theme: str, clip: dict) -> str:
    motifs = _preferred_terms(theme, clip, limit=2)
    if motifs:
        return ", ".join(_display_term(term) for term in motifs[:2])
    words = [word for word in re.findall(r"[a-z0-9']+", str(clip.get("snippet") or "").lower()) if len(word) >= 4]
    theme_words = _theme_words(theme)
    filtered = [word for word in words if word not in _STOPWORDS and word not in theme_words]
    return ", ".join(filtered[:2]) if filtered else re.sub(r"[^a-z0-9 ]+", "", theme.lower()).strip() or "sermon clip"


def main() -> None:
    args = _parse_args()
    env = (args.env or "").strip() or default_env()
    payload = _load_payload(Path(args.clips))
    clips = list(payload.get("clips") or [])
    if len(clips) < 2:
        print(
            "[write_short_script] Need at least 2 clips. Single-clip shorts are not acceptable.",
            file=sys.stderr,
        )
        sys.exit(1)

    intro = args.intro or _build_intro(args.theme, payload, clips)
    outro = args.outro or _build_outro(args.theme, payload, clips)
    editorial = _build_editorial(args.theme, payload, clips)

    lines = [
        f"# Short: {args.theme.title()}",
        "",
        "## metadata",
        f"theme: {args.theme}",
        "format: curated thought-bites",
        "selection: multi-feed practical arc",
        f"clips: {len(clips)}",
        f"structure: {editorial['structure']}",
        f"style: {editorial['style']}",
        f"opening_kicker: {editorial['opening_kicker']}",
        f"opening_context: {editorial['opening_context']}",
        f"closing_label: {editorial['closing_label']}",
        f"reflection_prompt: {editorial['reflection_prompt']}",
        "",
        "## intro",
        _clean_text(intro, max_chars=120),
        "",
    ]

    for clip in clips:
        feed = str(clip.get("feed") or "")
        feed_title = get_feed_title(env, feed) if feed else ""
        episode_title = _clean_text(str(clip.get("episode_title") or clip.get("episode_slug") or ""), max_chars=90)
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
                f"feed_title: {_clean_text(feed_title, max_chars=70)}",
                f"context: {_build_context(clip)}",
                f"decorators: {_build_decorators(args.theme, clip)}",
                "",
            ]
        )

    lines.extend(["## outro", _clean_text(outro, max_chars=120), ""])

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[write_short_script] wrote {out_path} ({len(clips)} clips)", file=sys.stderr)


if __name__ == "__main__":
    main()
