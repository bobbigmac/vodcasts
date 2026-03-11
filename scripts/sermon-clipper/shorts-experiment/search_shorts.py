"""Search for short, snappy sermon thought-bites suitable for vertical shorts."""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_AE_ROOT = _REPO_ROOT / "scripts" / "answer-engine"
_PARENT = Path(__file__).resolve().parent
for p in (_REPO_ROOT, _AE_ROOT, _PARENT.parent):
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

try:
    import webvtt
except Exception:
    webvtt = None


_FILLER_PATTERNS = (
    "i want to",
    "you know",
    "kind of",
    "sort of",
    "and um",
    "and uh",
    "we're gonna",
    "i'm gonna",
)

_STOPWORDS = {
    "about",
    "after",
    "again",
    "because",
    "being",
    "before",
    "could",
    "every",
    "from",
    "have",
    "into",
    "just",
    "jesus",
    "like",
    "more",
    "much",
    "need",
    "people",
    "only",
    "pastor",
    "really",
    "said",
    "still",
    "than",
    "that",
    "thats",
    "their",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "thing",
    "things",
    "very",
    "want",
    "well",
    "will",
    "would",
    "very",
    "what",
    "when",
    "where",
    "which",
    "while",
    "with",
    "your",
}

_PRACTICAL_TERMS = {
    "afraid",
    "alone",
    "anger",
    "anxious",
    "anxiety",
    "awkward",
    "burden",
    "conflict",
    "control",
    "dating",
    "depressed",
    "direction",
    "discouraged",
    "empty",
    "exhausted",
    "family",
    "fear",
    "forgive",
    "forgiveness",
    "friendship",
    "grief",
    "habits",
    "health",
    "healing",
    "heart",
    "home",
    "job",
    "lonely",
    "marriage",
    "money",
    "parent",
    "parenting",
    "pressure",
    "relationships",
    "rest",
    "shame",
    "stressed",
    "stress",
    "stuck",
    "temptation",
    "tired",
    "trust",
    "weak",
    "work",
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
}

_ADVICE_TERMS = {
    "ask",
    "believe",
    "bring",
    "choose",
    "come",
    "give",
    "hold",
    "keep",
    "learn",
    "let",
    "open",
    "receive",
    "remember",
    "release",
    "rest",
    "seek",
    "stop",
    "start",
    "take",
    "trust",
    "wait",
}

_QUESTION_STARTS = (
    "how ",
    "what ",
    "when ",
    "where ",
    "why ",
    "who ",
    "can ",
    "could ",
    "should ",
    "do ",
    "does ",
    "did ",
    "are ",
    "is ",
)

_NEGATIVE_TERMS = {
    "afraid",
    "alone",
    "anxious",
    "awkward",
    "burden",
    "empty",
    "fear",
    "lonely",
    "pressure",
    "shame",
    "stuck",
    "tired",
    "weak",
    "worry",
}

_MOTIF_REQUIRED_TERMS = _PRACTICAL_TERMS | _HOPE_TERMS | _ADVICE_TERMS | _NEGATIVE_TERMS

_GENERIC_MOTIFS = {
    "even",
    "god",
    "jesus",
    "know",
    "life",
    "people",
    "really",
    "thing",
    "things",
    "will",
}

_BRIDGE_MOTIFS = {
    "anxiety": ["peace", "rest", "trust", "help"],
    "control": ["trust", "rest", "grace", "peace"],
    "fear": ["peace", "trust", "love", "strength"],
    "lonely": ["known", "community", "love", "rest"],
    "stress": ["rest", "peace", "strength", "grace"],
    "stuck": ["grace", "freedom", "strength", "trust"],
    "worry": ["peace", "rest", "trust", "help"],
}


def _theme_terms(theme: str) -> set[str]:
    return {term for term in re.findall(r"[a-z0-9']+", (theme or "").lower()) if len(term) > 2}


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def _clip_share_path(feed: str, episode_slug: str, start_sec: float) -> str:
    return f"/{feed}/{episode_slug}/#t={int(max(0.0, start_sec))}"


def _ts_to_sec(ts: str) -> float:
    hh, mm, ss = ts.replace(",", ".").split(":")
    return int(hh) * 3600 + int(mm) * 60 + float(ss)


