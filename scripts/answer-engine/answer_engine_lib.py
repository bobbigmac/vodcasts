from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import sys
import time
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

# When executed directly, sys.path[0] is this directory (scripts/answer-engine),
# so add the repo root to allow `import scripts.*`.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.shared import VODCASTS_ROOT, normalize_ws, strip_html

import pysrt  # type: ignore
import snowballstemmer  # type: ignore
import webvtt  # type: ignore
from stop_words import get_stop_words  # type: ignore


_PLAYABLE_TRANSCRIPT_EXTS = {".vtt", ".srt"}

# Lightweight stopword list: start with the “usual suspects” + subtitle filler.
_STOPWORDS_RAW = {
    "a",
    "about",
    "above",
    "after",
    "again",
    "against",
    "all",
    "also",
    "am",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "because",
    "been",
    "before",
    "being",
    "below",
    "between",
    "both",
    "but",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "doing",
    "down",
    "during",
    "each",
    "few",
    "for",
    "from",
    "further",
    "had",
    "has",
    "have",
    "having",
    "he",
    "her",
    "here",
    "hers",
    "herself",
    "him",
    "himself",
    "his",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "itself",
    "just",
    "me",
    "more",
    "most",
    "my",
    "myself",
    "no",
    "nor",
    "not",
    "now",
    "of",
    "off",
    "on",
    "once",
    "only",
    "or",
    "other",
    "our",
    "ours",
    "ourselves",
    "out",
    "over",
    "own",
    "s",
    "same",
    "she",
    "should",
    "so",
    "some",
    "such",
    "t",
    "than",
    "that",
    "the",
    "their",
    "theirs",
    "them",
    "themselves",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "to",
    "too",
    "under",
    "until",
    "up",
    "us",
    "very",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "who",
    "whom",
    "why",
    "will",
    "with",
    "you",
    "your",
    "yours",
    "yourself",
    "yourselves",
    # subtitle filler / low-signal
    "um",
    "uh",
    "yeah",
    "okay",
    "ok",
    "right",
    "like",
    "kind",
    "sort",
    "got",
    "gonna",
    "wanna",
    "dont",
    "can't",
    "cant",
    "won't",
    "wont",
    "i'm",
    "im",
    "you're",
    "youre",
    "we're",
    "were",
    "it's",
    "its",
}

# “Heart / soul / faith / relationships” themed terms: used for tie-breaking / rerank,
# not for initial retrieval (to avoid irrelevant matches).
_THEME_WEIGHTS_RAW: dict[str, float] = {
    # faith / core theology
    "jesus": 3.0,
    "christ": 2.5,
    "god": 2.0,
    "gospel": 2.5,
    "scripture": 2.2,
    "bible": 2.0,
    "pray": 2.2,
    "prayer": 2.2,
    "holy": 1.2,
    "spirit": 1.8,
    "church": 1.6,
    "sin": 2.0,
    "repent": 2.2,
    "repentance": 2.2,
    "grace": 2.0,
    "mercy": 2.0,
    "forgive": 2.0,
    "forgiveness": 2.0,
    "salvation": 2.0,
    "cross": 1.8,
    "resurrection": 2.0,
    "worship": 1.8,
    # heart / inner life
    "heart": 2.0,
    "soul": 2.0,
    "spiritual": 1.8,
    "discipline": 1.4,
    "humility": 1.6,
    "pride": 1.6,
    "shame": 1.4,
    "guilt": 1.2,
    "hope": 1.6,
    "peace": 1.6,
    "joy": 1.6,
    "love": 1.6,
    "fear": 1.2,
    "anxiety": 1.4,
    "worry": 1.2,
    "stress": 1.2,
    # relationships / culture / advice
    "marriage": 1.8,
    "husband": 1.2,
    "wife": 1.2,
    "family": 1.3,
    "friend": 1.1,
    "relationships": 1.4,
    "relationship": 1.4,
    "trust": 1.4,
    "betrayal": 1.4,
    "conflict": 1.2,
    "anger": 1.2,
    "resentment": 1.4,
    "forgive": 2.0,
}

_SYNONYMS_RAW: dict[str, set[str]] = {
    "stress": {"anxiety", "worry", "fear", "pressure"},
    "anxiety": {"worry", "fear", "stress", "panic"},
    "forgive": {"forgiveness", "reconcile", "reconciliation", "mercy", "grace"},
    "forgiveness": {"forgive", "reconcile", "reconciliation", "mercy", "grace"},
    "anger": {"resentment", "bitterness", "rage"},
    "depression": {"despair", "hopeless", "sadness"},
    "trust": {"betrayal", "faithful", "faithfulness"},
    "marriage": {"husband", "wife", "spouse", "divorce"},
    "pray": {"prayer", "praying"},
    "prayer": {"pray", "praying"},
    "faith": {"belief", "trust"},
}

# Broader semantic neighborhoods for question expansion. These are not strict
# synonyms; they are adjacent concepts and listener-facing language that often
# show up when a speaker talks around the same issue.
_PROBLEM_SPACE_RAW: dict[str, set[str]] = {
    "anxiety": {"fear", "worry", "panic", "rest", "peace", "control", "overwhelm", "burden", "trust"},
    "fear": {"anxiety", "worry", "panic", "threat", "uncertainty", "trust", "peace", "courage"},
    "worry": {"anxiety", "fear", "burden", "trouble", "peace", "trust", "tomorrow"},
    "stress": {"pressure", "overwhelm", "burden", "rest", "peace", "control", "fatigue"},
    "doubt": {"questions", "uncertainty", "faith", "trust", "assurance", "confidence", "unbelief"},
    "lonely": {"alone", "isolation", "community", "belonging", "friendship", "family", "rejection"},
    "loneliness": {"alone", "isolation", "community", "belonging", "friendship", "rejection"},
    "alone": {"lonely", "loneliness", "isolation", "community", "belonging", "friendship"},
    "forgive": {"hurt", "wound", "offense", "bitterness", "resentment", "reconciliation", "mercy", "grace"},
    "forgiveness": {"hurt", "wound", "offense", "bitterness", "resentment", "reconciliation", "mercy", "grace"},
    "betrayal": {"trust", "wound", "hurt", "resentment", "reconciliation", "healing", "faithfulness"},
    "anger": {"resentment", "bitterness", "offense", "wound", "grace", "mercy"},
    "shame": {"guilt", "worth", "acceptance", "identity", "mercy", "grace", "healing"},
    "guilt": {"shame", "condemnation", "grace", "forgiveness", "mercy", "cleansing"},
    "comparison": {"envy", "jealousy", "identity", "approval", "worth", "status", "contentment"},
    "jealousy": {"envy", "comparison", "contentment", "covet", "approval", "worth"},
    "envy": {"jealousy", "comparison", "contentment", "covet", "approval"},
    "body": {"image", "appearance", "worth", "shame", "beauty", "identity", "embodied"},
    "illness": {"sickness", "pain", "weakness", "suffering", "healing", "body", "limitations"},
    "disability": {"weakness", "limitations", "body", "suffering", "healing", "dignity"},
    "pain": {"suffering", "grief", "weakness", "healing", "lament", "endurance"},
    "grief": {"loss", "mourning", "sorrow", "lament", "comfort", "hope"},
    "suffering": {"pain", "grief", "weakness", "trials", "endurance", "hope", "comfort"},
    "pray": {"prayer", "asking", "waiting", "listening", "lament", "persistence", "intercede"},
    "prayer": {"pray", "asking", "waiting", "listening", "lament", "persistence", "intercede"},
    "silent": {"waiting", "listening", "lament", "distance", "presence", "patience"},
    "waiting": {"silent", "patience", "hope", "trust", "endurance", "listen"},
    "faith": {"trust", "hope", "obedience", "belief", "confidence", "assurance", "endurance"},
    "trust": {"faith", "surrender", "control", "obedience", "hope", "assurance"},
    "marriage": {"spouse", "family", "conflict", "reconciliation", "intimacy", "covenant"},
    "relationship": {"conflict", "reconciliation", "friendship", "family", "trust", "hurt"},
}

_STEMMER = snowballstemmer.stemmer("english")


def _canon_env(v: str) -> str:
    v = (v or "").strip()
    if v in ("prod", "main", "full"):
        return "complete"
    return v


def active_env() -> str:
    v = _canon_env(os.environ.get("VOD_ENV") or "")
    if v:
        return v
    state_file = VODCASTS_ROOT / ".vodcasts-env"
    if state_file.exists():
        try:
            txt = state_file.read_text(encoding="utf-8", errors="replace").strip()
            if txt:
                return _canon_env(txt)
        except Exception:
            pass
    return "dev"


def default_cache_dir(env: str | None = None) -> Path:
    return VODCASTS_ROOT / "cache" / (env or active_env())


def default_transcripts_root() -> Path:
    return VODCASTS_ROOT / "site" / "assets" / "transcripts"


@lru_cache(maxsize=8)
def _load_sources_lookup(env: str) -> dict[str, dict[str, Any]]:
    from scripts.sources import load_sources_config

    env_name = _canon_env(str(env or "").strip()) or active_env()
    cfg_path = VODCASTS_ROOT / "feeds" / f"{env_name}.md"
    if not cfg_path.exists():
        return {}
    try:
        cfg = load_sources_config(cfg_path)
    except Exception:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for src in cfg.sources or []:
        out[str(src.id)] = {
            "title": str(src.title or src.id).strip() or str(src.id),
            "category": str(src.category or "").strip(),
            "tags": [str(t).strip() for t in (src.tags or ()) if str(t).strip()],
        }
    return out


def _content_label_from_source(*, category: str, tags: Iterable[str] | None = None, episode_title: str = "") -> str:
    cat = normalize_ws(str(category or "")).strip().lower()
    tag_set = {normalize_ws(str(t or "")).strip().lower() for t in (tags or []) if normalize_ws(str(t or "")).strip()}
    title = normalize_ws(str(episode_title or "")).strip().lower()

    if "homily" in cat or "homily" in tag_set:
        return "homily"
    if "sermon" in cat or "sermons" in tag_set:
        if "sunday" in tag_set and ("concert" in tag_set or "live-music" in tag_set or "worship" in tag_set):
            return "service"
        return "sermon"
    if "bible-study" in cat or "bible teaching" in cat or "through-the-bible" in tag_set or "expositional" in tag_set:
        return "Bible study"
    if "conference" in cat or "conferences" in tag_set:
        return "conference talk"
    if "news" in cat:
        return "news segment"
    if "devotional" in cat or "devotional" in tag_set:
        return "devotional"
    if "podcast" in title:
        return "podcast episode"
    if "church" in title and ("sunday" in tag_set or "worship" in tag_set):
        return "service"
    if "study" in title:
        return "study"
    return "message"


def _source_context_for_feed(feed_slug: str, *, episode_title: str = "") -> dict[str, Any]:
    info = _load_sources_lookup(active_env()).get(str(feed_slug or "").strip()) or {}
    source_title = normalize_ws(str(info.get("title") or feed_slug or "")).strip() or str(feed_slug or "")
    source_category = normalize_ws(str(info.get("category") or "")).strip()
    source_tags = [str(t) for t in (info.get("tags") or []) if str(t).strip()]
    content_label = _content_label_from_source(category=source_category, tags=source_tags, episode_title=episode_title)
    return {
        "source_title": source_title,
        "source_category": source_category,
        "source_tags": source_tags,
        "content_label": content_label,
    }


def _relpath_under_root(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(VODCASTS_ROOT.resolve())).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _parse_timecode(s: str) -> float:
    # WebVTT uses "." milliseconds; SRT uses ",". Accept both.
    s = (s or "").strip()
    if not s:
        return 0.0
    s = s.replace(",", ".")
    parts = s.split(":")
    if len(parts) == 2:
        h = 0
        m, sec = parts
    elif len(parts) == 3:
        h, m, sec = parts
    else:
        return 0.0
    try:
        h_i = int(h)
        m_i = int(m)
        sec_f = float(sec)
        return max(0.0, h_i * 3600 + m_i * 60 + sec_f)
    except Exception:
        return 0.0


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


def parse_transcript_file(path: Path) -> list[Cue]:
    ext = path.suffix.lower()
    if ext == ".vtt":
        v = webvtt.read(str(path))
        cues: list[Cue] = []
        for c in getattr(v, "captions", []) or []:
            start_s = _parse_timecode(str(getattr(c, "start", "") or ""))
            end_s = _parse_timecode(str(getattr(c, "end", "") or ""))
            if end_s <= 0 or end_s < start_s:
                continue
            txt = normalize_ws(strip_html(str(getattr(c, "text", "") or "")))
            if not txt:
                continue
            cues.append(Cue(start=float(start_s), end=float(end_s), text=txt))
        return cues
    if ext == ".srt":
        subs = pysrt.open(str(path), encoding="utf-8", error_handling=getattr(pysrt, "ERROR_LOG", 1))
        cues: list[Cue] = []
        for s in subs or []:
            start_s = float(getattr(getattr(s, "start", None), "ordinal", 0) or 0) / 1000.0
            end_s = float(getattr(getattr(s, "end", None), "ordinal", 0) or 0) / 1000.0
            if end_s <= 0 or end_s < start_s:
                continue
            txt = normalize_ws(strip_html(str(getattr(s, "text", "") or "")))
            if not txt:
                continue
            cues.append(Cue(start=start_s, end=end_s, text=txt))
        return cues
    return []


def _tokenize(text: str) -> list[str]:
    s = (text or "").lower()
    s = re.sub(r"['’]", "", s)
    # Keep letters/numbers; collapse everything else to spaces.
    s = re.sub(r"[^a-z0-9]+", " ", s)
    toks = [t for t in s.split() if t]
    return toks


@lru_cache(maxsize=131072)
def _norm_token(t: str) -> str:
    t = (t or "").strip().lower()
    if not t:
        return ""
    if t.isalpha() and len(t) >= 3:
        t = str(_STEMMER.stemWord(t) or t).strip().lower()
    return t


def _filter_tokens(tokens: Iterable[str]) -> list[str]:
    out: list[str] = []
    for t in tokens:
        t = _norm_token(t)
        if len(t) <= 1:
            continue
        if t in _STOPWORDS:
            continue
        out.append(t)
    return out


