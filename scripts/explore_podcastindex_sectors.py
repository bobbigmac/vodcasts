#!/usr/bin/env python3
"""Explore podcastindex_feeds.db for video-heavy sectors (non-church).
Outputs sector suggestions for SECTOR_SUGGESTIONS.md.

Usage:
  python scripts/explore_podcastindex_sectors.py [--limit N] [--min-pop N]
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "podcastindex-feeds" / "podcastindex_feeds.db"

# Exclude church/religion - we already have that
EXCLUDED_CATEGORIES = {"religion", "christianity", "spirituality", "buddhism", "hinduism"}
EXCLUDED_TERMS = [
    "sermon", "church", "bible", "christian", "pastor", "ministry", "worship",
    "gospel", "faith", "evangel", "baptist", "methodist", "catholic", "orthodox",
]

# Video enclosure URL patterns
VIDEO_PATTERNS = (".mp4", ".m4v", ".webm", ".mov", ".m3u8")


def is_video_enclosure(url: str) -> bool:
    if not url:
        return False
    u = url.lower()
    return any(p in u for p in VIDEO_PATTERNS)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=50000, help="Max rows to scan per query")
    parser.add_argument("--min-pop", type=int, default=3, help="Min popularityScore")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"DB not found: {DB_PATH}")
        return

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    base_where = (
        "dead = 0 and lastHttpStatus = 200 and episodeCount >= 5 "
        "and contentType like '%xml%' and url <> '' and popularityScore >= ?"
    )
    params = [args.min_pop]

    # 1. Category distribution (all feeds)
    print("=== Categories by feed count (excluding religion) ===\n")
    cur = conn.execute(
        """
        SELECT category1 as cat, count(*) as cnt
        FROM podcasts
        WHERE """ + base_where + """
        AND category1 IS NOT NULL AND trim(category1) != ''
        AND lower(trim(category1)) NOT IN ('religion', 'spirituality', 'christianity', 'buddhism', 'hinduism')
        GROUP BY lower(trim(category1))
        ORDER BY cnt DESC
        LIMIT 60
        """,
        params,
    )
    categories = []
    for row in cur.fetchall():
        cat = (row["cat"] or "").strip()
        cnt = row["cnt"]
        categories.append((cat, cnt))
        print(f"  {cnt:>6}  {cat}")

    # 2. Video feeds by category (newestEnclosureUrl has video ext)
    print("\n=== Video feeds by category (enclosure URL = video) ===\n")
    video_by_cat: dict[str, int] = {}
    # Use a subquery with limit for performance
    cur = conn.execute(
        f"""
        SELECT category1, category2, category3
        FROM (
            SELECT id, category1, category2, category3, newestEnclosureUrl
            FROM podcasts
            WHERE {base_where}
            AND newestEnclosureUrl IS NOT NULL AND newestEnclosureUrl != ''
            LIMIT {args.limit}
        )
        """,
        params,
    )
    for row in cur.fetchall():
        url = row[2] if len(row) > 2 else ""  # Actually we need newestEnclosureUrl
        # Fix: we need to select newestEnclosureUrl
        pass

    # Re-query with correct columns
    cur = conn.execute(
        f"""
        SELECT category1, category2, category3, newestEnclosureUrl
        FROM podcasts
        WHERE {base_where}
        AND newestEnclosureUrl IS NOT NULL AND newestEnclosureUrl != ''
        LIMIT {args.limit}
        """,
        params,
    )
    for row in cur.fetchall():
        c1 = (row[0] or "").strip().lower()
        c2 = (row[1] or "").strip().lower()
        c3 = (row[2] or "").strip().lower()
        url = row[3] or ""
        if not is_video_enclosure(url):
            continue
        # Skip religion
        if any(ex in c1 or ex in c2 or ex in c3 for ex in EXCLUDED_CATEGORIES):
            continue
        for c in [c1, c2, c3]:
            if c:
                video_by_cat[c] = video_by_cat.get(c, 0) + 1

    for cat, cnt in sorted(video_by_cat.items(), key=lambda x: -x[1])[:40]:
        print(f"  {cnt:>5}  {cat}")

    # 3. Sample high-value sectors: Education, Business, Technology, etc.
    print("\n=== Sample feeds by sector (video, 20+ episodes, pop>=5) ===\n")
    sectors = [
        ("Education", ["education", "courses", "learning", "university", "lecture", "ted"]),
        ("Business", ["business", "entrepreneur", "startup", "finance", "investing"]),
        ("Technology", ["technology", "tech", "software", "coding", "developer"]),
        ("Health & Fitness", ["health", "fitness", "wellness", "nutrition", "mental health"]),
        ("Comedy", ["comedy", "humor"]),
        ("TV & Film", ["tv", "film", "movies", "entertainment"]),
        ("News", ["news", "politics", "current affairs"]),
        ("Science", ["science", "physics", "biology", "research"]),
        ("Crafts & Hobbies", ["hobbies", "crafts", "diy", "how-to"]),
        ("Kids & Family", ["kids", "family", "parenting"]),
        ("Sports", ["sports", "sport"]),
        ("Music", ["music", "musician"]),
    ]

    sector_samples: dict[str, list[dict]] = {}
    for sector_name, terms in sectors:
        term_sql = " or ".join(
            "lower(coalesce(title,'')||' '||coalesce(description,'')||' '||coalesce(category1,'')||coalesce(category2,'')||coalesce(category3,'')) like ?"
            for _ in terms
        )
        term_params = [f"%{t}%" for t in terms] + params
        cur = conn.execute(
            f"""
            SELECT id, url, title, description, episodeCount, popularityScore, category1, category2, category3, newestEnclosureUrl
            FROM podcasts
            WHERE {base_where}
            AND episodeCount >= 20
            AND ({term_sql})
            AND newestEnclosureUrl IS NOT NULL AND newestEnclosureUrl != ''
            ORDER BY popularityScore DESC, episodeCount DESC
            LIMIT 30
            """,
            term_params,
        )
        rows = cur.fetchall()
        # Filter to video enclosures only
        video_rows = [r for r in rows if is_video_enclosure(r["newestEnclosureUrl"])]
        # Exclude church
        video_rows = [
            r
            for r in video_rows
            if not any(
                ex in (r["title"] or "").lower()
                or ex in ((r["description"] or "")[:500]).lower()
                for ex in EXCLUDED_TERMS
            )
        ]
        sector_samples[sector_name] = [
            {
                "title": r["title"],
                "url": r["url"],
                "episodeCount": r["episodeCount"],
                "popularityScore": r["popularityScore"],
                "categories": ", ".join(
                    c for c in [r["category1"], r["category2"], r["category3"]] if c
                ),
            }
            for r in video_rows[:15]
        ]

    for sector_name, samples in sector_samples.items():
        print(f"\n--- {sector_name} ({len(samples)} video feeds) ---")
        for s in samples[:8]:
            print(f"  {s['episodeCount']:>4} eps  pop={s['popularityScore']}  {s['title'][:60]}")

    conn.close()

    # Write JSON for SECTOR_SUGGESTIONS.md authoring
    import json
    out_path = ROOT / "tmp" / "sector_exploration.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "categories": categories,
                "video_by_category": dict(sorted(video_by_cat.items(), key=lambda x: -x[1])),
                "sector_samples": {
                    k: v
                    for k, v in sector_samples.items()
                    if v
                },
            },
            f,
            indent=2,
        )
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