def _read_cues(transcript_path: Path) -> list[dict]:
    if webvtt is None:
        return []
    cues = []
    try:
        for cue in webvtt.read(str(transcript_path)):
            start = _ts_to_sec(str(cue.start))
            end = _ts_to_sec(str(cue.end))
            text = " ".join(str(cue.text or "").split())
            if end > start and text:
                cues.append({"start": start, "end": end, "text": text})
    except Exception:
        return []
    return cues


def _question_score(text: str) -> float:
    lowered = (text or "").strip().lower()
    if not lowered:
        return 0.0
    score = 0.0
    if lowered.endswith("?"):
        score += 2.5
    if lowered.startswith(_QUESTION_STARTS):
        score += 1.6
    if "?" in lowered:
        score += 0.8
    return score


def _practicality_score(text: str) -> float:
    words = set(_tokenize(text))
    if not words:
        return 0.0
    score = float(len(words.intersection(_PRACTICAL_TERMS))) * 0.9
    if " you " in f" {(text or '').lower()} ":
        score += 0.5
    return score


def _hope_score(text: str) -> float:
    words = set(_tokenize(text))
    return float(len(words.intersection(_HOPE_TERMS))) * 0.8


def _advice_score(text: str) -> float:
    words = set(_tokenize(text))
    score = float(len(words.intersection(_ADVICE_TERMS))) * 0.8
    lowered = (text or "").strip().lower()
    if lowered.startswith(("don't ", "do not ", "stop ", "start ", "let ", "open ", "give ", "ask ", "remember ", "trust ")):
        score += 1.0
    return score


def _negative_score(text: str) -> float:
    words = set(_tokenize(text))
    return float(len(words.intersection(_NEGATIVE_TERMS))) * 0.8


def _classify_role(text: str) -> str:
    question = _question_score(text)
    advice = _advice_score(text)
    hope = _hope_score(text)
    negative = _negative_score(text)
    if question >= 2.0:
        return "question"
    if advice >= 1.5:
        return "advice"
    if hope >= 1.2 and negative < 1.0:
        return "hope"
    if negative >= 1.2:
        return "problem"
    return "insight"


def _motif_candidates_from_text(text: str, theme_terms: set[str]) -> set[str]:
    words = [word for word in _tokenize(text) if len(word) >= 4 and word not in _STOPWORDS and word not in theme_terms]
    motifs = {word for word in words if word in _MOTIF_REQUIRED_TERMS and word not in _GENERIC_MOTIFS}
    for index in range(len(words) - 1):
        left = words[index]
        right = words[index + 1]
        if left == right:
            continue
        if left in _PRACTICAL_TERMS or right in _PRACTICAL_TERMS or left in _HOPE_TERMS or right in _HOPE_TERMS:
            motifs.add(f"{left} {right}")
    return motifs


def _motif_popularity(db_path: Path, motif: str) -> tuple[int, int]:
    pattern = f"%{motif.lower()}%"
    with sqlite3.connect(db_path) as conn:
        mentions, feeds = conn.execute(
            """
            select count(*), count(distinct feed)
            from segments
            where kind = 'content' and lower(text) like ?
            """,
            (pattern,),
        ).fetchone()
    return int(mentions or 0), int(feeds or 0)


def _discover_motifs(db_path: Path, theme: str, results: list[dict], limit: int = 6) -> list[dict]:
    theme_terms = _theme_terms(theme)
    counts: Counter[str] = Counter()
    feed_spread: defaultdict[str, set[str]] = defaultdict(set)
    for result in results[: min(len(results), 80)]:
        text = str(result.get("text") or result.get("snippet") or "")
        feed = str(result.get("feed") or "")
        weight = max(1.0, float(result.get("score") or 0.0) * 0.12)
        for motif in _motif_candidates_from_text(text, theme_terms):
            counts[motif] += weight
            if feed:
                feed_spread[motif].add(feed)

    motifs: list[dict] = []
    for motif, local_score in counts.most_common(24):
        motif_words = set(motif.split())
        if motif in _GENERIC_MOTIFS:
            continue
        if " " not in motif and not motif_words.intersection(_MOTIF_REQUIRED_TERMS):
            continue
        if len(feed_spread[motif]) < 2:
            continue
        mentions, feeds = _motif_popularity(db_path, motif)
        if mentions < 3 or feeds < 2:
            continue
        practicality = 1.0 if any(word in _PRACTICAL_TERMS for word in motif.split()) else 0.0
        hope = 0.7 if any(word in _HOPE_TERMS for word in motif.split()) else 0.0
        motifs.append(
            {
                "term": motif,
                "score": round(local_score + feeds * 0.8 + min(mentions, 12) * 0.18 + practicality + hope, 3),
                "mentions": mentions,
                "feeds": feeds,
            }
        )
    motifs.sort(key=lambda item: float(item["score"]), reverse=True)
    return motifs[:limit]


