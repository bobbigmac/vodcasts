#!/usr/bin/env python3
"""
Report which feeds are missing show-filter files and summarize show bucketing.

Writes a Markdown report (intended for quick human review) that includes:
- Feeds missing `feeds/shows/<slug>.json` + title pattern hints from cached XML.
- Feeds with show filters + resulting show episode counts (from cached XML).
"""
from __future__ import annotations

import argparse
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.feed_manifest import parse_feed_for_manifest
from scripts.shared import VODCASTS_ROOT, read_json
from scripts.show_filters import build_shows_for_feed
from scripts.sources import Source, load_sources_config


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Report missing show filters and summarize show bucketing.")
    p.add_argument("--feeds", default=str(VODCASTS_ROOT / "feeds" / "church.md"), help="Feeds config (.md).")
    p.add_argument("--cache", default=str(VODCASTS_ROOT / "cache" / "church"), help="Cache directory (env root).")
    p.add_argument("--out", default=str(VODCASTS_ROOT / "tmp" / "show_filters_report.md"), help="Output report path.")
    p.add_argument("--limit", type=int, default=160, help="Max episode titles per feed to analyze (default 160).")
    p.add_argument("--max-feeds", type=int, default=0, help="Limit feeds processed (0 = all).")
    p.add_argument(
        "--max-missing",
        type=int,
        default=0,
        help="Limit missing feeds included in the report (0 = all). When combined with --only-missing, stops scanning after this many missing feeds.",
    )
    p.add_argument(
        "--feed-id",
        action="append",
        default=[],
        help="Only process this feed id (repeatable).",
    )
    p.add_argument("--only-missing", action="store_true", help="Only list feeds missing show filter files.")
    p.add_argument("--only-with-filters", action="store_true", help="Only list feeds that already have show filters.")
    return p.parse_args()


def _md_escape(s: str) -> str:
    return str(s or "").replace("\n", " ").replace("\r", " ").strip()


def _extract_prefixes(titles: list[str]) -> list[tuple[str, int]]:
    prefixes: Counter[str] = Counter()
    for t in titles:
        t = (t or "").strip()
        if not t:
            continue
        for sep in (":", " | ", " - ", " – "):
            if sep in t:
                p = t.split(sep, 1)[0].strip()
                if 2 <= len(p) <= 70:
                    prefixes[p] += 1
                break
    return prefixes.most_common(12)


def _extract_pipe_series(titles: list[str]) -> list[tuple[str, int]]:
    """Prefix candidates for 'Series | Episode' style titles."""
    ct: Counter[str] = Counter()
    for t in titles:
        t = (t or "").strip()
        if " | " not in t:
            continue
        p = t.split(" | ", 1)[0].strip()
        if 2 <= len(p) <= 70:
            ct[p] += 1
    return ct.most_common(12)


def _extract_code_prefixes(titles: list[str]) -> list[tuple[str, int]]:
    """e.g. MATT123 - ... => MATT"""
    ct: Counter[str] = Counter()
    rx = re.compile(r"^([A-Z]{2,7})\d{2,4}\b")
    for t in titles:
        t = (t or "").strip()
        m = rx.match(t)
        if not m:
            continue
        ct[m.group(1)] += 1
    return ct.most_common(12)


def _extract_trailing_parens(titles: list[str]) -> list[tuple[str, int]]:
    """e.g. ... (Divine Providence)"""
    ct: Counter[str] = Counter()
    rx = re.compile(r"\(([^()]{2,60})\)\s*$")
    for t in titles:
        t = (t or "").strip()
        m = rx.search(t)
        if not m:
            continue
        v = m.group(1).strip()
        if v:
            ct[v] += 1
    return ct.most_common(12)


def _extract_trailing_speakers(titles: list[str]) -> list[tuple[str, int]]:
    """Heuristic: last ' | ' chunk if it looks like a speaker."""
    ct: Counter[str] = Counter()
    for t in titles:
        t = (t or "").strip()
        if " | " not in t:
            continue
        last = t.rsplit(" | ", 1)[-1].strip()
        if not last:
            continue
        low = last.lower()
        if low.startswith("pastor ") or low.startswith("fr. ") or low.startswith("dr. "):
            if 5 <= len(last) <= 52:
                ct[last] += 1
    return ct.most_common(10)


@dataclass(frozen=True)
class FeedScan:
    source: Source
    cached_xml: Path | None
    episode_count: int
    sample_titles: list[str]
    prefixes: list[tuple[str, int]]
    pipe_series: list[tuple[str, int]]
    code_prefixes: list[tuple[str, int]]
    trailing_parens: list[tuple[str, int]]
    trailing_speakers: list[tuple[str, int]]
    parse_error: str | None = None