def _build_stopwords() -> set[str]:
    out: set[str] = set()

    def add_word(w: str) -> None:
        for tok in _tokenize(w):
            nt = _norm_token(tok)
            if nt:
                out.add(nt)

    for w in _STOPWORDS_RAW:
        add_word(w)

    for w in get_stop_words("en") or []:
        add_word(str(w))

    return out


def _normalize_theme_weights(raw: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for k, v in (raw or {}).items():
        nk = _norm_token(str(k))
        if not nk:
            continue
        out[nk] = max(float(out.get(nk, 0.0)), float(v))
    return out


def _normalize_synonyms(raw: dict[str, set[str]]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for k, vs in (raw or {}).items():
        nk = _norm_token(str(k))
        if not nk:
            continue
        s = out.setdefault(nk, set())
        for v in vs or set():
            nv = _norm_token(str(v))
            if nv and nv != nk:
                s.add(nv)
    return out


# Final, normalized vocabulary used by indexing + querying.
_STOPWORDS = _build_stopwords()
_THEME_WEIGHTS = _normalize_theme_weights(_THEME_WEIGHTS_RAW)
_SYNONYMS = _normalize_synonyms(_SYNONYMS_RAW)
_PROBLEM_SPACE = _normalize_synonyms(_PROBLEM_SPACE_RAW)


def index_text(text: str) -> str:
    # Remove stopwords to reduce index noise.
    toks = _filter_tokens(_tokenize(text))
    return " ".join(toks)


def theme_density(text: str) -> float:
    toks = _filter_tokens(_tokenize(text))
    if not toks:
        return 0.0
    score = 0.0
    for t in toks:
        score += float(_THEME_WEIGHTS.get(t, 0.0))
    # Normalize: average weight per token, squashed to [0,1).
    avg = score / max(1.0, float(len(toks)))
    return 1.0 - math.exp(-avg)


def _rank_query_term(term: str, *, seed_terms: set[str] | None = None) -> float:
    t = _norm_token(term)
    if not t:
        return -1.0
    score = min(12.0, float(len(t))) + (float(_THEME_WEIGHTS.get(t, 0.0)) * 1.5)
    if seed_terms and t in seed_terms:
        score += 6.0
    if t in _PROBLEM_SPACE:
        score += 1.2
    if t in _SYNONYMS:
        score += 0.8
    return score


def _collect_problem_space_terms(*texts: str, max_terms: int = 18) -> list[str]:
    seed_terms: list[str] = []
    seed_set: set[str] = set()
    for text in texts:
        raw = normalize_ws(strip_html(text or ""))
        for tok in _filter_tokens(_tokenize(raw)):
            if tok and tok not in seed_set:
                seed_set.add(tok)
                seed_terms.append(tok)
    if not seed_terms:
        return []

    scores: dict[str, float] = {}
    for idx, term in enumerate(seed_terms):
        scores[term] = max(
            scores.get(term, -1.0),
            _rank_query_term(term, seed_terms=seed_set) + max(0.0, 2.6 - (idx * 0.2)),
        )
        first_ring = sorted((_SYNONYMS.get(term, set()) | _PROBLEM_SPACE.get(term, set())))
        for rel in first_ring:
            if not rel or rel == term:
                continue
            rel_score = _rank_query_term(rel, seed_terms=seed_set) + (2.4 if rel in seed_set else 0.9)
            scores[rel] = max(scores.get(rel, -1.0), rel_score)
            if rel in seed_set:
                continue
            for second in sorted(_PROBLEM_SPACE.get(rel, set())):
                if not second or second == term:
                    continue
                second_score = _rank_query_term(second, seed_terms=seed_set) + (0.4 if second in seed_set else 0.0)
                scores[second] = max(scores.get(second, -1.0), second_score)

    ranked = sorted(scores.items(), key=lambda item: (item[1], len(item[0])), reverse=True)
    return [term for term, _score in ranked[: max(4, int(max_terms))]]


def _build_problem_space_queries(
    *,
    question: str,
    related_topics: Iterable[str] | None = None,
    max_queries: int = 4,
) -> list[str]:
    topic_list = [normalize_ws(strip_html(t or "")).strip() for t in (related_topics or []) if normalize_ws(strip_html(t or "")).strip()]
    seed_terms = _collect_problem_space_terms(question, max_terms=8)
    expanded_terms = _collect_problem_space_terms(question, *topic_list, max_terms=18)
    if not expanded_terms:
        return []

    out: list[str] = []
    seen: set[str] = set()

    def add_query(parts: Iterable[str]) -> None:
        toks: list[str] = []
        local_seen: set[str] = set()
        for part in parts:
            nt = _norm_token(part)
            if not nt or nt in local_seen:
                continue
            local_seen.add(nt)
            toks.append(nt)
        if len(toks) < 2:
            return
        q = " ".join(toks[:5]).strip()
        if not q or q in seen:
            return
        seen.add(q)
        out.append(q)

    add_query(seed_terms[:2] + [t for t in expanded_terms if t not in seed_terms][:3])

    topic_terms = _collect_problem_space_terms(*topic_list, max_terms=8)
    if topic_terms:
        add_query(topic_terms[:2] + [t for t in expanded_terms if t not in topic_terms][:3])

    anchor_terms = seed_terms[:2] + [t for t in topic_terms if t not in seed_terms][:2]
    for anchor in anchor_terms:
        neighbors = sorted(
            (_SYNONYMS.get(anchor, set()) | _PROBLEM_SPACE.get(anchor, set())),
            key=lambda t: _rank_query_term(t, seed_terms=set(seed_terms)),
            reverse=True,
        )
        add_query([anchor] + neighbors[:4])
        if len(out) >= max(1, int(max_queries)):
            break

    if not out:
        add_query(expanded_terms[:5])
    return out[: max(1, int(max_queries))]


def answeriness(text: str) -> float:
    """
    Heuristic “does this sound like advice / response / counsel?” score in [0,1].
    """
    t = (text or "").lower()
    toks_raw = _tokenize(t)
    if not toks_raw:
        return 0.0
    toks = _filter_tokens(toks_raw)
    you = toks_raw.count("you") + toks_raw.count("your") + toks_raw.count("yours")
    imperatives = sum(1 for w in toks if w in {"should", "need", "must", "try", "start", "stop", "remember", "consider", "let", "lets", "do"})
    counsel = sum(1 for w in toks if w in {"forgiv", "repent", "pray", "trust", "love", "peac", "hope", "mercy", "grace"})
    raw = (you * 0.08) + (imperatives * 0.15) + (counsel * 0.12)
    return float(1.0 - math.exp(-max(0.0, raw)))


_HUMAN_CHAPTER_KINDS = {
    "start",
    "welcome",
    "intro",
    "worship",
    "prayer",
    "scripture",
    "reading",
    "message",
    "teaching",
    "application",
    "topic",
    "illustration",
    "story",
    "testimony",
    "conversation",
    "interview",
    "q_and_a",
    "response",
    "invitation",
    "communion",
    "announcements",
    "giving",
    "ad",
    "transition",
    "benediction",
    "outro",
}

_BOUNDARY_REVIEW_KINDS = {
    "message",
    "teaching",
    "application",
    "topic",
    "scripture",
    "reading",
    "illustration",
    "story",
    "testimony",
    "conversation",
    "interview",
    "q_and_a",
    "response",
    "invitation",
    "communion",
    "worship",
    "prayer",
}

_HARD_LOCKED_KINDS = {"start", "welcome", "intro", "worship", "prayer", "scripture", "reading", "announcements", "giving", "ad", "transition", "benediction", "outro"}


def _is_open_content_kind(kind: str) -> bool:
    k = normalize_ws(str(kind or "")).strip().lower().replace("-", "_").replace(" ", "_")
    if not k or len(k) < 3 or len(k) > 32:
        return False
    if not re.match(r"^[a-z][a-z0-9_]*$", k):
        return False
    if k in {"start", "intro", "ad", "transition", "outro", "announcements", "content", "chapter", "section", "segment", "other", "misc", "general", "unknown"}:
        return False
    return True


def classify_segment(text: str, *, start_sec: float, end_sec: float, total_sec: float) -> tuple[str, float]:
    """
    Very lightweight classification for tagging intros/ads/breaks/prayer/outros.
    Returns (kind, confidence) where kind is one of:
      content|intro|outro|ad|announcements|prayer|transition
    """
    s = normalize_ws(strip_html(text or "")).lower()
    toks = _tokenize(s)
    if not toks:
        return "content", 0.0
    pos = 0.0 if total_sec <= 0 else max(0.0, min(1.0, start_sec / total_sec))
    dur = max(0.0, float(end_sec) - float(start_sec))
    # Raw “token hits” are useful, but phrase patterns are much stronger signals.

    def has_any(needles: set[str]) -> int:
        return sum(1 for t in toks if t in needles)

    def has_phrase(pat: str) -> bool:
        return bool(re.search(pat, s, flags=re.I))

    def count_phrases(pats: list[tuple[str, float]]) -> float:
        sc = 0.0
        for pat, w in pats:
            if has_phrase(pat):
                sc += float(w)
        return sc

    intro_hits = has_any({"welcome", "glad", "joining", "thanks", "morning", "evening"})
    outro_hits = has_any({"subscribe", "watching", "listening", "bye", "presentation"})
    ad_hits = has_any({"sponsor", "sponsored", "promo", "discount", "offer", "donate", "donation", "patreon", "paypal", "venmo", "cashapp"})
    ann_hits = has_any({"announcements", "register", "signup", "conference", "camp"})
    # Avoid treating "Father <Name>" (speaker credit) as a prayer.
    prayer_hits = has_any({"amen"})
    transition_hits = has_any({"break", "return", "returning", "music", "pause", "intermission", "tuned"})

    intro_phr = [
        (r"\bwelcome\b", 0.35),
        (r"\bglad\s+(you|ya)\b", 0.25),
        (r"\bthank(s)?\s+you\s+for\s+(joining|being)\b", 0.45),
        (r"\bpresents\b", 0.30),
        (r"\btaken\s+from\b", 0.35),
        (r"\bhere('?s| is)\s+(pastor|father|fr\\.?|reverend)\b", 0.55),
        (r"\btoday\s+(we('| a)re|we)\b", 0.25),
        (r"\bwe\s+(are|re)\s+in\s+(a|the)\s+series\b", 0.45),
        (r"\bturn\s+(with\s+me|to)\b", 0.35),
    ]
    outro_phr = [
        (r"\bthanks?\s+for\s+(watching|listening)\b", 0.55),
        (r"\bsee\s+you\s+(next|again)\b", 0.35),
        (r"\bnext\s+week\b", 0.25),
        (r"\bgod\s+bless\b", 0.45),
        (r"\bbefore\s+you\s+go\b", 0.45),
        (r"\bcome\s+forward\b", 0.35),
        (r"\blike\s+and\s+subscribe\b", 0.75),
        (r"\buntil\s+next\s+time\b", 0.55),
        (r"\bthat('?s)?\s+all\s+for\s+today\b", 0.65),
        (r"\bthis\s+has\s+been\s+(a\s+)?presentation\b", 1.05),
        (r"\bpresentation\s+of\b", 0.55),
    ]
    ad_phr = [
        (r"\bthis\s+(episode|video)\s+is\s+sponsored\b", 1.10),
        (r"\bsponsor(?:ed|ship)?\b", 0.55),
        (r"\bpromo\s+code\b", 0.85),
        (r"\bdiscount\b", 0.55),
        (r"\boffer\b", 0.45),
        (r"\bbrought\s+to\s+you\s+by\b", 0.85),
        (r"\bsupport\s+us\b", 0.45),
        (r"\bsupport\s+(this|the)\s+(show|podcast|ministry|church)\b", 0.75),
        (r"\bmake\s+a\s+donation\b", 0.85),
        (r"\bplease\s+donate\b", 0.85),
        (r"\btext\s+to\s+give\b", 0.90),
        (r"\bonline\s+giving\b", 0.80),
        (r"\bpatreon\b", 0.65),
        (r"\blink\s+in\s+the\s+description\b", 0.55),
        (r"\bvisit\s+\w+(\s+dot\s+|\.)com\b", 0.70),
    ]
    ann_phr = [
        (r"\bannouncements\b", 0.95),
        (r"\bregister\b", 0.55),
        (r"\bsign\s+up\b", 0.45),
        (r"\bjoin\s+us\b", 0.35),
        (r"\bcoming\s+up\b", 0.35),
        (r"\bservice\s+times?\b", 0.55),
        (r"\bsmall\s+groups?\b", 0.55),
        (r"\bthis\s+(sunday|week)\b", 0.35),
        (r"\bupcoming\b", 0.35),
        (r"\bevent\b", 0.30),
    ]
    prayer_phr = [
        (r"\blet('| )s\s+pray\b", 1.15),
        (r"\bjoin\s+me\s+in\s+prayer\b", 0.95),
        (r"\bbow\s+your\s+heads?\b", 1.10),
        (r"\bin\s+the\s+name\s+of\s+the\s+father\b", 1.15),
        (r"\bour\s+father\s+who\s+(art|is)\b", 1.15),
        (r"\bin\s+jesus('?s)?\s+name\b", 0.85),
        (r"\b(dear|heavenly)\s+(lord|father|god)\b", 0.90),
        (r"^(lord|father|god|jesus)\b[, ]+(we\s+)?(thank|ask|praise|pray|come|lift|confess|worship)\b", 1.00),
        (r"\b(lord|father|god|jesus)\b[, ]+\s*(we\s+)?(thank|ask|praise|pray|come|lift|confess|worship)\b", 0.85),
        (r"\bthank\s+you\s+(lord|jesus|father|god)\b", 0.75),
        (r"\bamen\b", 0.65),
    ]
    transition_phr = [
        (r"\bwe('?| a)ll\s+be\s+right\s+back\b", 1.30),
        (r"\bback\s+in\s+(a\s+)?moment\b", 1.10),
        (r"\bafter\s+the\s+break\b", 1.05),
        (r"\bwhen\s+we\s+return\b", 0.90),
        (r"\band\s+now\s+back\b", 1.05),
        (r"\bwe('?| a)re\s+back\b", 0.95),
        (r"\bdon't\s+go\s+anywhere\b", 1.05),
        (r"\\[\\s*music\\s*\\]", 1.15),
        (r"♪", 1.15),
        (r"\bquick\s+break\b", 1.10),
        (r"\bshort\s+break\b", 1.05),
        (r"\bwe\s+(just\s+)?need\s+to\s+pause\b", 0.95),
        (r"\bstay\s+tuned\b", 1.00),
        (r"\bcoming\s+up\b", 0.80),
    ]

    # Score each label with a weak position prior.
    intro = (intro_hits * 0.14) + count_phrases(intro_phr) + (0.45 if pos <= 0.10 else 0.0)
    outro = (outro_hits * 0.14) + count_phrases(outro_phr) + (0.45 if pos >= 0.88 else 0.0)
    ad = (ad_hits * 0.16) + count_phrases(ad_phr) + (0.10 if 0.05 <= pos <= 0.95 else 0.0)
    announcements = (ann_hits * 0.14) + count_phrases(ann_phr) + (0.12 if pos <= 0.28 else 0.0)
    prayer = (prayer_hits * 0.14) + count_phrases(prayer_phr) + (0.10 if pos >= 0.65 else 0.0)
    transition = (transition_hits * 0.10) + count_phrases(transition_phr) + (0.05 if 0.05 <= pos <= 0.95 else 0.0)

    # Duration priors: very short segments are harder to classify confidently.
    if dur < 18.0:
        intro *= 0.75
        outro *= 0.75
        ad *= 0.70
        announcements *= 0.75
        prayer *= 0.70
        transition *= 0.70

    scores = {
        "intro": intro,
        "outro": outro,
        "ad": ad,
        "announcements": announcements,
        "prayer": prayer,
        "transition": transition,
    }
    kind = max(scores.keys(), key=lambda k: scores[k])
    conf = float(1.0 - math.exp(-max(0.0, scores[kind])))
    # Conservative: only call it non-content when it’s pretty clear.
    thresh = 0.50
    if kind == "ad":
        thresh = 0.62
    if kind == "prayer":
        thresh = 0.58
    if kind == "transition":
        thresh = 0.56
    if conf < thresh:
        return "content", float(conf)
    return kind, float(conf)


def classify_segment_v2(text: str, *, start_sec: float, end_sec: float, total_sec: float) -> tuple[str, float]:
    """
    Human-facing structure classifier used for chapter generation.
    Returns one of:
      content|welcome|intro|worship|prayer|scripture|invitation|giving|announcements|ad|transition|benediction|outro
    """
    s = normalize_ws(strip_html(text or "")).lower()
    toks = _tokenize(s)
    if not toks:
        return "content", 0.0
    pos = 0.0 if total_sec <= 0 else max(0.0, min(1.0, start_sec / total_sec))
    dur = max(0.0, float(end_sec) - float(start_sec))

    def has_any(needles: set[str]) -> int:
        return sum(1 for t in toks if t in needles)

    def has_phrase(pat: str) -> bool:
        return bool(re.search(pat, s, flags=re.I))

    def count_phrases(pats: list[tuple[str, float]]) -> float:
        sc = 0.0
        for pat, w in pats:
            if has_phrase(pat):
                sc += float(w)
        return sc

    welcome_hits = has_any({"welcome", "glad", "joining", "thanks", "morning", "evening", "church", "online"})
    intro_hits = has_any({"welcome", "glad", "joining", "thanks", "morning", "evening"})
    worship_hits = has_any({"worship", "sing", "praise", "glory", "honor", "worthy", "hallelujah"})
    outro_hits = has_any({"subscribe", "watching", "listening", "bye", "presentation"})
    ad_hits = has_any({"sponsor", "sponsored", "promo", "discount", "offer", "donate", "donation", "patreon", "paypal", "venmo", "cashapp"})
    ann_hits = has_any({"announcements", "register", "signup", "conference", "camp"})
    giving_hits = has_any({"give", "giving", "offering", "tithe", "generosity", "donate", "donation"})
    prayer_hits = has_any({"amen"})
    transition_hits = has_any({"break", "return", "returning", "music", "pause", "intermission", "tuned"})
    scripture_hits = has_any({"scripture", "verse", "chapter", "bible", "gospel", "psalm"})
    invitation_hits = has_any({"respond", "receive", "surrender", "salvation", "repent", "confess"})
    benediction_hits = has_any({"peace", "bless", "grace"})

    welcome_phr = [
        (r"\bhey\s+everybody[, ]+\s+welcome\s+to\s+church\b", 1.05),
        (r"\bwelcome\s+to\s+church\b", 0.95),
        (r"\bglad\s+(you|ya)(?:'re|\s+are)?\s+(here|joining)\b", 0.60),
        (r"\bgreat\s+to\s+see\s+you\s+today\b", 0.65),
        (r"\bjoining\s+us\s+from\b", 0.55),
    ]
    intro_phr = [
        (r"\bwelcome\b", 0.35),
        (r"\bthank(s)?\s+you\s+for\s+(joining|being)\b", 0.45),
        (r"\bpresents\b", 0.30),
        (r"\btaken\s+from\b", 0.35),
        (r"\bhere('?s| is)\s+(pastor|father|fr\\.?|reverend)\b", 0.55),
        (r"\btoday\s+(we('| a)re|we)\b", 0.25),
        (r"\bwe\s+(are|re)\s+in\s+(a|the)\s+series\b", 0.45),
    ]
    worship_phr = [
        (r"\blet('?| u)s\s+do\s+some\s+singing\b", 1.15),
        (r"\blet('?| u)s\s+sing\b", 1.05),
        (r"\bas\s+we\s+sing\b", 0.85),
        (r"\blift\s+up\s+the\s+name\s+of\s+jesus\b", 1.00),
        (r"\bworthy\s+of\s+our\s+(praise|worship)\b", 1.05),
        (r"\bwe\s+give\s+you\s+all\s+the\s+(honor|glory)\b", 1.00),
        (r"\bworship\s+together\b", 0.80),
        (r"\bstand\s+to\s+your\s+feet\b", 0.80),
    ]
    outro_phr = [
        (r"\bthanks?\s+for\s+(watching|listening)\b", 0.55),
        (r"\bsee\s+you\s+(next|again)\b", 0.35),
        (r"\bnext\s+week\b", 0.25),
        (r"\bgod\s+bless\b", 0.45),
        (r"\bbefore\s+you\s+go\b", 0.45),
        (r"\blike\s+and\s+subscribe\b", 0.75),
        (r"\buntil\s+next\s+time\b", 0.55),
        (r"\bthat('?s)?\s+all\s+for\s+today\b", 0.65),
        (r"\bthis\s+has\s+been\s+(a\s+)?presentation\b", 1.05),
    ]
    ad_phr = [
        (r"\bthis\s+(episode|video)\s+is\s+sponsored\b", 1.10),
        (r"\bsponsor(?:ed|ship)?\b", 0.55),
        (r"\bpromo\s+code\b", 0.85),
        (r"\bbrought\s+to\s+you\s+by\b", 0.85),
        (r"\bsupport\s+(this|the)\s+(show|podcast|ministry|church)\b", 0.75),
        (r"\bmake\s+a\s+donation\b", 0.85),
        (r"\bplease\s+donate\b", 0.85),
        (r"\bpatreon\b", 0.65),
        (r"\blink\s+in\s+the\s+description\b", 0.55),
        (r"\bvisit\s+\w+(\s+dot\s+|\.)com\b", 0.70),
    ]
    ann_phr = [
        (r"\bannouncements\b", 0.95),
        (r"\bregister\b", 0.55),
        (r"\bsign\s+up\b", 0.45),
        (r"\bservice\s+times?\b", 0.55),
        (r"\bsmall\s+groups?\b", 0.55),
        (r"\bupcoming\b", 0.35),
        (r"\bevent\b", 0.30),
    ]
    giving_phr = [
        (r"\b(tithes?|offerings?)\b", 1.05),
        (r"\bgenerosity\b", 0.75),
        (r"\btext\s+to\s+give\b", 1.15),
        (r"\bonline\s+giving\b", 1.05),
        (r"\bour\s+(tithes?|offerings?)\b", 1.10),
        (r"\bwe\s+invite\s+you\s+to\s+give\b", 1.00),
        (r"\bpartner\s+with\s+us\b", 0.70),
    ]
    invitation_phr = [
        (r"\bif\s+you('?ve|\s+have)\s+never\b", 0.95),
        (r"\blead\s+you\s+in\s+a\s+(very\s+)?simple\s+prayer\b", 1.45),
        (r"\bpray\s+this\s+prayer\b", 0.95),
        (r"\breceive\s+(jesus|christ)\b", 1.05),
        (r"\bgive\s+your\s+life\s+to\s+(jesus|christ)\b", 1.15),
        (r"\bput\s+your\s+faith\s+in\s+jesus\b", 1.00),
        (r"\braise\s+your\s+hand\b", 0.90),
        (r"\bcome\s+forward\b", 0.90),
        (r"\bconfess\s+with\s+your\s+mouth\b", 0.80),
        (r"\bi\s+invite\s+you\s+inside\b", 1.10),
        (r"\bforgive\s+my\s+sin\b", 1.10),
        (r"\btoday\s+i\s+repent\b", 1.15),
        (r"\bwelcome\s+to\s+the\s+family\s+of\s+god\b", 1.20),
        (r"\bmost\s+important\s+decision\s+of\s+your\s+life\b", 1.15),
        (r"\bif\s+you('?ve|\s+have)\s+decided\s+to\s+follow\s+jesus\b", 1.20),
    ]
    prayer_phr = [
        (r"\blet('| )s\s+pray\b", 1.15),
        (r"\bjoin\s+me\s+in\s+prayer\b", 0.95),
        (r"\bbow\s+your\s+heads?\b", 1.10),
        (r"\bin\s+the\s+name\s+of\s+the\s+father\b", 1.15),
        (r"\bour\s+father\s+who\s+(art|is)\b", 1.15),
        (r"\bin\s+jesus('?s)?\s+name\b", 0.85),
        (r"\b(dear|heavenly)\s+(lord|father|god)\b", 0.90),
        (r"^(lord|father|god|jesus)\b[, ]+(we\s+)?(thank|ask|praise|pray|come|lift|confess|worship)\b", 1.00),
        (r"\b(lord|father|god|jesus)\b[, ]+\s*(we\s+)?(thank|ask|praise|pray|come|lift|confess|worship)\b", 0.85),
        (r"\bthank\s+you\s+(lord|jesus|father|god)\b", 0.75),
        (r"\bamen\b", 0.65),
    ]
    scripture_phr = [
        (r"\bopen\s+(your|the)\s+bibles?\b", 1.00),
        (r"\bturn\s+(with\s+me|in\s+your\s+bibles?|to)\b", 0.80),
        (r"\breading\s+from\b", 1.00),
        (r"\bour\s+scripture\s+reading\b", 1.05),
        (r"\bthe\s+word\s+of\s+the\s+lord\b", 1.10),
        (r"\bour\s+text\s+today\b", 0.75),
        (r"\bchapter\s+\d+\b", 0.55),
    ]
    transition_phr = [
        (r"\bwe('?| a)ll\s+be\s+right\s+back\b", 1.30),
        (r"\bback\s+in\s+(a\s+)?moment\b", 1.10),
        (r"\bafter\s+the\s+break\b", 1.05),
        (r"\bwhen\s+we\s+return\b", 0.90),
        (r"\band\s+now\s+back\b", 1.05),
        (r"\bwe('?| a)re\s+back\b", 0.95),
        (r"\bdon't\s+go\s+anywhere\b", 1.05),
        (r"\\[\\s*music\\s*\\]", 1.15),
        (r"â™ª", 1.15),
        (r"\bquick\s+break\b", 1.10),
        (r"\bshort\s+break\b", 1.05),
        (r"\bwe\s+(just\s+)?need\s+to\s+pause\b", 0.95),
        (r"\bstay\s+tuned\b", 1.00),
    ]
    benediction_phr = [
        (r"\bgo\s+in\s+peace\b", 1.25),
        (r"\bthe\s+lord\s+bless\s+you\s+and\s+keep\s+you\b", 1.25),
        (r"\bmay\s+the\s+lord\b", 0.95),
        (r"\bgrace\s+of\s+the\s+lord\b", 1.05),
        (r"\bhave\s+a\s+great\s+week\b", 0.60),
        (r"\byou\s+are\s+invited\s+back\b", 0.55),
    ]

    welcome = (welcome_hits * 0.16) + count_phrases(welcome_phr) + (0.55 if pos <= 0.06 else 0.0)
    intro = (intro_hits * 0.14) + count_phrases(intro_phr) + (0.45 if pos <= 0.10 else 0.0)
    worship = (worship_hits * 0.18) + count_phrases(worship_phr) + (0.20 if pos <= 0.35 else 0.0)
    outro = (outro_hits * 0.14) + count_phrases(outro_phr) + (0.45 if pos >= 0.88 else 0.0)
    ad = (ad_hits * 0.16) + count_phrases(ad_phr) + (0.10 if 0.05 <= pos <= 0.95 else 0.0)
    announcements = (ann_hits * 0.14) + count_phrases(ann_phr) + (0.12 if pos <= 0.28 else 0.0)
    giving = (giving_hits * 0.16) + count_phrases(giving_phr) + (0.10 if pos <= 0.25 or pos >= 0.82 else 0.0)
    invitation = (invitation_hits * 0.18) + count_phrases(invitation_phr) + (0.26 if pos >= 0.55 else 0.0)
    prayer = (prayer_hits * 0.14) + count_phrases(prayer_phr) + (0.10 if pos >= 0.65 else 0.0)
    scripture = (scripture_hits * 0.12) + count_phrases(scripture_phr) + (0.75 if _extract_bible_ref(s) else 0.0)
    transition = (transition_hits * 0.10) + count_phrases(transition_phr) + (0.05 if 0.05 <= pos <= 0.95 else 0.0)
    benediction = (benediction_hits * 0.14) + count_phrases(benediction_phr) + (0.35 if pos >= 0.82 else 0.0)

    if dur < 18.0:
        welcome *= 0.78
        intro *= 0.75
        worship *= 0.75
        outro *= 0.75
        ad *= 0.70
        announcements *= 0.75
        giving *= 0.75
        invitation *= 0.78
        prayer *= 0.70
        scripture *= 0.80
        transition *= 0.70
        benediction *= 0.80

    scores = {
        "welcome": welcome,
        "intro": intro,
        "worship": worship,
        "outro": outro,
        "ad": ad,
        "announcements": announcements,
        "giving": giving,
        "invitation": invitation,
        "prayer": prayer,
        "scripture": scripture,
        "transition": transition,
        "benediction": benediction,
    }
    kind = max(scores.keys(), key=lambda k: scores[k])
    conf = float(1.0 - math.exp(-max(0.0, scores[kind])))
    thresh = 0.50
    if kind in {"welcome", "worship", "scripture", "giving", "benediction"}:
        thresh = 0.60
    if kind == "invitation":
        thresh = 0.55
    if kind == "ad":
        thresh = 0.62
    if kind == "prayer":
        thresh = 0.58
    if kind == "transition":
        thresh = 0.56
    if conf < thresh:
        return "content", float(conf)
    return kind, float(conf)


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str
    kind: str
    kind_conf: float
    theme: float
    answer: float


_SEGMENT_SENTENCE_END_RE = re.compile(r"[.!?]\s*$")
_SEGMENT_HARD_BOUNDARY_RE = re.compile(
    r"\b("
    r"let('| )s\s+pray|let\s+us\s+pray|join\s+me\s+in\s+prayer|bow\s+your\s+heads?|"
    r"let('| )s\s+sing|stand\s+to\s+your\s+feet|worship\s+together|"
    r"in\s+the\s+name\s+of\s+the\s+father|our\s+father\s+who\s+(art|is)|"
    r"open\s+(your|the)\s+bibles?|reading\s+from|the\s+word\s+of\s+the\s+lord|"
    r"tithes?|offerings?|text\s+to\s+give|online\s+giving|"
    r"this\s+(episode|video)\s+is\s+sponsored|promo\s+code|brought\s+to\s+you\s+by|"
    r"announcements?|we('?| a)ll\s+be\s+right\s+back|after\s+the\s+break|when\s+we\s+return|"
    r"go\s+in\s+peace|the\s+lord\s+bless\s+you\s+and\s+keep\s+you|"
    r"here('?s| is)\s+(pastor|father|fr\\.?|reverend)"
    r")\b",
    flags=re.I,
)


def cues_to_search_segments(
    cues: list[Cue],
    *,
    target_words: int = 140,
    overlap_words: int = 45,
    max_words: int = 220,
    max_duration_sec: float = 120.0,
) -> list[Segment]:
    """
    Cheap search-oriented chunking.

    For answer retrieval we only need reasonably-sized, overlapping windows that
    preserve timestamps and enough local context for FTS and follow-up review.
    """
    if not cues:
        return []

    cue_word_counts = [max(1, len(_tokenize(c.text))) for c in cues]
    out: list[Segment] = []
    total_n = len(cues)
    start_idx = 0

    while start_idx < total_n:
        words = 0
        end_idx = start_idx
        window_start = float(cues[start_idx].start)

        while end_idx < total_n:
            words += cue_word_counts[end_idx]
            window_end = float(cues[end_idx].end)
            end_idx += 1

            if words >= int(max_words):
                break
            if window_end - window_start >= float(max_duration_sec):
                break
            if words >= int(target_words) and _SEGMENT_SENTENCE_END_RE.search(cues[end_idx - 1].text or ""):
                break

        window = cues[start_idx:end_idx]
        txt = normalize_ws(" ".join(c.text for c in window))
        if txt:
            out.append(
                Segment(
                    start=float(window[0].start),
                    end=float(window[-1].end),
                    text=txt,
                    kind="content",
                    kind_conf=1.0,
                    theme=0.0,
                    answer=0.0,
                )
            )

        if end_idx >= total_n:
            break

        next_start = end_idx
        overlap = 0
        while next_start > start_idx + 1 and overlap < int(overlap_words):
            next_start -= 1
            overlap += cue_word_counts[next_start]
        start_idx = max(start_idx + 1, next_start)

    return out


def cues_to_segments(
    cues: list[Cue],
    *,
    target_words: int = 140,
    max_words: int = 220,
    max_duration_sec: float = 130.0,
    max_gap_sec: float = 4.0,
) -> list[Segment]:
    if not cues:
        return []
    total_sec = float(max(c.end for c in cues))
    out: list[Segment] = []

    buf_text: list[str] = []
    buf_word_count = 0
    start = cues[0].start
    end = cues[0].end

    def flush():
        nonlocal buf_text, buf_word_count, start, end
        txt = normalize_ws(" ".join(buf_text))
        if txt:
            kind, conf = classify_segment_v2(txt, start_sec=start, end_sec=end, total_sec=total_sec)
            out.append(
                Segment(
                    start=float(start),
                    end=float(end),
                    text=txt,
                    kind=kind,
                    kind_conf=float(conf),
                    theme=float(theme_density(txt)),
                    answer=float(answeriness(txt)),
                )
            )
        buf_text = []
        buf_word_count = 0

    def word_count() -> int:
        return buf_word_count

    prev_end = cues[0].end
    for c in cues:
        gap = float(c.start - prev_end)
        prev_end = c.end

        # Hard boundaries help keep structured sections from being mixed
        # into the first "big segment", which makes both classification and titles worse.
        if buf_text:
            boundary = bool(_SEGMENT_HARD_BOUNDARY_RE.search(c.text or ""))
            if boundary:
                wc = word_count()
                dur = float(c.start - start)
                if wc >= 18 or dur >= 18.0:
                    flush()
                    start = c.start
                    end = c.end

        if buf_text:
            dur = float(c.end - start)
            wc = word_count()
            ends_sentence = bool(_SEGMENT_SENTENCE_END_RE.search(buf_text[-1] if buf_text else ""))
            if gap >= max_gap_sec and wc >= max(40, int(target_words * 0.45)):
                flush()
                start = c.start
                end = c.end
            elif dur >= max_duration_sec and wc >= max(55, int(target_words * 0.50)):
                flush()
                start = c.start
                end = c.end
            elif wc >= max_words and ends_sentence:
                flush()
                start = c.start
                end = c.end

        if not buf_text:
            start = c.start
        end = c.end
        buf_text.append(c.text)
        buf_word_count += len(_filter_tokens(_tokenize(c.text)))

        # Friendly boundary: if we’ve reached target words and the current cue ends a sentence.
        if word_count() >= target_words and _SEGMENT_SENTENCE_END_RE.search(c.text):
            flush()
            start = c.end
            end = c.end

    if buf_text:
        flush()
    return out


def _iter_transcript_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() in _PLAYABLE_TRANSCRIPT_EXTS:
            yield p


def _load_episode_meta_for_feed(cache_dir: Path, feed_slug: str) -> dict[str, dict[str, Any]]:
    from scripts.feed_manifest import parse_feed_for_manifest

    feed_path = cache_dir / "feeds" / f"{feed_slug}.xml"
    if not feed_path.exists():
        return {}
    try:
        xml_text = feed_path.read_text(encoding="utf-8", errors="replace")
        _features, _channel_title, episodes, _image = parse_feed_for_manifest(xml_text, source_id=feed_slug, source_title=feed_slug)
        out: dict[str, dict[str, Any]] = {}
        for ep in episodes or []:
            if not isinstance(ep, dict):
                continue
            slug = str(ep.get("slug") or "").strip()
            if not slug:
                continue
            out[slug] = ep
        return out
    except Exception:
        return {}


def _ensure_schema(con: sqlite3.Connection) -> None:
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA temp_store=MEMORY;")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS files (
          path TEXT PRIMARY KEY,
          feed TEXT NOT NULL,
          episode_slug TEXT NOT NULL,
          mtime_ns INTEGER NOT NULL,
          size INTEGER NOT NULL,
          cues INTEGER NOT NULL,
          segments INTEGER NOT NULL,
          updated_at_unix INTEGER NOT NULL
        );
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS segments (
          id INTEGER PRIMARY KEY,
          file_path TEXT NOT NULL,
          feed TEXT NOT NULL,
          episode_slug TEXT NOT NULL,
          episode_title TEXT NOT NULL,
          episode_date TEXT NOT NULL,
          start_sec REAL NOT NULL,
          end_sec REAL NOT NULL,
          kind TEXT NOT NULL,
          kind_conf REAL NOT NULL,
          theme REAL NOT NULL,
          answer REAL NOT NULL,
          text TEXT NOT NULL,
          text_index TEXT NOT NULL
        );
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_segments_feed_ep ON segments(feed, episode_slug);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_segments_file ON segments(file_path);")
    # Prefer a non-contentless FTS table so we can DELETE by rowid during incremental rebuilds.
    try:
        row = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='segments_fts'").fetchone()
        sql = str(row[0] or "") if row else ""
        if "content=''" in sql.replace(" ", ""):
            con.execute("DROP TABLE IF EXISTS segments_fts;")
    except Exception:
        pass
    con.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts
        USING fts5(text_index, episode_title, feed, episode_slug);
        """
    )


def _meta_set(con: sqlite3.Connection, key: str, value: Any) -> None:
    con.execute("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))


def _meta_get(con: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row[0])
    except Exception:
        return default


def _file_signature(path: Path) -> tuple[int, int]:
    st = path.stat()
    sig_m = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))
    sig_s = int(st.st_size)
    return sig_m, sig_s


def _file_row_is_current(path: Path, row: sqlite3.Row | None) -> bool:
    if row is None or not path.exists():
        return False
    sig_m, sig_s = _file_signature(path)
    return int(row["mtime_ns"]) == sig_m and int(row["size"]) == sig_s


def _format_elapsed_brief(seconds: float) -> str:
    total = max(0, int(seconds))
    mins, sec = divmod(total, 60)
    hrs, mins = divmod(mins, 60)
    if hrs > 0:
        return f"{hrs:d}:{mins:02d}:{sec:02d}"
    return f"{mins:02d}:{sec:02d}"


def _segment_from_row(row: sqlite3.Row) -> Segment:
    return Segment(
        start=float(row["start_sec"] or 0.0),
        end=float(row["end_sec"] or 0.0),
        text=str(row["text"] or ""),
        kind=str(row["kind"] or "content"),
        kind_conf=float(row["kind_conf"] or 0.0),
        theme=float(row["theme"] or 0.0),
        answer=float(row["answer"] or 0.0),
    )


def _load_segments_for_file(con: sqlite3.Connection, file_path: str) -> list[Segment]:
    rows = con.execute(
        """
        SELECT start_sec, end_sec, kind, kind_conf, theme, answer, text
        FROM segments
        WHERE file_path=?
        ORDER BY start_sec ASC
        """,
        (file_path,),
    ).fetchall()
    return [_segment_from_row(r) for r in rows]


def analyze_transcripts(
    *,
    db_path: Path,
    transcripts_root: Path,
    cache_dir: Path,
    incremental: bool = True,
    force: bool = False,
    limit_files: int = 0,
    transcript_paths: list[Path] | None = None,
    quiet: bool = False,
) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    _ensure_schema(con)

    started = time.time()
    now = int(started)
    tokenizer_version = 7
    tok_info = {
        "version": int(tokenizer_version),
        "stemmer": "snowball",
        "stopwords": "stop-words",
        "segment_classifier": "search-windows-v1",
    }
    prev_info = _meta_get(con, "tokenizer_info", None)
    if prev_info != tok_info:
        force = True
        incremental = False

    _meta_set(con, "version", 1)
    _meta_set(con, "analysis_built_at_unix", now)
    _meta_set(con, "tokenizer_version", tokenizer_version)
    _meta_set(con, "tokenizer_info", tok_info)
    _meta_set(con, "env", str(cache_dir.name))
    _meta_set(con, "transcripts_root", _relpath_under_root(transcripts_root))

    files = list(transcript_paths or _iter_transcript_files(transcripts_root))
    files = [Path(p).resolve() for p in files]
    files.sort()
    if transcript_paths:
        force = True
    if limit_files and limit_files > 0:
        files = files[: int(limit_files)]

    by_feed_meta: dict[str, dict[str, dict[str, Any]]] = {}

    def log(msg: str) -> None:
        if not quiet:
            print(msg, flush=True)

    log(f"[answer-engine] analyzing transcripts: {transcripts_root} (files={len(files)})")
    log(f"[answer-engine] db: {db_path}")
    log(f"[answer-engine] mode: incremental={bool(incremental)} force={bool(force)}")

    touched = 0
    skipped = 0
    written_segments = 0
    total_n = len(files)
    fts_cleared = False
    last_progress = started
    try:
        for idx, p in enumerate(files, 1):
            rel = _relpath_under_root(p)
            feed = p.parent.name
            episode_slug = p.stem
            sig_m, sig_s = _file_signature(p)

            row = None
            if incremental and not force:
                row = con.execute("SELECT mtime_ns, size FROM files WHERE path=?", (rel,)).fetchone()
            if incremental and not force and _file_row_is_current(p, row):
                skipped += 1
                log(f"[answer-engine] [{idx}/{total_n}] skip  {rel}")
                continue

            if not fts_cleared:
                with con:
                    con.execute("DELETE FROM segments_fts")
                fts_cleared = True

            if feed not in by_feed_meta:
                by_feed_meta[feed] = _load_episode_meta_for_feed(cache_dir, feed)
            ep_meta = by_feed_meta.get(feed, {}).get(episode_slug) or {}
            ep_title = normalize_ws(str(ep_meta.get("title") or episode_slug))
            ep_date = normalize_ws(str(ep_meta.get("dateText") or ep_meta.get("date") or ""))

            cues = parse_transcript_file(p)
            segs = cues_to_search_segments(cues)
            seg_rows = [
                (
                    rel,
                    feed,
                    episode_slug,
                    ep_title,
                    ep_date,
                    float(s.start),
                    float(s.end),
                    str(s.kind),
                    float(s.kind_conf),
                    float(s.theme),
                    float(s.answer),
                    s.text,
                    index_text(s.text),
                )
                for s in segs
            ]
            with con:
                con.execute("DELETE FROM segments WHERE file_path=?", (rel,))
                con.executemany(
                    """
                    INSERT INTO segments(
                      file_path, feed, episode_slug, episode_title, episode_date,
                      start_sec, end_sec, kind, kind_conf, theme, answer, text, text_index
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    seg_rows,
                )

                con.execute(
                    """
                    INSERT INTO files(path, feed, episode_slug, mtime_ns, size, cues, segments, updated_at_unix)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(path) DO UPDATE SET
                      feed=excluded.feed,
                      episode_slug=excluded.episode_slug,
                      mtime_ns=excluded.mtime_ns,
                      size=excluded.size,
                      cues=excluded.cues,
                      segments=excluded.segments,
                      updated_at_unix=excluded.updated_at_unix
                    """,
                    (rel, feed, episode_slug, sig_m, sig_s, int(len(cues)), int(len(segs)), now),
                )

            touched += 1
            written_segments += len(segs)
            log(f"[answer-engine] [{idx}/{total_n}] update {rel} cues={len(cues)} segs={len(segs)}")
            if not quiet:
                elapsed = max(0.001, time.time() - started)
                processed = touched + skipped
                if processed == total_n or (processed % 25 == 0) or ((time.time() - last_progress) >= 5.0):
                    rate = processed / elapsed
                    remaining = max(0, total_n - processed)
                    eta = (remaining / rate) if rate > 0 else 0.0
                    pct = (processed / total_n * 100.0) if total_n > 0 else 100.0
                    log(
                        "[answer-engine] progress: "
                        f"{processed}/{total_n} files ({pct:.1f}%) "
                        f"updated={touched} skipped={skipped} segs={written_segments} "
                        f"rate={rate:.2f} files/s eta={_format_elapsed_brief(eta)}"
                    )
                    last_progress = time.time()

        if touched > 0:
            _meta_set(con, "fts_dirty", True)
            _meta_set(con, "segments_built_at_unix", int(time.time()))

        elapsed = max(0.001, time.time() - started)
        log(f"[answer-engine] done: updated={touched} skipped={skipped} elapsed={elapsed:.1f}s")
    except KeyboardInterrupt:
        elapsed = max(0.001, time.time() - started)
        log(f"\n[answer-engine] interrupted: updated={touched} skipped={skipped} elapsed={elapsed:.1f}s")
        raise
    finally:
        try:
            con.close()
        except Exception:
            pass


def rebuild_search_index(*, db_path: Path, quiet: bool = False) -> None:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    _ensure_schema(con)

    def log(msg: str) -> None:
        if not quiet:
            print(msg, flush=True)

    try:
        total_segments = int(con.execute("SELECT COUNT(*) FROM segments").fetchone()[0] or 0)
        if total_segments <= 0:
            raise RuntimeError("no analyzed segments found; run `ae.sh analyze` first")

        started = time.time()
        with con:
            con.execute("DELETE FROM segments_fts")
            con.execute(
                """
                INSERT INTO segments_fts(rowid, text_index, episode_title, feed, episode_slug)
                SELECT id, text_index, episode_title, feed, episode_slug
                FROM segments
                ORDER BY id ASC
                """
            )
        _meta_set(con, "fts_dirty", False)
        _meta_set(con, "fts_built_at_unix", int(time.time()))
        elapsed = max(0.001, time.time() - started)
        log(f"[answer-engine] indexed {total_segments} segments into FTS in {elapsed:.1f}s")
    finally:
        try:
            con.close()
        except Exception:
            pass


def write_chapters_from_analysis(
    *,
    db_path: Path,
    transcripts_root: Path,
    chapters_out: Path | None = None,
    chapters_adjacent: bool = False,
    mode: str = "semantic",
    force: bool = False,
    limit_files: int = 0,
    transcript_rel: str = "",
    quiet: bool = False,
) -> None:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    _ensure_schema(con)

    def log(msg: str) -> None:
        if not quiet:
            print(msg, flush=True)

    q = "SELECT path, feed, episode_slug, mtime_ns, size FROM files"
    params: list[Any] = []
    if transcript_rel:
        q += " WHERE path=?"
        params.append(str(transcript_rel))
    q += " ORDER BY path ASC"
    rows = con.execute(q, params).fetchall()
    if limit_files and limit_files > 0:
        rows = rows[: int(limit_files)]
    if transcript_rel and not rows:
        raise RuntimeError(f"no analyzed segments found for {transcript_rel}; run `ae.sh analyze` first")

    log(f"[answer-engine] writing chapters from analyzed segments (files={len(rows)})")
    wrote = 0
    skipped = 0
    stale = 0
    try:
        for idx, row in enumerate(rows, 1):
            rel = str(row["path"])
            p = (VODCASTS_ROOT / rel).resolve()
            if not _file_row_is_current(p, row):
                stale += 1
                log(f"[warn] [{idx}/{len(rows)}] stale analysis {rel}; run `ae.sh analyze`")
                continue

            target = _chapters_output_path(transcript_path=p, out_dir=chapters_out, adjacent=chapters_adjacent)
            if target and not force and target.exists() and not _chapters_needs_update(target, mode=str(mode or "semantic")):
                skipped += 1
                log(f"[answer-engine] [{idx}/{len(rows)}] skip  {rel}")
                continue

            segs = _load_segments_for_file(con, rel)
            if not segs:
                skipped += 1
                log(f"[warn] [{idx}/{len(rows)}] no segments {rel}")
                continue

            chapters = chapters_from_segments(
                feed=str(row["feed"]),
                episode_slug=str(row["episode_slug"]),
                segments=segs,
                mode=str(mode or "semantic"),
            )
            _write_chapters_for_transcript(
                transcript_path=p,
                chapters=chapters,
                out_dir=chapters_out,
                adjacent=chapters_adjacent,
            )
            wrote += 1
            log(f"[answer-engine] [{idx}/{len(rows)}] write {rel} chapters={len(chapters.get('chapters') or [])}")
    finally:
        try:
            con.close()
        except Exception:
            pass

    if not quiet:
        print(f"[answer-engine] done: wrote={wrote} skipped={skipped} stale={stale}", flush=True)


def _build_fts_query(q: str, *, max_terms: int = 14) -> tuple[str, list[str]]:
    raw = normalize_ws(strip_html(q or ""))
    toks = _filter_tokens(_tokenize(raw))
    if not toks:
        return "", []

    # Prefer longer + themed words.
    def weight(t: str) -> float:
        return min(12.0, float(len(t))) + float(_THEME_WEIGHTS.get(t, 0.0)) * 1.4

    uniq: list[str] = []
    seen: set[str] = set()
    for t in toks:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    uniq.sort(key=weight, reverse=True)
    picked = uniq[: max(3, min(max_terms, len(uniq)))]

    # Expand a few common synonyms (still AND across “concepts”, OR within a concept).
    groups: list[str] = []
    expanded_terms: list[str] = []
    for t in picked:
        syns = sorted(_SYNONYMS.get(t, set()))
        terms = [t] + [s for s in syns if s not in picked]
        # Quote terms with special characters (shouldn’t happen with our tokenizer, but keep safe).
        terms_q = [re.sub(r"[^a-z0-9_]", "", x) for x in terms if x]
        terms_q = [x for x in terms_q if x]
        if not terms_q:
            continue
        expanded_terms += terms_q
        if len(terms_q) == 1:
            groups.append(terms_q[0])
        else:
            groups.append("(" + " OR ".join(terms_q) + ")")

    if not groups:
        return "", []
    if len(groups) <= 3:
        return " AND ".join(groups), expanded_terms
    # Avoid over-constraining long questions: require the top concepts, then OR the rest.
    must = groups[:2]
    optional = groups[2:]
    return " AND ".join(must + ["(" + " OR ".join(optional) + ")"]), expanded_terms


def _build_fts_query_variants(q: str, *, max_terms: int = 14) -> tuple[list[str], list[str]]:
    primary, expanded_terms = _build_fts_query(q, max_terms=max_terms)
    raw = normalize_ws(strip_html(q or ""))
    toks = _filter_tokens(_tokenize(raw))
    uniq: list[str] = []
    seen: set[str] = set()
    for t in toks:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    terms = uniq[: max(3, min(max_terms, len(uniq)))]

    variants: list[str] = []
    if primary:
        variants.append(primary)

    if len(terms) >= 3:
        variants.append(" AND ".join(terms[:3]))
    if len(terms) >= 2:
        variants.append(" AND ".join(terms[:2]))
    if terms:
        variants.append(" OR ".join(terms[: min(5, len(terms))]))
    if expanded_terms:
        exp_uniq: list[str] = []
        exp_seen: set[str] = set()
        for t in expanded_terms:
            if t and t not in exp_seen:
                exp_seen.add(t)
                exp_uniq.append(t)
        if len(exp_uniq) >= 2:
            variants.append(" OR ".join(exp_uniq[: min(8, len(exp_uniq))]))

    out: list[str] = []
    seen_q: set[str] = set()
    for v in variants:
        vv = normalize_ws(v).strip()
        if not vv or vv in seen_q:
            continue
        seen_q.add(vv)
        out.append(vv)
    return out, expanded_terms


def _snippet(text: str, *, max_chars: int = 240) -> str:
    s = normalize_ws(text or "")
    if len(s) <= max_chars:
        return s
    return s[: max(0, max_chars - 1)].rstrip() + "…"


def _share_path(feed: str, episode_slug: str, t_sec: float) -> str:
    t = int(max(0.0, float(t_sec)))
    return f"/{feed}/{episode_slug}/#t={t}"


def _recommendation_with_source(*, recommendation: str, source_title: str, content_label: str) -> str:
    text = normalize_ws(recommendation or "").strip()
    title = normalize_ws(source_title or "").strip()
    label = normalize_ws(content_label or "").strip() or "message"
    if not text:
        return text
    lower = text.lower()
    if title and title.lower() in lower:
        return text
    if label.lower() in lower and " from " in lower:
        return text
    if title and label.lower() in title.lower():
        prefix = f"{title} is worth a watch if this is where you are: "
    elif title:
        prefix = f"This {label} from {title} is worth a watch if this is where you are: "
    else:
        prefix = f"This {label} is worth a watch if this is where you are: "
    return prefix + text[0].lower() + text[1:] if len(text) > 1 and text[0].isupper() else prefix + text


def search_segments(
    *,
    db_path: Path,
    q: str,
    limit: int = 12,
    candidates: int = 160,
    include_noncontent: bool = False,
) -> dict[str, Any]:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    if bool(_meta_get(con, "fts_dirty", False)):
        return {"query": q, "fts": "", "results": [], "episodes": [], "error": "index-stale-run-analyze-then-index"}
    fts_variants, expanded_terms = _build_fts_query_variants(q)
    if not fts_variants:
        return {"query": q, "fts": "", "results": [], "episodes": [], "error": "empty-query"}

    rows: list[sqlite3.Row] = []
    used_fts = ""
    for fts_q in fts_variants:
        rows = con.execute(
            """
            SELECT rowid, bm25(segments_fts, 1.0, 0.6, 0.2, 0.2) AS bm25
            FROM segments_fts
            WHERE segments_fts MATCH ?
            ORDER BY bm25
            LIMIT ?
            """,
            (fts_q, int(max(1, candidates))),
        ).fetchall()
        if rows:
            used_fts = fts_q
            break

    if not rows:
        return {"query": q, "fts": fts_variants[0], "expanded_terms": expanded_terms, "results": [], "episodes": []}

    ids = [int(r["rowid"]) for r in rows]
    bm25_by_id = {int(r["rowid"]): float(r["bm25"]) for r in rows}
    placeholders = ",".join(["?"] * len(ids))
    seg_rows = con.execute(f"SELECT * FROM segments WHERE id IN ({placeholders})", ids).fetchall()

    results: list[dict[str, Any]] = []
    for r in seg_rows:
        seg_id = int(r["id"])
        bm25 = float(bm25_by_id.get(seg_id, 0.0))
        base = max(0.0, -bm25)  # convert to positive-ish
        kind = str(r["kind"] or "content")
        kind_mult = 1.0
        if not include_noncontent and kind in {"ad", "intro", "outro", "announcements", "transition"}:
            kind_mult = 0.55
        theme = float(r["theme"] or 0.0)
        ans = float(r["answer"] or 0.0)
        score = base * (1.0 + 0.50 * theme + 0.35 * ans) * kind_mult

        start = float(r["start_sec"] or 0.0)
        end = float(r["end_sec"] or start)
        results.append(
            {
                "segment_id": seg_id,
                "score": float(score),
                "bm25": float(bm25),
                "feed": str(r["feed"]),
                "episode_slug": str(r["episode_slug"]),
                "episode_title": str(r["episode_title"]),
                "episode_date": str(r["episode_date"]),
                "start_sec": float(start),
                "end_sec": float(end),
                "kind": kind,
                "kind_conf": float(r["kind_conf"] or 0.0),
                "theme": theme,
                "answer": ans,
                "share_path": _share_path(str(r["feed"]), str(r["episode_slug"]), start),
                "transcript_path": str(r["file_path"]),
                "snippet": _snippet(str(r["text"])),
            }
        )

    results.sort(key=lambda x: float(x["score"]), reverse=True)
    results = results[: int(max(1, limit))]

    # Episode-level aggregation: max segment score per episode.
    by_ep: dict[tuple[str, str], dict[str, Any]] = {}
    for seg in results:
        k = (seg["feed"], seg["episode_slug"])
        cur = by_ep.get(k)
        if not cur or float(seg["score"]) > float(cur["score"]):
            by_ep[k] = {
                "feed": seg["feed"],
                "episode_slug": seg["episode_slug"],
                "episode_title": seg["episode_title"],
                "episode_date": seg["episode_date"],
                "score": float(seg["score"]),
                "best_segment_id": int(seg["segment_id"]),
                "best_start_sec": float(seg["start_sec"]),
                "share_path": seg["share_path"],
            }
    episodes = sorted(by_ep.values(), key=lambda x: float(x["score"]), reverse=True)

    return {
        "query": q,
        "fts": used_fts or fts_variants[0],
        "fts_variants": fts_variants,
        "expanded_terms": expanded_terms,
        "results": results,
        "episodes": episodes,
    }


def load_segment_context(*, db_path: Path, segment_id: int, before: int = 1, after: int = 1, include_text: bool = False) -> dict[str, Any]:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT * FROM segments WHERE id=?", (int(segment_id),)).fetchone()
    if not row:
        return {"segment_id": int(segment_id), "error": "not-found"}
    feed = str(row["feed"])
    ep = str(row["episode_slug"])
    file_path = str(row["file_path"])
    start = float(row["start_sec"] or 0.0)

    prev_rows = con.execute(
        """
        SELECT id, start_sec, end_sec, kind, kind_conf, text
        FROM segments
        WHERE file_path=? AND end_sec <= ?
        ORDER BY end_sec DESC
        LIMIT ?
        """,
        (file_path, start, int(max(0, before))),
    ).fetchall()
    next_rows = con.execute(
        """
        SELECT id, start_sec, end_sec, kind, kind_conf, text
        FROM segments
        WHERE file_path=? AND start_sec >= ?
        ORDER BY start_sec ASC
        LIMIT ?
        """,
        (file_path, start, int(max(0, after)) + 1),
    ).fetchall()

    def to_min(r: sqlite3.Row) -> dict[str, Any]:
        out = {
            "segment_id": int(r["id"]),
            "start_sec": float(r["start_sec"] or 0.0),
            "end_sec": float(r["end_sec"] or 0.0),
            "kind": str(r["kind"] or "content"),
            "kind_conf": float(r["kind_conf"] or 0.0),
            "snippet": _snippet(str(r["text"]), max_chars=320),
        }
        if include_text:
            out["text"] = normalize_ws(strip_html(str(r["text"] or "")))
        return out

    context = [to_min(r) for r in reversed(prev_rows)] + [to_min(r) for r in next_rows]
    return {
        "segment_id": int(segment_id),
        "feed": feed,
        "episode_slug": ep,
        "episode_title": str(row["episode_title"]),
        "episode_date": str(row["episode_date"]),
        "transcript_path": file_path,
        "share_path": _share_path(feed, ep, float(row["start_sec"] or 0.0)),
        "context": context,
    }


def _format_timecode(sec: float) -> str:
    total = int(max(0.0, float(sec)))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h > 0:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _normalize_quote_for_match(text: str) -> str:
    return normalize_ws(strip_html(text or "")).strip()


def _pick_verified_quote(requested_quote: str, *, segment_text: str, fallback_text: str = "") -> str:
    seg_norm = _normalize_quote_for_match(segment_text)
    req_norm = _normalize_quote_for_match(requested_quote)
    if req_norm and seg_norm:
        i = seg_norm.lower().find(req_norm.lower())
        if i >= 0:
            return seg_norm[i : i + len(req_norm)]
    best = _best_sentence(segment_text or fallback_text)
    if best:
        return best[:220].rstrip()
    return _snippet(segment_text or fallback_text, max_chars=220)


def _answer_candidate_kind_weight(kind: str) -> float:
    k = str(kind or "").strip().lower()
    if k in {"teaching", "application", "message", "content", "story", "testimony", "conversation", "interview", "q_and_a"}:
        return 1.0
    if k in {"scripture", "illustration", "response"}:
        return 0.92
    if k in {"welcome", "intro", "worship", "prayer", "communion", "invitation", "benediction", "outro"}:
        return 0.62
    if k in {"announcements", "ad", "giving", "transition"}:
        return 0.40
    return 0.82


def _query_overlap_score(text: str, queries: Iterable[str]) -> float:
    text_toks = {
        t
        for t in _filter_tokens(_tokenize(normalize_ws(text or "")))
        if len(t) >= 5 or t in _THEME_WEIGHTS
    }
    if not text_toks:
        return 0.0
    score = 0.0
    for query in queries:
        q_toks = {
            t
            for t in _filter_tokens(_tokenize(normalize_ws(query or "")))
            if len(t) >= 5 or t in _THEME_WEIGHTS
        }
        if not q_toks:
            continue
        inter = len(text_toks & q_toks)
        if inter <= 0:
            continue
        score = max(score, inter / float(max(1, min(len(q_toks), 6))))
    return score


def _pick_focus_segment(*, context: list[dict[str, Any]], queries: list[str], default_segment_id: int) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_score = -1.0
    for seg in context:
        seg_id = int(seg.get("segment_id") or 0)
        if seg_id <= 0:
            continue
        kind = str(seg.get("kind") or "content")
        text = str(seg.get("text") or seg.get("snippet") or "")
        score = (_query_overlap_score(text, queries) * 3.0) + (_answer_candidate_kind_weight(kind) * 0.6)
        if seg_id == int(default_segment_id):
            score += 0.05
        if best is None or score > best_score:
            best = seg
            best_score = score
    return best


def answer_question(
    *,
    db_path: Path,
    transcripts_root: Path,
    q: str,
    answers: int = 3,
    per_query_limit: int = 8,
    candidates: int = 180,
    review_candidates: int = 6,
    include_noncontent: bool = False,
) -> dict[str, Any]:
    from answer_engine_llm import plan_query, summarize_answer_candidate

    question = normalize_ws(strip_html(q or "")).strip()
    if not question:
        return {"query": q, "error": "empty-query", "answers": []}

    plan = plan_query(question=question)
    search_queries: list[str] = []
    problem_space_queries = _build_problem_space_queries(
        question=question,
        related_topics=(plan.related_topics if plan else []),
        max_queries=4,
    )
    seen_q: set[str] = set()
    for query in [question] + list((plan.search_queries if plan else []) or []) + problem_space_queries:
        qq = normalize_ws(query or "").strip()
        if len(qq) < 3:
            continue
        key = qq.lower()
        if key in seen_q:
            continue
        seen_q.add(key)
        search_queries.append(qq)
        if len(search_queries) >= 8:
            break

    merged: dict[int, dict[str, Any]] = {}
    search_runs: list[dict[str, Any]] = []
    for idx, query in enumerate(search_queries or [question]):
        payload = search_segments(
            db_path=db_path,
            q=query,
            limit=int(max(1, per_query_limit)),
            candidates=int(max(20, candidates)),
            include_noncontent=bool(include_noncontent),
        )
        search_runs.append(
            {
                "query": query,
                "fts": payload.get("fts"),
                "expanded_terms": list(payload.get("expanded_terms") or []),
                "result_count": len(payload.get("results") or []),
            }
        )
        query_weight = 1.0 if idx == 0 else max(0.58, 0.92 - (0.08 * idx))
        for rank, seg in enumerate(payload.get("results") or []):
            seg_id = int(seg.get("segment_id") or 0)
            if seg_id <= 0:
                continue
            rank_mult = max(0.55, 1.0 - (0.05 * rank))
            cur = merged.get(seg_id)
            score = float(seg.get("score") or 0.0) * query_weight * rank_mult
            if cur is None:
                cur = dict(seg)
                cur["retrieval_score"] = float(score)
                cur["query_matches"] = [query]
                cur["expanded_terms"] = list(payload.get("expanded_terms") or [])
                merged[seg_id] = cur
            else:
                cur["retrieval_score"] = max(float(cur.get("retrieval_score") or 0.0), float(score))
                matches = list(cur.get("query_matches") or [])
                if query not in matches:
                    matches.append(query)
                cur["query_matches"] = matches

    if not merged:
        return {
            "query": question,
            "plan": {
                "intent": plan.intent if plan else "",
                "search_queries": search_queries,
                "problem_space_queries": problem_space_queries,
                "related_topics": (plan.related_topics if plan else []),
            },
            "search_runs": search_runs,
            "answers": [],
        }

    retrieved = sorted(
        merged.values(),
        key=lambda x: (
            (float(x.get("retrieval_score") or 0.0) * _answer_candidate_kind_weight(str(x.get("kind") or "")))
            + (0.10 * len(x.get("query_matches") or []))
        ),
        reverse=True,
    )

    picked: list[dict[str, Any]] = []
    episode_starts: dict[tuple[str, str], list[float]] = {}
    for seg in retrieved:
        ep_key = (str(seg.get("feed") or ""), str(seg.get("episode_slug") or ""))
        starts = episode_starts.setdefault(ep_key, [])
        start_sec = float(seg.get("start_sec") or 0.0)
        if any(abs(start_sec - prev) < 90.0 for prev in starts):
            continue
        starts.append(start_sec)
        picked.append(seg)
        if len(picked) >= int(max(1, review_candidates)):
            break

    reviewed: list[dict[str, Any]] = []
    for seg in picked:
        source_ctx = _source_context_for_feed(str(seg.get("feed") or ""), episode_title=str(seg.get("episode_title") or ""))
        ctx = load_segment_context(
            db_path=db_path,
            segment_id=int(seg.get("segment_id") or 0),
            before=2,
            after=3,
            include_text=True,
        )
        context = list(ctx.get("context") or [])
        if not context:
            continue
        by_id = {int(c.get("segment_id") or 0): c for c in context if int(c.get("segment_id") or 0) > 0}
        focus = _pick_focus_segment(
            context=context,
            queries=[question] + list(seg.get("query_matches") or []),
            default_segment_id=int(seg.get("segment_id") or 0),
        )
        if not focus:
            continue
        focus_id = int(focus.get("segment_id") or 0)
        focus_index = next((i for i, c in enumerate(context) if int(c.get("segment_id") or 0) == focus_id), 0)
        review_context = context[max(0, focus_index - 1) : min(len(context), focus_index + 2)]
        if not review_context:
            review_context = [focus]
        llm_summary = summarize_answer_candidate(
            question=question,
            episode_title=str(seg.get("episode_title") or ""),
            source_title=str(source_ctx.get("source_title") or ""),
            source_category=str(source_ctx.get("source_category") or ""),
            source_tags=list(source_ctx.get("source_tags") or []),
            content_label=str(source_ctx.get("content_label") or ""),
            chapter_hint="",
            retrieval_queries=list(seg.get("query_matches") or []),
            context_segments=[
                {
                    "segment_id": int(c.get("segment_id") or 0),
                    "timecode": _format_timecode(float(c.get("start_sec") or 0.0)),
                    "kind": str(c.get("kind") or "content"),
                    "text": str(c.get("text") or ""),
                }
                for c in review_context
            ],
        )
        focus_overlap = _query_overlap_score(str(focus.get("text") or focus.get("snippet") or ""), [question] + list(seg.get("query_matches") or []))
        if llm_summary is None or not llm_summary.recommendation:
            continue
        if not llm_summary.relevant and max(focus_overlap, float(llm_summary.relevance or 0.0)) < 0.34:
            continue

        start_ctx = focus
        quote_ctx = focus
        if not start_ctx or not quote_ctx:
            continue

        start_sec = float(start_ctx.get("start_sec") or seg.get("start_sec") or 0.0)
        quote_text = _pick_verified_quote(
            "",
            segment_text=str(quote_ctx.get("text") or ""),
            fallback_text=str(start_ctx.get("text") or ""),
        )
        recommendation_text = _recommendation_with_source(
            recommendation=str(llm_summary.recommendation or llm_summary.summary or ""),
            source_title=str(source_ctx.get("source_title") or ""),
            content_label=str(source_ctx.get("content_label") or ""),
        )

        reviewed.append(
            {
                "feed": str(seg.get("feed") or ""),
                "episode_slug": str(seg.get("episode_slug") or ""),
                "episode_title": str(seg.get("episode_title") or ""),
                "episode_date": str(seg.get("episode_date") or ""),
                "source_title": str(source_ctx.get("source_title") or ""),
                "source_category": str(source_ctx.get("source_category") or ""),
                "source_tags": list(source_ctx.get("source_tags") or []),
                "content_label": str(source_ctx.get("content_label") or ""),
                "segment_id": int(seg.get("segment_id") or 0),
                "start_segment_id": int(start_ctx.get("segment_id") or seg.get("segment_id") or 0),
                "quote_segment_id": int(quote_ctx.get("segment_id") or 0),
                "start_sec": float(start_sec),
                "timecode": _format_timecode(start_sec),
                "share_path": _share_path(str(seg.get("feed") or ""), str(seg.get("episode_slug") or ""), start_sec),
                "transcript_path": str(seg.get("transcript_path") or ""),
                "retrieval_score": float(seg.get("retrieval_score") or 0.0),
                "relevance": max(float(llm_summary.relevance or 0.0), float(focus_overlap or 0.0)),
                "score": (float(seg.get("retrieval_score") or 0.0) * 0.55) + (max(float(llm_summary.relevance or 0.0), float(focus_overlap or 0.0)) * 2.0),
                "recommendation": recommendation_text,
                "summary": recommendation_text,
                "why_relevant": llm_summary.why_relevant,
                "quote": quote_text,
                "tags": list(llm_summary.tags or []),
                "query_matches": list(seg.get("query_matches") or []),
                "supporting_context": [
                    {
                        "segment_id": int(c.get("segment_id") or 0),
                        "start_sec": float(c.get("start_sec") or 0.0),
                        "timecode": _format_timecode(float(c.get("start_sec") or 0.0)),
                        "kind": str(c.get("kind") or "content"),
                        "snippet": str(c.get("snippet") or ""),
                    }
                    for c in context
                ],
            }
        )

    by_episode: dict[tuple[str, str], dict[str, Any]] = {}
    for ans in reviewed:
        key = (str(ans.get("feed") or ""), str(ans.get("episode_slug") or ""))
        cur = by_episode.get(key)
        if cur is None or float(ans.get("score") or 0.0) > float(cur.get("score") or 0.0):
            by_episode[key] = ans

    answers_out = sorted(by_episode.values(), key=lambda x: float(x.get("score") or 0.0), reverse=True)[: int(max(1, answers))]
    return {
        "query": question,
        "plan": {
            "intent": plan.intent if plan else "",
            "search_queries": search_queries,
            "problem_space_queries": problem_space_queries,
            "related_topics": (plan.related_topics if plan else []),
        },
        "search_runs": search_runs,
        "reviewed_candidates": len(reviewed),
        "answers": answers_out,
    }


_BIBLE_BOOKS_RE = (
    r"genesis|exodus|leviticus|numbers|deuteronomy|joshua|judges|ruth|"
    r"1\\s*samuel|2\\s*samuel|1\\s*kings|2\\s*kings|1\\s*chronicles|2\\s*chronicles|"
    r"ezra|nehemiah|esther|job|psalms?|proverbs|ecclesiastes|song\\s+of\\s+songs|song\\s+of\\s+solomon|"
    r"isaiah|jeremiah|lamentations|ezekiel|daniel|hosea|joel|amos|obadiah|jonah|micah|nahum|habakkuk|"
    r"zephaniah|haggai|zechariah|malachi|"
    r"matthew|mark|luke|john|acts|romans|"
    r"1\\s*corinthians|2\\s*corinthians|galatians|ephesians|philippians|colossians|"
    r"1\\s*thessalonians|2\\s*thessalonians|1\\s*timothy|2\\s*timothy|titus|philemon|"
    r"hebrews|james|1\\s*peter|2\\s*peter|1\\s*john|2\\s*john|3\\s*john|jude|revelation"
)


def _extract_bible_ref(text: str) -> str:
    s = normalize_ws(strip_html(text or ""))
    if not s:
        return ""
    # Examples:
    # - "Mark 2:1-12"
    # - "1 Corinthians 13"
    # - "Ephesians chapter 2"
    pat = re.compile(rf"\\b({_BIBLE_BOOKS_RE})\\b\\s+(?:chapter\\s+)?(\\d{{1,3}})(?::(\\d{{1,3}}))?", re.I)
    m = pat.search(s)
    if not m:
        return ""
    book = normalize_ws(m.group(1) or "")
    ch = m.group(2) or ""
    vs = m.group(3) or ""
    if not book or not ch:
        return ""
    book = re.sub(r"\\s+", " ", book).strip()
    # Normalize "1 john" -> "1 John"
    book = " ".join([w.capitalize() if not w.isdigit() else w for w in book.split()])
    return f"{book} {ch}" + (f":{vs}" if vs else "")


def _extract_sponsor_hint(text: str) -> str:
    s = normalize_ws(strip_html(text or "")).strip()
    if not s:
        return ""
    m = re.search(r"\\b(sponsored\\s+by|brought\\s+to\\s+you\\s+by)\\s+([^\\n\\.,;]{3,60})", s, re.I)
    if m:
        name = normalize_ws(m.group(2) or "")
        name = re.sub(r"\\b(the|a|an)\\b\\s+", "", name, flags=re.I).strip()
        return name[:50].strip()
    m2 = re.search(r"\\b([a-z0-9][a-z0-9\\-]{1,40}\\.(com|org|net|io|co|app))\\b", s, re.I)
    if m2:
        return str(m2.group(1) or "").lower()
    return ""


def _truncate_title(s: str, *, max_len: int = 84) -> str:
    s = normalize_ws(s or "")
    if len(s) <= max_len:
        return s
    return s[: max(0, max_len - 1)].rstrip() + "…"


def _title_tokens(s: str) -> list[str]:
    toks = [_norm_token(t) for t in _tokenize(s)]
    return [t for t in toks if t and t not in _STOPWORDS]


def _titles_too_similar(a: str, b: str) -> bool:
    aa = _title_tokens(a)
    bb = _title_tokens(b)
    if not aa or not bb:
        return False
    sa = set(aa)
    sb = set(bb)
    if not sa or not sb:
        return False
    if sa == sb:
        return True
    inter = len(sa & sb)
    union = len(sa | sb)
    if union <= 0:
        return False
    return (inter / float(union)) >= 0.72


def _split_sentences(text: str) -> list[str]:
    s = normalize_ws(strip_html(text or "")).strip()
    if not s:
        return []
    parts = re.split(r"(?:\n+|(?<=[.!?])\s+)", s)
    out: list[str] = []
    for p in parts:
        pp = normalize_ws(p).strip()
        if not pp:
            continue
        alpha = sum(1 for ch in pp if ch.isalpha())
        if alpha < 12:
            continue
        out.append(pp)
    return out


def _best_sentence(text: str) -> str:
    sents = _split_sentences(text)
    if not sents:
        return ""

    def score(sent: str) -> float:
        ref = 1.0 if _extract_bible_ref(sent) else 0.0
        td = theme_density(sent)
        ans = answeriness(sent)
        n = len(sent)
        length_bonus = 0.0
        if 48 <= n <= 130:
            length_bonus = 0.35
        elif 28 <= n <= 170:
            length_bonus = 0.15
        else:
            length_bonus = -0.10
        return (td * 0.9) + (ans * 0.5) + (ref * 0.55) + length_bonus

    best = max(sents, key=score)
    best = re.sub(r"^(and|so|but|well|okay|right)\b[\s,]+", "", best, flags=re.I).strip()
    best = best.rstrip(" .!?:;,-")
    return best


_PRAYER_KW_DROP = {
    "lord",
    "father",
    "jesus",
    "christ",
    "spirit",
    "holy",
    "amen",
    "heaven",
    "heavenly",
    "god",
    "pray",
    "prayer",
    "thank",
    "thanks",
    "please",
}


def _dedupe_keywords(kws: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def canon(kw: str) -> str:
        toks = [_norm_token(t) for t in _tokenize(kw)]
        toks = [t for t in toks if t and t not in _STOPWORDS]
        if not toks:
            return ""
        return " ".join(toks[:4])

    for kw in kws or []:
        c = canon(kw)
        if not c or c in seen:
            continue
        seen.add(c)
        out.append(normalize_ws(kw))
    return out


def _extract_prayer_subject(text: str) -> str:
    s = normalize_ws(strip_html(text or "")).strip()
    if not s:
        return ""
    sl = s.lower()
    m = re.search(
        r"\b(we\s+pray\s+for|i\s+pray\s+for|we\s+ask\s+(?:that|you)\b|help\s+us\s+to|forgive\s+us\s+for|thank\s+you\s+for|we\s+thank\s+you\s+for|i\s+thank\s+you\s+for)\s+(.{12,140})",
        sl,
        re.I,
    )
    if m:
        tail = normalize_ws(m.group(2) or "")
        tail = re.split(r"[.;\n]|\b(in\s+jesus('?s)?\s+name|amen)\b", tail, maxsplit=1, flags=re.I)[0]
        tail = tail.strip(" ,.-")
        if tail:
            toks = [_norm_token(t) for t in _tokenize(tail)]
            toks = [t for t in toks if t and t not in _STOPWORDS and t not in _PRAYER_KW_DROP]
            if len(toks) < 2:
                return ""
            return _truncate_title(tail, max_len=56)
    return ""


def _chapter_title(kind: str, text: str, *, conf: float | None = None, title_mode: str = "semantic") -> str:
    kind = (kind or "").strip().lower()
    ref = _extract_bible_ref(text)
    tm = (title_mode or "semantic").strip().lower()
    if tm not in {"semantic", "embed", "embeddings", "hybrid"}:
        raise ValueError(f"Unsupported chapter title mode: {title_mode}")

    from answer_engine_semantic import keyphrases_for_title, representative_sentence  # type: ignore

    kw0 = keyphrases_for_title(text, top_n=8)
    kw: list[str] = []
    for k in kw0:
        kk = normalize_ws(k).strip()
        if not kk:
            continue
        if len(kk) > 54:
            kk = _truncate_title(kk, max_len=54)
        kw.append(kk)
        if len(kw) >= 3:
            break

    kw_s = ", ".join(kw) if kw else ""
    sent = representative_sentence(text, max_chars=104)

    if kind == "welcome":
        base = "Welcome"
        if sent:
            return _truncate_title(f"{base} — {sent}")
        if kw_s:
            return _truncate_title(f"{base} — {kw_s}")
        return base

    if kind == "intro":
        base = "Intro"
        if ref:
            base += f" — {ref}"
        if sent:
            base += f" — {sent}"
            return _truncate_title(base)
        if kw_s:
            base += f" — {kw_s}"
        return _truncate_title(base)

    if kind == "worship":
        base = "Worship"
        if sent:
            return _truncate_title(f"{base} — {sent}")
        if kw_s:
            return _truncate_title(f"{base} — {kw_s}")
        return base

    if kind == "outro":
        base = "Outro"
        if sent:
            base += f" — {sent}"
            return _truncate_title(base)
        if kw_s:
            base += f" — {kw_s}"
        return _truncate_title(base)

    if kind == "transition":
        s = normalize_ws(strip_html(text or "")).strip()
        if re.search(r"\\[\\s*music\\s*\\]|♪", s, re.I):
            return "Music break"
        m = re.search(r"\b(after\s+the\s+break|when\s+we\s+return|back\s+in\s+(a\\s+)?moment)\\b\\s*(.{0,100})", s, re.I)
        if m:
            tail = normalize_ws(m.group(2) or "").strip(" ,.-")
            if tail:
                return _truncate_title(f"Break — {tail}", max_len=84)
        return "Break / transition"

    if kind == "ad":
        hint = _extract_sponsor_hint(text)
        base = "Sponsor / support"
        if hint:
            base += f" — {hint}"
        return _truncate_title(base)

    if kind == "announcements":
        base = "Announcements"
        if sent:
            base += f" — {sent}"
            return _truncate_title(base)
        if kw_s:
            base += f" — {kw_s}"
        return _truncate_title(base)

    if kind == "giving":
        base = "Giving / generosity"
        if sent:
            return _truncate_title(f"{base} — {sent}")
        if kw_s:
            return _truncate_title(f"{base} — {kw_s}")
        return base

    if kind == "prayer":
        s = normalize_ws(strip_html(text or "")).lower()
        if re.search(r"\bin\s+the\s+name\s+of\s+the\s+father\b", s):
            return "Prayer — Doxology"
        if re.search(r"\bour\s+father\s+who\s+(art|is)\b", s):
            return "Prayer — The Lord's Prayer"
        subj = _extract_prayer_subject(text)
        if subj:
            return _truncate_title(f"Prayer — {subj}")
        return "Prayer"

    if kind in {"scripture", "reading"}:
        label = "Scripture reading" if kind == "scripture" else "Reading"
        if ref and sent:
            return _truncate_title(f"{label} — {ref} — {sent}")
        if ref:
            return _truncate_title(f"{label} — {ref}")
        if sent:
            return _truncate_title(f"{label} — {sent}")
        if kw_s:
            return _truncate_title(f"{label} — {kw_s}")
        return label

    if kind in {"message", "teaching"}:
        label = "Message" if kind == "message" else "Teaching"
        if ref and sent:
            return _truncate_title(f"{label} — {ref} — {sent}")
        if ref:
            return _truncate_title(f"{label} — {ref}")
        if sent:
            return _truncate_title(f"{label} — {sent}")
        if kw_s:
            return _truncate_title(f"{label} — {kw_s}")
        return label

    if kind == "application":
        if sent:
            return _truncate_title(f"Application — {sent}")
        if kw_s:
            return _truncate_title(f"Application — {kw_s}")
        return "Application"

    if kind == "topic":
        if ref and sent:
            return _truncate_title(f"Topic — {ref} — {sent}")
        if ref:
            return _truncate_title(f"Topic — {ref}")
        if sent:
            return _truncate_title(f"Topic — {sent}")
        if kw_s:
            return _truncate_title(f"Topic — {kw_s}")
        return "Topic"

    if kind in {"illustration", "story"}:
        label = "Illustration" if kind == "illustration" else "Story"
        if sent:
            return _truncate_title(f"{label} — {sent}")
        if kw_s:
            return _truncate_title(f"{label} — {kw_s}")
        return label

    if kind == "testimony":
        if sent:
            return _truncate_title(f"Testimony — {sent}")
        if kw_s:
            return _truncate_title(f"Testimony — {kw_s}")
        return "Testimony"

    if kind in {"conversation", "interview", "q_and_a"}:
        label = {"conversation": "Conversation", "interview": "Interview", "q_and_a": "Q&A"}[kind]
        if sent:
            return _truncate_title(f"{label} — {sent}")
        if kw_s:
            return _truncate_title(f"{label} — {kw_s}")
        return label

    if kind in {"response", "invitation", "communion", "benediction"}:
        label = {
            "response": "Response",
            "invitation": "Invitation",
            "communion": "Communion",
            "benediction": "Benediction",
        }[kind]
        if sent:
            return _truncate_title(f"{label} — {sent}")
        if kw_s:
            return _truncate_title(f"{label} — {kw_s}")
        return label

    if _is_open_content_kind(kind):
        label = kind.replace("_", " ").strip().title()
        if ref and sent:
            return _truncate_title(f"{label} — {ref} — {sent}")
        if sent:
            return _truncate_title(f"{label} — {sent}")
        if kw_s:
            return _truncate_title(f"{label} — {kw_s}")
        return label

    # content/topic
    if ref and sent:
        return _truncate_title(f"{ref} — {sent}")
    if ref:
        return _truncate_title(ref)
    if sent:
        return _truncate_title(sent)
    if kw_s:
        return _truncate_title(kw_s)
    return "Chapter"


def chapters_from_segments(*, feed: str, episode_slug: str, segments: list[Segment], mode: str = "semantic") -> dict[str, Any]:
    total = float(max((s.end for s in segments), default=0.0))
    if total <= 0.0:
        return {"feed": feed, "episode_slug": episode_slug, "chapters": []}

    chapters: list[dict[str, Any]] = []
    title_mode = (mode or "semantic").strip().lower()
    if title_mode not in {"semantic", "embed", "embeddings", "hybrid"}:
        raise ValueError(f"Unsupported chapters mode: {mode}")
    llm_enabled = title_mode == "hybrid"

    def interval_text(start_t: float, end_t: float) -> str:
        bits = [s.text for s in segments if s.end > float(start_t) and s.start < float(end_t)]
        return normalize_ws(" ".join(bits))

    def fallback_tags(text: str, *, limit: int = 4) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for kw in top_keywords(text, k=max(2, limit * 2), n=2) or []:
            tag = normalize_ws(kw).strip().lower()
            if not tag or len(tag) < 3:
                continue
            if tag in seen:
                continue
            seen.add(tag)
            out.append(tag[:40])
            if len(out) >= limit:
                break
        return out

    def add(t: float, title: str, *, kind: str | None = None, conf: float | None = None, tags: list[str] | None = None) -> None:
        if not title:
            return
        t = float(max(0.0, min(total, t)))
        if any(abs(float(existing.get("startTime") or 0.0) - t) < 2.0 for existing in chapters):
            return
        if chapters:
            prev = chapters[-1]
            prev_title = str(prev.get("title") or "")
            prev_t = float(prev.get("startTime") or 0.0)
            prev_kind = str(prev.get("kind") or "")
            if abs(t - prev_t) <= 12 * 60.0 and _titles_too_similar(prev_title, title):
                if kind in {"topic", "message"} or prev_kind in {"topic", "message"}:
                    return
        ch: dict[str, Any] = {"startTime": t, "title": title}
        if kind:
            ch["kind"] = str(kind)
        if conf is not None:
            ch["confidence"] = float(conf)
        if tags:
            ch["tags"] = list(tags)
        chapters.append(ch)

    # Intro run (early non-content) + main message start.
    intro_end = 0.0
    intro_texts: list[str] = []
    intro_kind_texts: dict[str, list[str]] = {}
    intro_kind_scores: dict[str, float] = {}
    for s in segments:
        if s.start > 8 * 60.0:
            break
        if s.kind != "content" and s.kind_conf >= 0.50:
            intro_end = float(s.end)
            intro_kind_texts.setdefault(str(s.kind or "intro"), []).append(s.text)
            intro_kind_scores[str(s.kind or "intro")] = float(intro_kind_scores.get(str(s.kind or "intro"), 0.0)) + float(
                max(0.35, s.kind_conf)
            )
            if s.kind not in {"prayer", "worship"}:
                intro_texts.append(s.text)
            continue
        # Stop after we hit clear content for a bit.
        if s.kind == "content" and s.start >= 15.0:
            break

    main_start = 0.0
    for s in segments:
        if s.kind == "content" and s.start >= max(20.0, intro_end - 1.0):
            main_start = float(s.start)
            break

    if intro_texts or intro_kind_texts:
        intro_kind = "intro"
        if intro_kind_scores:
            ranked = sorted(intro_kind_scores.items(), key=lambda kv: (-float(kv[1]), kv[0]))
            top_kind, top_score = ranked[0]
            if top_kind in {"welcome", "worship", "scripture", "reading", "giving", "announcements"} and top_score >= 0.70:
                intro_kind = top_kind
        intro_source = intro_kind_texts.get(intro_kind) or intro_texts
        intro_txt = normalize_ws(" ".join(intro_source or intro_texts))
        if intro_txt:
            add(0.0, _chapter_title(intro_kind, intro_txt, title_mode=title_mode), kind=intro_kind, tags=fallback_tags(intro_txt))
    if main_start > 0.0:
        # Name the main message from the first ~8 minutes of content.
        main_segments = [s for s in segments if s.kind == "content" and s.start >= main_start and s.start < main_start + 8 * 60.0]
        title_segments = main_segments[1:] if len(main_segments) >= 3 else main_segments
        main_txt = " ".join(s.text for s in title_segments)
        add(main_start, _chapter_title("message", main_txt, title_mode=title_mode), kind="message", tags=fallback_tags(main_txt))

    edge_window = min(8 * 60.0, max(3 * 60.0, total * 0.16))
    content_window_end = max(main_start + 90.0, edge_window)

    # Runs worth marking as chapters.
    i = 0
    while i < len(segments):
        s = segments[i]
        min_conf = 0.60
        if s.kind in {"ad", "transition", "worship", "invitation"}:
            min_conf = 0.52
        if s.kind in {"welcome", "worship", "scripture", "reading", "giving", "invitation", "ad", "announcements", "prayer", "transition", "benediction", "outro"} and s.kind_conf >= min_conf:
            kind = s.kind
            conf = s.kind_conf
            run_start = s.start
            j = i + 1
            run_texts = [s.text]
            while (
                j < len(segments)
                and segments[j].kind == kind
                and segments[j].kind_conf >= 0.55
                and (segments[j].start - segments[j - 1].end) <= 8.0
            ):
                conf = max(conf, segments[j].kind_conf)
                run_texts.append(segments[j].text)
                j += 1
            run_end = float(segments[j - 1].end)
            run_dur = max(0.0, run_end - float(run_start))
            near_start = bool(run_start <= content_window_end)
            near_end = bool(run_start >= max(main_start + 60.0, total - edge_window))
            allow = True
            if kind == "prayer":
                allow = near_start or near_end or (conf >= 0.92 and run_dur >= 90.0)
            elif kind == "welcome":
                allow = near_start
            elif kind == "worship":
                allow = near_start or near_end or (conf >= 0.88 and run_dur >= 120.0)
            elif kind in {"scripture", "reading"}:
                allow = near_start or (conf >= 0.86 and run_dur >= 75.0)
            elif kind == "giving":
                allow = near_start or near_end
            elif kind == "invitation":
                allow = near_end or (conf >= 0.88 and run_dur >= 60.0)
            elif kind == "announcements":
                before_message = bool(main_start <= 0.0 or run_start <= main_start + 30.0)
                allow = (near_start and before_message) or near_end
            elif kind in {"ad", "outro"}:
                allow = near_start or near_end
            elif kind == "benediction":
                allow = near_end
            elif kind == "transition":
                allow = near_end or conf >= 0.78
            if not allow:
                i = j
                continue
            run_txt = normalize_ws(" ".join(run_texts))
            if kind in {"worship", "welcome", "prayer"} and re.search(
                r"\b(lead\s+you\s+in\s+a\s+(very\s+)?simple\s+prayer|welcome\s+to\s+the\s+family\s+of\s+god|"
                r"most\s+important\s+decision\s+of\s+your\s+life|decided\s+to\s+follow\s+jesus|"
                r"give\s+your\s+life\s+to\s+(jesus|christ)|pray\s+this\s+prayer)\b",
                run_txt,
                flags=re.I,
            ):
                kind = "invitation"
            title = _chapter_title(kind, run_txt, conf=conf, title_mode=title_mode)
            add(run_start, title, kind=kind, conf=conf if kind in {"ad", "transition", "worship", "invitation"} else None, tags=fallback_tags(run_txt))
            i = j
            continue
        i += 1

    # Avoid generating topic chapters into an outro/support tail.
    content_end = total
    if main_start > 0.0 and total > 0.0:
        for s in segments:
            if s.start < main_start:
                continue
            if s.kind in {"outro", "ad", "announcements", "benediction", "giving"} and s.kind_conf >= 0.55 and s.start >= total * 0.70:
                content_end = min(content_end, float(s.start))
                break

    # Topic chapters come from semantic topic shifts only. We do not synthesize
    # fixed-cadence chapters because they produce misleading labels.
    mode = (mode or "semantic").strip().lower()
    added_topics = 0

    if title_mode in {"semantic", "embed", "embeddings", "hybrid"} and main_start > 0.0 and content_end - main_start >= 900.0:
        from answer_engine_semantic import TextSpan, pick_chapter_times  # type: ignore

        spans = [TextSpan(start=float(s.start), end=float(s.end), text=str(s.text)) for s in segments if s.kind == "content"]
        times = pick_chapter_times(
            spans,
            total_sec=float(content_end),
            main_start_sec=float(main_start),
            min_gap_sec=7 * 60.0,
            max_chapters=12,
        )
        for t in times:
            if t < main_start + 60.0 or t >= content_end - 120.0:
                continue
            window_start = t - 180.0
            window_end = t + 180.0
            txt = " ".join(s.text for s in segments if s.start <= window_end and s.end >= window_start and s.kind == "content")
            if txt:
                kind = "topic"
                title = _chapter_title("topic", txt, title_mode=title_mode)
                tags = fallback_tags(txt)
                if llm_enabled:
                    try:
                        from answer_engine_llm import review_boundary  # type: ignore

                        before_txt = interval_text(max(main_start, t - 210.0), t)
                        after_txt = interval_text(t, min(content_end, t + 210.0))
                        decision = review_boundary(before_text=before_txt, after_text=after_txt, title_hint=title)
                        if decision and not decision.keep:
                            continue
                        if decision:
                            allowed = _BOUNDARY_REVIEW_KINDS
                            proposed = str(decision.kind or kind)
                            kind = proposed if proposed in allowed or _is_open_content_kind(proposed) else kind
                            title = str(decision.title or title)
                            tags = list(decision.tags or tags)
                    except Exception as exc:
                        print(f"[answer-engine] LLM boundary review failed at {t:.1f}s: {exc}", flush=True)
                add(t, title, kind=kind, tags=tags)
                added_topics += 1

    chapters.sort(key=lambda c: float(c.get("startTime") or 0.0))
    # Ensure 0-start chapter exists (nice UX), but don’t spam.
    if not chapters or float(chapters[0].get("startTime") or 0.0) > 2.0:
        chapters.insert(0, {"startTime": 0.0, "title": "Start", "kind": "start"})

    if llm_enabled and chapters:
        try:
            from answer_engine_llm import refine_chapter_metadata  # type: ignore

            for idx, ch in enumerate(chapters):
                start_t = float(ch.get("startTime") or 0.0)
                end_t = float(chapters[idx + 1].get("startTime") or total) if idx + 1 < len(chapters) else total
                chapter_txt = interval_text(start_t, end_t)
                prev_title = str(chapters[idx - 1].get("title") or "") if idx > 0 else ""
                next_title = str(chapters[idx + 1].get("title") or "") if idx + 1 < len(chapters) else ""
                kind_hint = str(ch.get("kind") or "topic")
                if kind_hint in _HARD_LOCKED_KINDS:
                    if not ch.get("tags"):
                        tags = fallback_tags(chapter_txt)
                        if tags:
                            ch["tags"] = tags
                    continue
                meta = refine_chapter_metadata(
                    kind_hint=kind_hint,
                    title_hint=str(ch.get("title") or ""),
                    chapter_text=chapter_txt,
                    prev_title=prev_title,
                    next_title=next_title,
                )
                tags = list(ch.get("tags") or [])
                if meta:
                    next_kind = str(meta.kind or kind_hint or "topic")
                    if next_kind not in (_HUMAN_CHAPTER_KINDS - {"start", "intro", "ad", "transition", "outro", "announcements"}) and not _is_open_content_kind(next_kind):
                        next_kind = kind_hint
                    ch["kind"] = next_kind
                    ch["title"] = str(meta.title or ch.get("title") or "Chapter")
                    tags = list(meta.tags or tags or fallback_tags(chapter_txt))
                elif not tags:
                    tags = fallback_tags(chapter_txt)
                if tags:
                    ch["tags"] = tags
        except Exception as exc:
            print(f"[answer-engine] LLM chapter refinement failed; falling back to extractive tags: {exc}", flush=True)
            for idx, ch in enumerate(chapters):
                if ch.get("tags"):
                    continue
                start_t = float(ch.get("startTime") or 0.0)
                end_t = float(chapters[idx + 1].get("startTime") or total) if idx + 1 < len(chapters) else total
                tags = fallback_tags(interval_text(start_t, end_t))
                if tags:
                    ch["tags"] = tags
    else:
        for idx, ch in enumerate(chapters):
            if ch.get("tags"):
                continue
            start_t = float(ch.get("startTime") or 0.0)
            end_t = float(chapters[idx + 1].get("startTime") or total) if idx + 1 < len(chapters) else total
            tags = fallback_tags(interval_text(start_t, end_t))
            if tags:
                ch["tags"] = tags

    return {
        "version": 1,
        "generator": {"name": "vodcasts-answer-engine", "version": 4, "mode": str(mode or "semantic")},
        "generated_at_unix": int(time.time()),
        "feed": feed,
        "episode_slug": episode_slug,
        "chapters": chapters,
    }


def top_keywords(text: str, *, k: int = 6, n: int = 2) -> list[str]:
    return _yake_keywords(text, top=int(max(1, k)), n=int(max(1, n)))


@lru_cache(maxsize=4)
def _yake_extractor(n: int) -> Any:
    import yake  # type: ignore

    # n=2 allows short phrases without requiring full NLP models.
    # Provide an explicit stopword list so scoring is stable across environments.
    sw = list(get_stop_words("en") or [])
    return yake.KeywordExtractor(lan="en", n=int(max(1, n)), top=40, stopwords=sw)


def _yake_keywords(text: str, *, top: int, n: int = 2) -> list[str]:
    s = normalize_ws(strip_html(text or ""))
    if len(s) < 40:
        return []
    ext = _yake_extractor(int(max(1, n)))
    pairs = ext.extract_keywords(s) or []
    out: list[str] = []
    for kw, score in pairs:
        kww = normalize_ws(str(kw or "")).strip()
        if not kww:
            continue
        # YAKE scores: lower is better; we only need ordering.
        _ = float(score) if score is not None else 0.0
        # Avoid spammy 1-char tokens, and avoid fully stopword phrases.
        toks = [t for t in _tokenize(kww) if _norm_token(t) and _norm_token(t) not in _STOPWORDS]
        if not toks:
            continue
        if kww.lower() in {"like", "yeah", "okay", "right"}:
            continue
        out.append(kww)
        if len(out) >= int(max(1, top)):
            break
    return out


def _write_chapters_for_transcript(*, transcript_path: Path, chapters: dict[str, Any], out_dir: Path | None, adjacent: bool) -> Path | None:
    target = _chapters_output_path(transcript_path=transcript_path, out_dir=out_dir, adjacent=adjacent)
    if not target:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(chapters, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def _chapters_output_path(*, transcript_path: Path, out_dir: Path | None, adjacent: bool) -> Path | None:
    if not adjacent and not out_dir:
        return None
    if adjacent:
        return transcript_path.with_suffix(".chapters.json")
    feed = transcript_path.parent.name
    return (out_dir or Path(".")) / feed / (transcript_path.stem + ".chapters.json")

def _chapters_needs_update(path: Path, *, mode: str) -> bool:
    try:
        raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        gen = raw.get("generator") if isinstance(raw, dict) else None
        if not isinstance(gen, dict):
            return True
        if str(gen.get("name") or "") != "vodcasts-answer-engine":
            return True
        if int(gen.get("version") or 0) != 4:
            return True
        if str(gen.get("mode") or "") != str(mode or "semantic"):
            return True
        return False
    except Exception:
        return True


def default_db_path(cache_dir: Path) -> Path:
    return cache_dir / "answer-engine" / "answer_engine.sqlite"


def parse_common_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--env", default="", help="Cache env (default: active env from VOD_ENV or .vodcasts-env).")
    p.add_argument("--cache", default="", help="Cache dir (default: cache/<env>/).")
    p.add_argument("--transcripts", default="", help="Transcripts root (default: site/assets/transcripts/).")


def resolve_paths(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    env = _canon_env(str(getattr(args, "env", "") or "").strip()) or active_env()
    cache_dir = Path(str(getattr(args, "cache", "") or "")).resolve() if getattr(args, "cache", "") else default_cache_dir(env)
    transcripts_root = (
        Path(str(getattr(args, "transcripts", "") or "")).resolve() if getattr(args, "transcripts", "") else default_transcripts_root()
    )
    db_path = default_db_path(cache_dir)
    return cache_dir, transcripts_root, db_path