def _bridge_terms(theme: str, motifs: list[dict]) -> list[str]:
    lowered_theme = str(theme or "").lower()
    found: list[str] = []
    for key, bridge_terms in _BRIDGE_MOTIFS.items():
        if key in lowered_theme or any(key in str(item.get("term") or "") for item in motifs):
            for term in bridge_terms:
                if term not in found:
                    found.append(term)
    return found[:4]


def _fts_query_term(motif: str) -> str:
    words = [word for word in re.findall(r"[a-z0-9]+", str(motif or "").lower()) if word]
    if not words:
        return ""
    if len(words) == 1:
        return words[0]
    phrase = " ".join(words)
    return f"\"{phrase}\""


def _query_fulltext_segments(db_path: Path, motif: str, limit: int = 80) -> list[dict]:
    query = _fts_query_term(motif)
    if not query:
        return []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            select
                s.feed,
                s.episode_slug,
                s.episode_title,
                s.episode_date,
                s.start_sec,
                s.end_sec,
                s.text,
                s.kind,
                s.kind_conf,
                s.theme,
                s.answer,
                bm25(segments_fts) as fts_rank
            from segments_fts
            join segments s on segments_fts.rowid = s.id
            where segments_fts match ?
              and s.kind = 'content'
            order by fts_rank
            limit ?
            """,
            (query, int(limit)),
        ).fetchall()
    out: list[dict] = []
    for row in rows:
        rank = float(row["fts_rank"] or 0.0)
        out.append(
            {
                "feed": row["feed"],
                "episode_slug": row["episode_slug"],
                "episode_title": row["episode_title"],
                "episode_date": row["episode_date"],
                "start_sec": float(row["start_sec"] or 0.0),
                "end_sec": float(row["end_sec"] or 0.0),
                "text": row["text"],
                "score": max(0.5, 7.5 - max(0.0, rank)),
                "share_path": _clip_share_path(row["feed"], row["episode_slug"], float(row["start_sec"] or 0.0)),
                "seed": f"fts:{motif}",
            }
        )
    return out


def _merge_seed_results(primary_results: list[dict], motif_results: list[dict]) -> list[dict]:
    merged: list[dict] = []
    seen: set[tuple[str, str, int, str]] = set()
    for result in [*primary_results, *motif_results]:
        key = (
            str(result.get("feed") or ""),
            str(result.get("episode_slug") or ""),
            int(float(result.get("start_sec") or 0.0) * 2),
            str(result.get("seed") or "seed"),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(result)
    return merged


def _snippet_score(theme_terms: set[str], text: str, dur: float, base_score: float) -> float:
    lowered = (text or "").lower()
    words = re.findall(r"[a-z0-9']+", lowered)
    word_count = len(words)
    sentence_count = max(1, len([part for part in re.split(r"(?<=[.!?])\s+", lowered) if part.strip()]))
    term_hits = sum(1 for term in theme_terms if term in lowered)
    duration_center = 4.2
    duration_bonus = max(0.0, 2.4 - abs(dur - duration_center) * 0.55)
    punctuation_bonus = 1.0 if sentence_count == 1 and lowered.rstrip().endswith(("?", "!", ".")) else 0.0
    filler_penalty = sum(0.5 for filler in _FILLER_PATTERNS if filler in lowered)
    sentence_bonus = 2.2 if sentence_count == 1 else max(-2.0, 0.5 - (sentence_count - 1) * 1.2)
    brevity_bonus = 1.8 if 6 <= word_count <= 18 else (0.6 if word_count <= 22 else -1.0)
    clause_penalty = max(0, lowered.count(",") - 1) * 0.4 + lowered.count(";") * 0.6 + lowered.count(":") * 0.4
    text_len = len(lowered)
    length_bonus = 0.9 if 25 <= text_len <= 110 else (-0.6 if text_len > 145 else 0.0)
    lead_bonus = 0.8 if lowered.startswith(("god ", "you ", "when ", "if ", "stop ", "start ", "dont ", "don't ")) else 0.0
    return (
        base_score * 0.15
        + term_hits * 2.8
        + duration_bonus
        + punctuation_bonus
        + sentence_bonus
        + brevity_bonus
        + length_bonus
        + lead_bonus
        - filler_penalty
        - clause_penalty
    )


def _window_to_snippets(
    transcript_path: Path,
    start: float,
    end: float,
    theme_terms: set[str],
    base_score: float,
    min_duration: float,
    max_duration: float,
) -> list[dict]:
    cues = _read_cues(transcript_path)
    if not cues:
        return []
    overlapping = [cue for cue in cues if cue["end"] > start and cue["start"] < end]
    snippets: list[dict] = []
    bucket: list[dict] = []
    bucket_words = 0

    def flush() -> None:
        nonlocal bucket, bucket_words
        if not bucket:
            return
        s = max(start, bucket[0]["start"])
        e = min(end, bucket[-1]["end"])
        dur = e - s
        text = " ".join(item["text"] for item in bucket).strip()
        if dur >= min_duration and dur <= max_duration and text:
            snippets.append(
                {
                    "start_sec": s,
                    "end_sec": e,
                    "duration_sec": dur,
                    "snippet": text,
                    "score": _snippet_score(theme_terms, text, dur, base_score),
                }
            )
        bucket = []
        bucket_words = 0

    for cue in overlapping:
        if bucket and cue["start"] - bucket[-1]["end"] > 0.85:
            flush()
        bucket.append(cue)
        bucket_words += len(re.findall(r"[a-z0-9']+", cue["text"].lower()))
        bucket_dur = bucket[-1]["end"] - bucket[0]["start"]
        end_punct = bool(re.search(r"[.!?][\"']?$", cue["text"].strip()))
        if bucket_dur >= max_duration or bucket_words >= 18 or (end_punct and bucket_dur >= min_duration) or (bucket_dur >= min_duration and bucket_words >= 14):
            flush()

    flush()
    return snippets


def _clip_motifs(text: str, discovered_motifs: list[dict], theme_terms: set[str]) -> list[str]:
    lowered = (text or "").lower()
    matched = [motif["term"] for motif in discovered_motifs if motif["term"] in lowered]
    if matched:
        return matched[:2]
    fallback = [word for word in _tokenize(text) if len(word) >= 4 and word not in _STOPWORDS and word not in theme_terms]
    preferred = [word for word in fallback if word in _PRACTICAL_TERMS or word in _HOPE_TERMS or word in _ADVICE_TERMS]
    return preferred[:2] or fallback[:2]


def _candidate_bonus(text: str, motifs: list[str]) -> float:
    return (
        _question_score(text)
        + _practicality_score(text)
        + _hope_score(text)
        + _advice_score(text)
        + len(motifs) * 0.8
    )


def _select_unique_feed_clips(
    candidates: list[dict],
    limit: int,
    min_clips: int,
    min_duration: float,
    max_duration: float,
    max_total: float,
    max_per_feed: int,
    max_per_episode: int,
    rejected: dict[str, int],
) -> list[dict]:
    feed_counts: dict[str, int] = {}
    episode_counts: dict[str, int] = {}
    seen_starts: set[tuple[str, str, int]] = set()
    selected: list[dict] = []
    total_so_far = 0.0

    question_candidates = [clip for clip in candidates if clip.get("role") == "question"]
    allow_question_role = True
    if question_candidates:
        opener = question_candidates[0]
        selected.append(opener)
        feed_counts[opener["feed"]] = 1
        episode_counts[opener["episode_slug"]] = 1
        seen_starts.add((opener["feed"], opener["episode_slug"], int(opener["start_sec"] * 2)))
        total_so_far += float(opener["duration_sec"])
        allow_question_role = False

    primary_pass = [clip for clip in candidates if allow_question_role or clip.get("role") != "question"]
    secondary_pass = [clip for clip in candidates if clip.get("role") == "question"] if not allow_question_role else []

    for clip in [*primary_pass, *secondary_pass]:
        feed = str(clip.get("feed") or "")
        episode = str(clip.get("episode_slug") or "")
        key = (feed, episode, int(float(clip.get("start_sec") or 0.0) * 2))
        if key in seen_starts:
            rejected["duplicate_clip"] += 1
            continue
        if feed_counts.get(feed, 0) >= max(1, max_per_feed):
            rejected["duplicate_feed"] += 1
            continue
        if episode_counts.get(episode, 0) >= max(1, max_per_episode):
            rejected["duplicate_episode"] += 1
            continue
        dur = float(clip.get("duration_sec") or 0.0)
        if dur < min_duration or dur > max_duration:
            rejected["duration"] += 1
            continue
        if total_so_far + dur > max_total and len(selected) >= min_clips:
            rejected["max_total"] += 1
            continue
        selected.append(clip)
        seen_starts.add(key)
        feed_counts[feed] = feed_counts.get(feed, 0) + 1
        episode_counts[episode] = episode_counts.get(episode, 0) + 1
        total_so_far += dur
        if len(selected) >= limit:
            break
    return selected


def _sequence_selected_clips(clips: list[dict]) -> list[dict]:
    role_order = {"question": 0, "problem": 1, "insight": 2, "advice": 3, "hope": 4}
    ordered = sorted(
        clips,
        key=lambda clip: (
            role_order.get(str(clip.get("role") or "insight"), 2),
            -float(clip.get("score") or 0.0),
        ),
    )
    return ordered


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Search for short sermon thought-bites for vertical shorts.")
    p.add_argument("--theme", required=True, help="Search query (e.g. forgiveness, prayer).")
    p.add_argument("--env", default="", help="Cache env (default: from .vodcasts-env).")
    p.add_argument("--cache", default="", help="Cache dir override.")
    p.add_argument("--limit", type=int, default=10, help="Target clips (default: 10).")
    p.add_argument("--min-clips", type=int, default=8, help="Minimum clips required (default: 8).")
    p.add_argument("--candidates", type=int, default=520, help="FTS candidates for rerank (default: 520).")
    p.add_argument("--include-noncontent", action="store_true", help="Allow intro/ad/outro segments.")
    p.add_argument("--output", "-o", default="", help="Write JSON to file (default: stdout).")
    p.add_argument("--exclude-used", default="", help="Path to used-clips.json to exclude.")
    p.add_argument("--min-duration", type=float, default=2.0, help="Minimum snippet seconds (default: 2.0).")
    p.add_argument("--max-duration", type=float, default=6.5, help="Max snippet seconds (default: 6.5).")
    p.add_argument("--max-total-duration", type=float, default=58.0, help="Max total seconds across all snippets (default: 58).")
    p.add_argument("--feeds", default="", help="Comma-separated feed slugs to restrict (e.g. church-of-the-highlands-weekend-video).")
    p.add_argument("--max-per-feed", type=int, default=1, help="Maximum snippets per feed (default: 1).")
    p.add_argument("--max-per-episode", type=int, default=1, help="Maximum snippets per episode (default: 1).")
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

    seed_results = payload.get("results") or []
    motifs = _discover_motifs(db_path, args.theme, seed_results, limit=6)
    bridge_terms = _bridge_terms(args.theme, motifs)
    motif_results: list[dict] = []
    for motif in motifs[:4]:
        motif_results.extend(_query_fulltext_segments(db_path, motif["term"], limit=60))
    for term in bridge_terms:
        motif_results.extend(_query_fulltext_segments(db_path, term, limit=40))

    results = _merge_seed_results(seed_results, motif_results)
    used_ids = load_used_clips(Path(args.exclude_used)) if args.exclude_used else set()
    min_dur = float(args.min_duration)
    max_dur = float(args.max_duration)
    max_total = float(args.max_total_duration or 999)
    allowed_feeds = {f.strip() for f in (args.feeds or "").split(",") if f.strip()}
    require_video = not bool(args.allow_audio)
    require_transcript = not bool(args.allow_missing_transcript)
    theme_terms = _theme_terms(args.theme)

    candidates = []
    rejected = {
        "duplicate_clip": 0,
        "duplicate_episode": 0,
        "duplicate_feed": 0,
        "used_clip": 0,
        "duration": 0,
        "max_total": 0,
        "not_renderable": 0,
        "no_snippets": 0,
    }
    renderability_cache: dict[tuple[str, str], bool] = {}
    transcript_cache: dict[tuple[str, str], Path | None] = {}
    for result in results:
        feed = str(result.get("feed") or "")
        if not feed:
            continue
        if allowed_feeds and feed not in allowed_feeds:
            continue
        ep_slug = str(result.get("episode_slug") or "")
        render_key = (feed, ep_slug)
        if render_key not in renderability_cache:
            renderability_cache[render_key] = clip_has_render_requirements(
                cache_dir=cache_dir,
                transcripts_root=transcripts_root,
                feed_slug=feed,
                episode_slug=ep_slug,
                require_video=require_video,
                require_transcript=require_transcript,
            )
            transcript_cache[render_key] = None
            if renderability_cache[render_key]:
                transcript_path = transcripts_root / feed / f"{ep_slug}.vtt"
                if not transcript_path.exists():
                    transcript_path = transcripts_root / feed / f"{ep_slug}.srt"
                transcript_cache[render_key] = transcript_path if transcript_path.exists() else None
        if not renderability_cache.get(render_key):
            rejected["not_renderable"] += 1
            continue
        transcript_path = transcript_cache.get(render_key)
        if transcript_path is None:
            rejected["not_renderable"] += 1
            continue

        start = float(result.get("start_sec") or 0.0)
        end = float(result.get("end_sec") or start)
        snippets = _window_to_snippets(
            transcript_path=transcript_path,
            start=start,
            end=end,
            theme_terms=theme_terms,
            base_score=float(result.get("score") or 0.0),
            min_duration=min_dur,
            max_duration=max_dur,
        )
        if not snippets:
            rejected["no_snippets"] += 1
            continue
        for snippet in snippets:
            cid = clip_id(feed, ep_slug, float(snippet["start_sec"]))
            if cid in used_ids:
                rejected["used_clip"] += 1
                continue
            motifs_for_clip = _clip_motifs(str(snippet["snippet"] or ""), motifs, theme_terms)
            role = _classify_role(str(snippet["snippet"] or ""))
            score = float(snippet["score"]) + _candidate_bonus(str(snippet["snippet"] or ""), motifs_for_clip)
            candidates.append(
                {
                    "feed": feed,
                    "episode_slug": ep_slug,
                    "episode_title": result.get("episode_title"),
                    "episode_date": result.get("episode_date"),
                    "start_sec": float(snippet["start_sec"]),
                    "end_sec": float(snippet["end_sec"]),
                    "duration_sec": float(snippet["duration_sec"]),
                    "snippet": snippet["snippet"],
                    "score": score,
                    "role": role,
                    "motifs": motifs_for_clip,
                    "seed": result.get("seed") or "answer-engine",
                    "share_path": result.get("share_path") or _clip_share_path(feed, ep_slug, float(snippet["start_sec"])),
                }
            )

    candidates.sort(
        key=lambda item: (
            -float(item.get("score") or 0.0),
            0 if item.get("role") == "question" else 1,
            str(item.get("episode_date") or ""),
        )
    )

    selected = _select_unique_feed_clips(
        candidates=candidates,
        limit=max(int(args.limit), int(args.min_clips)),
        min_clips=int(args.min_clips),
        min_duration=min_dur,
        max_duration=max_dur,
        max_total=max_total,
        max_per_feed=int(args.max_per_feed),
        max_per_episode=int(args.max_per_episode),
        rejected=rejected,
    )
    clips = _sequence_selected_clips(selected)

    if len(clips) < args.min_clips:
        print(
            f"[search_shorts] Only {len(clips)} clips found; need at least {args.min_clips}. "
            "Try a broader query or relax duration filters.",
            file=sys.stderr,
        )
        sys.exit(3)

    total_dur = sum(float(c["duration_sec"]) for c in clips)
    out = {
        "query": args.theme,
        "clips": clips,
        "total_duration_sec": total_dur,
        "motifs": motifs,
        "bridge_terms": bridge_terms,
        "filters": {
            "require_video": require_video,
            "require_transcript": require_transcript,
            "min_duration": min_dur,
            "max_duration": max_dur,
            "max_total_duration": max_total,
            "max_per_feed": int(args.max_per_feed),
            "max_per_episode": int(args.max_per_episode),
        },
        "rejected_counts": rejected,
    }
    out_json = json.dumps(out, ensure_ascii=False, indent=2)

    if args.output:
        Path(args.output).write_text(out_json, encoding="utf-8")
        print(f"[search_shorts] wrote {len(clips)} clips to {args.output}", file=sys.stderr)
    else:
        print(out_json)


if __name__ == "__main__":
    main()