def _cache_feeds_dir(cache_root: Path) -> Path:
    # accept either `cache/<env>` or `cache/<env>/feeds`
    if (cache_root / "feeds").is_dir():
        return cache_root / "feeds"
    return cache_root


def _scan_feed(source: Source, *, cache_feeds_dir: Path, limit: int) -> FeedScan:
    cached = cache_feeds_dir / f"{source.id}.xml"
    if not cached.exists():
        return FeedScan(
            source=source,
            cached_xml=None,
            episode_count=0,
            sample_titles=[],
            prefixes=[],
            pipe_series=[],
            code_prefixes=[],
            trailing_parens=[],
            trailing_speakers=[],
            parse_error="no cached XML",
        )

    try:
        xml = cached.read_text(encoding="utf-8", errors="replace")
        _, _, episodes, _ = parse_feed_for_manifest(xml, source_id=source.id, source_title=source.title)
        titles = [str(ep.get("title") or "").strip() for ep in episodes[: max(0, int(limit))] if str(ep.get("title") or "").strip()]
        return FeedScan(
            source=source,
            cached_xml=cached,
            episode_count=len(episodes),
            sample_titles=titles[:20],
            prefixes=_extract_prefixes(titles),
            pipe_series=_extract_pipe_series(titles),
            code_prefixes=_extract_code_prefixes(titles),
            trailing_parens=_extract_trailing_parens(titles),
            trailing_speakers=_extract_trailing_speakers(titles),
        )
    except Exception as e:
        return FeedScan(
            source=source,
            cached_xml=cached,
            episode_count=0,
            sample_titles=[],
            prefixes=[],
            pipe_series=[],
            code_prefixes=[],
            trailing_parens=[],
            trailing_speakers=[],
            parse_error=f"{type(e).__name__}: {e}",
        )


def _load_show_filters_for_feed(feed_id: str) -> dict[str, Any] | None:
    p = VODCASTS_ROOT / "feeds" / "shows" / f"{feed_id}.json"
    if not p.exists():
        return None
    try:
        doc = read_json(p)
        return doc if isinstance(doc, dict) else None
    except Exception:
        return None


def _show_filter_summary_lines(shows: list[dict[str, Any]]) -> list[str]:
    out = []
    for s in shows or []:
        if not isinstance(s, dict):
            continue
        title = str(s.get("title") or s.get("id") or "").strip()
        if not title:
            continue
        eps = s.get("episodes") or []
        n = len(eps) if isinstance(eps, list) else 0
        is_left = bool(s.get("isLeftovers"))
        sample = ""
        if isinstance(eps, list) and eps:
            t0 = str(eps[0].get("title") or "").strip()
            if t0:
                sample = f" — e.g. {t0[:90]}{'…' if len(t0) > 90 else ''}"
        out.append(f"- {'(leftovers) ' if is_left else ''}{_md_escape(title)} — {n} eps{sample}")
    return out


