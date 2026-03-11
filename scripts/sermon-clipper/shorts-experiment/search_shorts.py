"""Search for 10-25 second clips suitable for vertical shorts. Output JSON."""
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


def _theme_terms(theme: str) -> set[str]:
    return {term for term in re.findall(r"[a-z0-9']+", (theme or "").lower()) if len(term) > 2}


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


def _snippet_score(theme_terms: set[str], text: str, dur: float, base_score: float) -> float:
    lowered = (text or "").lower()
    term_hits = sum(1 for term in theme_terms if term in lowered)
    duration_center = 5.5
    duration_bonus = max(0.0, 2.0 - abs(dur - duration_center) * 0.35)
    punctuation_bonus = 0.8 if lowered.rstrip().endswith(("?", "!", ".")) else 0.0
    filler_penalty = sum(0.5 for filler in _FILLER_PATTERNS if filler in lowered)
    text_len = len(lowered)
    length_bonus = 1.0 if 35 <= text_len <= 130 else 0.0
    return base_score * 0.2 + term_hits * 2.5 + duration_bonus + punctuation_bonus + length_bonus - filler_penalty


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
        bucket.append(cue)
        bucket_words += len(re.findall(r"[a-z0-9']+", cue["text"].lower()))
        bucket_dur = bucket[-1]["end"] - bucket[0]["start"]
        end_punct = cue["text"].rstrip().endswith((".", "!", "?"))
        if bucket_dur >= max_duration or bucket_words >= 20 or (end_punct and bucket_dur >= min_duration):
            flush()

    flush()
    return snippets


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Search for short clips/snippets for vertical shorts.")
    p.add_argument("--theme", required=True, help="Search query (e.g. forgiveness, prayer).")
    p.add_argument("--env", default="", help="Cache env (default: from .vodcasts-env).")
    p.add_argument("--cache", default="", help="Cache dir override.")
    p.add_argument("--limit", type=int, default=8, help="Max clips (default: 8).")
    p.add_argument("--min-clips", type=int, default=6, help="Minimum clips required (default: 6).")
    p.add_argument("--candidates", type=int, default=400, help="FTS candidates for rerank (default: 400).")
    p.add_argument("--include-noncontent", action="store_true", help="Allow intro/ad/outro segments.")
    p.add_argument("--output", "-o", default="", help="Write JSON to file (default: stdout).")
    p.add_argument("--exclude-used", default="", help="Path to used-clips.json to exclude.")
    p.add_argument("--min-duration", type=float, default=2.5, help="Minimum snippet seconds (default: 2.5).")
    p.add_argument("--max-duration", type=float, default=8.5, help="Max snippet seconds (default: 8.5).")
    p.add_argument("--max-total-duration", type=float, default=52.0, help="Max total seconds across all snippets (default: 52).")
    p.add_argument("--feeds", default="", help="Comma-separated feed slugs to restrict (e.g. church-of-the-highlands-weekend-video).")
    p.add_argument("--max-per-feed", type=int, default=2, help="Maximum snippets per feed (default: 2).")
    p.add_argument("--max-per-episode", type=int, default=2, help="Maximum snippets per episode (default: 2).")
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

    results = payload.get("results") or []
    used_ids = load_used_clips(Path(args.exclude_used)) if args.exclude_used else set()
    min_dur = float(args.min_duration)
    max_dur = float(args.max_duration)
    max_total = float(args.max_total_duration or 999)
    allowed_feeds = {f.strip() for f in (args.feeds or "").split(",") if f.strip()}
    require_video = not bool(args.allow_audio)
    require_transcript = not bool(args.allow_missing_transcript)
    theme_terms = _theme_terms(args.theme)

    candidates = []
    feed_counts: dict[str, int] = {}
    episode_counts: dict[str, int] = {}
    rejected = {
        "duplicate_feed": 0,
        "used_clip": 0,
        "duration": 0,
        "not_renderable": 0,
        "no_snippets": 0,
    }
    for r in results:
        feed = r.get("feed")
        if allowed_feeds and feed not in allowed_feeds:
            continue
        ep_slug = r.get("episode_slug")
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
        transcript_path = default_transcripts_root() / str(feed or "") / f"{ep_slug}.vtt"
        if not transcript_path.exists():
            transcript_path = default_transcripts_root() / str(feed or "") / f"{ep_slug}.srt"
        if not transcript_path.exists():
            rejected["not_renderable"] += 1
            continue
        start = float(r.get("start_sec") or 0)
        end = float(r.get("end_sec") or start)
        snippets = _window_to_snippets(
            transcript_path=transcript_path,
            start=start,
            end=end,
            theme_terms=theme_terms,
            base_score=float(r.get("score") or 0),
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
            candidates.append(
                {
                    "feed": feed,
                    "episode_slug": ep_slug,
                    "episode_title": r.get("episode_title"),
                    "episode_date": r.get("episode_date"),
                    "start_sec": float(snippet["start_sec"]),
                    "end_sec": float(snippet["end_sec"]),
                    "duration_sec": float(snippet["duration_sec"]),
                    "snippet": snippet["snippet"],
                    "score": float(snippet["score"]),
                    "share_path": r.get("share_path"),
                }
            )

    candidates.sort(key=lambda item: float(item.get("score") or 0), reverse=True)

    clips = []
    seen_starts: set[tuple[str, str, int]] = set()
    total_so_far = 0.0
    for clip in candidates:
        feed = str(clip.get("feed") or "")
        episode = str(clip.get("episode_slug") or "")
        key = (feed, episode, int(float(clip.get("start_sec") or 0) * 2))
        if key in seen_starts:
            rejected["duplicate_feed"] += 1
            continue
        if feed_counts.get(feed, 0) >= max(1, int(args.max_per_feed)):
            rejected["duplicate_feed"] += 1
            continue
        if episode_counts.get(episode, 0) >= max(1, int(args.max_per_episode)):
            rejected["duplicate_feed"] += 1
            continue
        dur = float(clip.get("duration_sec") or 0)
        if dur < min_dur or dur > max_dur:
            rejected["duration"] += 1
            continue
        if total_so_far + dur > max_total and len(clips) >= args.min_clips:
            continue
        seen_starts.add(key)
        feed_counts[feed] = feed_counts.get(feed, 0) + 1
        episode_counts[episode] = episode_counts.get(episode, 0) + 1
        total_so_far += dur
        clips.append(clip)
        if len(clips) >= args.limit:
            break

    if len(clips) < args.min_clips:
        print(
            f"[search_shorts] Only {len(clips)} clips found; need at least {args.min_clips}. "
            "Try a broader query or relax duration filters.",
            file=sys.stderr,
        )
        sys.exit(3)

    total_dur = sum(c["duration_sec"] for c in clips)
    out = {
        "query": args.theme,
        "clips": clips,
        "total_duration_sec": total_dur,
        "filters": {
            "require_video": require_video,
            "require_transcript": require_transcript,
            "min_duration": min_dur,
            "max_duration": max_dur,
            "max_total_duration": max_total,
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
