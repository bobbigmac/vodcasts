#!/usr/bin/env python3
"""
Scan cached feed XML to extract episode titles for show-filter analysis.
Use before writing feeds/shows/<id>.json — derive filters from actual content.
"""
from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

from scripts.feed_manifest import parse_feed_for_manifest
from scripts.shared import VODCASTS_ROOT, read_json


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Scan cached feeds for episode title patterns.")
    p.add_argument("--feeds", default=str(VODCASTS_ROOT / "feeds" / "dev.md"), help="Feeds config.")
    p.add_argument("--cache", default=str(VODCASTS_ROOT / "cache" / "dev"), help="Cache directory.")
    p.add_argument("feed_id", nargs="?", help="Filter to this feed ID (omit to scan all).")
    p.add_argument("--limit", type=int, default=100, help="Max episodes per feed to scan (default 100).")
    p.add_argument("--patterns", action="store_true", help="Suggest title_contains / title_prefix patterns.")
    return p.parse_args()


def _extract_prefixes(titles: list[str], min_count: int = 2) -> list[tuple[str, int]]:
    """Return (prefix, count) for prefixes before ':', ' - ', ' | ' (min 2 chars)."""
    prefixes: Counter[str] = Counter()
    for t in titles:
        t = (t or "").strip()
        if not t:
            continue
        for sep in (":", " - ", " | ", " – "):
            if sep in t:
                p = t.split(sep)[0].strip()
                if len(p) >= min_count:
                    prefixes[p] += 1
                break
    return prefixes.most_common(20)


def _extract_substrings(titles: list[str], min_len: int = 4, min_count: int = 2) -> list[tuple[str, int]]:
    """Find recurring substrings (case-insensitive) that might be series names."""
    words: Counter[str] = Counter()
    for t in titles:
        t = (t or "").strip().lower()
        # Simple word tokens (skip numbers, very short)
        tokens = re.findall(r"[a-z]{3,}", re.sub(r"[^\w\s]", " ", t))
        for tkn in tokens:
            if len(tkn) >= min_len:
                words[tkn] += 1
    return [(w, c) for w, c in words.most_common(40) if c >= min_count]


def main() -> None:
    args = _parse_args()
    cache_dir = Path(args.cache)
    feeds_dir = Path(args.feeds).parent

    # Load feed IDs from config
    from scripts.sources import load_sources_config
    cfg = load_sources_config(Path(args.feeds))
    feed_ids = [s.id for s in cfg.sources]
    if args.feed_id:
        feed_ids = [f for f in feed_ids if f == args.feed_id]
        if not feed_ids:
            print(f"Feed '{args.feed_id}' not in config.")
            return

    for fid in feed_ids:
        cached = cache_dir / "feeds" / f"{fid}.xml"
        if not cached.exists():
            print(f"[{fid}] no cached XML — run update first")
            continue

        xml = cached.read_text(encoding="utf-8", errors="replace")
        _, _, episodes, _ = parse_feed_for_manifest(xml, source_id=fid, source_title=fid)
        titles = [ep.get("title") or "" for ep in episodes[: args.limit]]

        print(f"\n--- {fid} ({len(titles)} episodes) ---")
        for i, t in enumerate(titles[:20]):
            print(f"  {i+1}. {t[:80]}{'…' if len(t) > 80 else ''}")
        if len(titles) > 20:
            print(f"  ... and {len(titles) - 20} more")

        if args.patterns and titles:
            prefixes = _extract_prefixes(titles)
            if prefixes:
                print("\n  Prefix candidates (before : or -):")
                for p, c in prefixes[:10]:
                    print(f"    title_prefix: \"{p}\" ({c} eps)")
            subs = _extract_substrings(titles)
            if subs:
                print("\n  Recurring tokens:")
                for w, c in subs[:15]:
                    print(f"    title_contains: \"{w}\" ({c} eps)")


if __name__ == "__main__":
    main()