def main() -> None:
    args = _parse_args()
    feeds_path = Path(args.feeds)
    cache_root = Path(args.cache)
    out_path = Path(args.out)
    limit = max(0, int(args.limit))
    max_feeds = max(0, int(args.max_feeds))
    max_missing = max(0, int(args.max_missing))
    wanted_feed_ids = {str(x).strip() for x in (args.feed_id or []) if str(x).strip()}

    cfg = load_sources_config(feeds_path)
    sources = cfg.sources[:]
    if wanted_feed_ids:
        sources = [s for s in sources if s.id in wanted_feed_ids]
    if max_feeds:
        sources = sources[:max_feeds]

    cache_feeds_dir = _cache_feeds_dir(cache_root)
    shows_dir = VODCASTS_ROOT / "feeds" / "shows"

    missing_filters: list[FeedScan] = []
    with_filter_sources: list[Source] = []
    parse_errors: list[FeedScan] = []
    processed_sources = 0
    with_filters_processed = 0

    for s in sources:
        processed_sources += 1
        has_filters = (shows_dir / f"{s.id}.json").exists()
        if has_filters:
            with_filters_processed += 1
        if args.only_missing and has_filters:
            continue
        if args.only_with_filters and (not has_filters):
            continue
        if has_filters:
            with_filter_sources.append(s)
            continue
        scan = _scan_feed(s, cache_feeds_dir=cache_feeds_dir, limit=limit)
        if scan.parse_error:
            parse_errors.append(scan)
        else:
            missing_filters.append(scan)
        if args.only_missing and max_missing and (len(missing_filters) + len(parse_errors) >= max_missing):
            break

    missing_filters.sort(key=lambda x: (-x.episode_count, x.source.id))
    with_filter_sources.sort(key=lambda x: x.id)
    if max_missing and missing_filters:
        missing_filters = missing_filters[:max_missing]

    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.append("# Show filters report")
    lines.append("")
    lines.append(f"- Feeds: `{feeds_path}`")
    lines.append(f"- Cache: `{cache_root}`")
    lines.append(f"- Title scan limit: `{limit}`")
    lines.append("")
    lines.append(f"- Total feeds in selection: **{len(sources)}**")
    lines.append(f"- Feeds processed: **{processed_sources}**")
    lines.append(f"- With show filters: **{with_filters_processed}**")
    lines.append(f"- Missing show filters: **{len(missing_filters)}**")
    if parse_errors:
        lines.append(f"- Parse/missing-cache errors: **{len(parse_errors)}**")
    if wanted_feed_ids:
        lines.append(f"- Feed id filter: `{', '.join(sorted(wanted_feed_ids))}`")
    lines.append("")

    if not args.only_with_filters:
        lines.append("## Missing show filters")
        lines.append("")
        for scan in missing_filters:
            s = scan.source
            lines.append(f"### `{s.id}` — { _md_escape(s.title) }")
            lines.append("")
            lines.append(f"- Category: `{_md_escape(s.category)}`")
            lines.append(f"- Cached episodes: **{scan.episode_count}**")
            lines.append(f"- Cached XML: `{scan.cached_xml}`")
            lines.append("")

            if scan.sample_titles:
                lines.append("Sample titles:")
                for t in scan.sample_titles[:8]:
                    lines.append(f"- { _md_escape(t[:120]) }{'…' if len(t) > 120 else ''}")
                lines.append("")

            if scan.code_prefixes:
                lines.append("Code prefixes (suggest `title_regex: ^CODE\\d+`):")
                for p, c in scan.code_prefixes[:8]:
                    lines.append(f"- `{p}` — {c}")
                lines.append("")

            if scan.pipe_series:
                lines.append("Series prefixes via `Series | Episode`:")
                for p, c in scan.pipe_series[:8]:
                    lines.append(f"- `{_md_escape(p)}` — {c}")
                lines.append("")

            if scan.trailing_parens:
                lines.append("Trailing `(Category)` suffixes:")
                for p, c in scan.trailing_parens[:8]:
                    lines.append(f"- `{_md_escape(p)}` — {c}")
                lines.append("")

            if scan.trailing_speakers:
                lines.append("Trailing speakers (suggest `title_contains`/`title_suffix`):")
                for p, c in scan.trailing_speakers[:8]:
                    lines.append(f"- `{_md_escape(p)}` — {c}")
                lines.append("")

            if scan.prefixes:
                lines.append("General prefixes:")
                for p, c in scan.prefixes[:8]:
                    lines.append(f"- `{_md_escape(p)}` — {c}")
                lines.append("")

        if not missing_filters:
            lines.append("_None._")
            lines.append("")

    if not args.only_missing:
        lines.append("## Feeds with show filters")
        lines.append("")
        for s in with_filter_sources:
            doc = _load_show_filters_for_feed(s.id) or {}
            shows_cfg = doc.get("shows") if isinstance(doc.get("shows"), list) else []
            leftovers_title = str(doc.get("leftovers_title") or "").strip() or None
            leftovers_full = str(doc.get("leftovers_title_full") or "").strip() or None
            leftovers_desc = str(doc.get("leftovers_description") or "").strip() or None

            # Parse full episode list for accurate counts in this section.
            eps: list[dict[str, Any]] = []
            try:
                cached_xml = cache_feeds_dir / f"{s.id}.xml"
                if cached_xml.exists():
                    xml = cached_xml.read_text(encoding="utf-8", errors="replace")
                    _, _, eps, _ = parse_feed_for_manifest(xml, source_id=s.id, source_title=s.title)
            except Exception:
                eps = []

            shows_out = build_shows_for_feed(
                eps,
                shows_cfg,
                feed_id=s.id,
                feed_title=s.title or s.id,
                leftovers_title=leftovers_title,
                leftovers_title_full=leftovers_full,
                leftovers_description=leftovers_desc,
            )

            lines.append(f"### `{s.id}` — { _md_escape(s.title) }")
            lines.append("")
            lines.append(f"- Category: `{_md_escape(s.category)}`")
            lines.append(f"- Cached episodes: **{len(eps)}**")
            lines.append(f"- Filters file: `{shows_dir / f'{s.id}.json'}`")
            lines.append("")
            for ln in _show_filter_summary_lines(shows_out):
                lines.append(ln)
            lines.append("")

    if parse_errors:
        lines.append("## Parse/cache errors")
        lines.append("")
        for scan in parse_errors[:80]:
            s = scan.source
            lines.append(f"- `{s.id}` — {_md_escape(scan.parse_error or '')}")
        lines.append("")

    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"[report] wrote {out_path} ({len(lines)} lines)")


if __name__ == "__main__":
    main()
