#!/usr/bin/env python3
"""Quick sector exploration of podcastindex_feeds.db (no API).
Run: python scripts/explore_sectors_quick.py
"""
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "podcastindex-feeds" / "podcastindex_feeds.db"


def main():
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    base = "dead=0 AND lastHttpStatus=200 AND episodeCount>=5 AND popularityScore>=5"
    exclude_cat = "lower(trim(category1)) NOT IN ('religion','spirituality','christianity')"

    # Video by category
    t0 = time.time()
    cur = conn.execute(f"""
        SELECT category1, count(*) FROM podcasts
        WHERE {base} AND newestEnclosureUrl IS NOT NULL AND newestEnclosureUrl != ''
        AND (lower(newestEnclosureUrl) LIKE '%.mp4%' OR lower(newestEnclosureUrl) LIKE '%.m4v%'
             OR lower(newestEnclosureUrl) LIKE '%.webm%' OR lower(newestEnclosureUrl) LIKE '%.mov%'
             OR lower(newestEnclosureUrl) LIKE '%.m3u8%')
        AND category1 IS NOT NULL AND trim(category1) != '' AND {exclude_cat}
        GROUP BY lower(trim(category1)) ORDER BY count(*) DESC LIMIT 50
    """)
    video_cats = cur.fetchall()
    print("Video feeds by category (pop>=5):", round(time.time() - t0, 1), "sec")
    for c, n in video_cats:
        print(f"  {n:>5}  {c}")

    # Sample education video feeds
    cur = conn.execute(f"""
        SELECT title, url, episodeCount, popularityScore, category1
        FROM podcasts WHERE {base} AND episodeCount >= 20
        AND (lower(category1) = 'education' OR lower(category2) = 'education' OR lower(category3) = 'education'
             OR lower(title) LIKE '%lecture%' OR lower(title) LIKE '%course%' OR lower(title) LIKE '%ted%')
        AND newestEnclosureUrl IS NOT NULL
        AND (lower(newestEnclosureUrl) LIKE '%.mp4%' OR lower(newestEnclosureUrl) LIKE '%.m4v%')
        AND {exclude_cat}
        ORDER BY popularityScore DESC, episodeCount DESC LIMIT 20
    """)
    edu = cur.fetchall()
    print("\nEducation video sample:")
    for r in edu[:10]:
        print(f"  {r[2]:>4}eps pop={r[3]}  {r[0][:55]}")

    # Business, Technology, Health, TV/Arts samples
    for label, cat_cond in [
        ("Business", "lower(category1) = 'business' OR lower(category2) = 'business'"),
        ("Technology", "lower(category1) = 'technology' OR lower(category2) = 'technology' OR lower(title) LIKE '%tech%'"),
        ("Health", "lower(category1) = 'health' OR lower(category2) = 'health'"),
        ("TV/Arts", "lower(category1) IN ('tv','arts') OR lower(category2) IN ('tv','arts')"),
    ]:
        cur = conn.execute(f"""
            SELECT title, episodeCount, popularityScore
            FROM podcasts WHERE {base} AND episodeCount >= 15
            AND ({cat_cond})
            AND newestEnclosureUrl IS NOT NULL
            AND (lower(newestEnclosureUrl) LIKE '%.mp4%' OR lower(newestEnclosureUrl) LIKE '%.m4v%')
            AND {exclude_cat}
            ORDER BY popularityScore DESC LIMIT 12
        """)
        rows = cur.fetchall()
        print(f"\n{label} video sample:")
        for r in rows[:8]:
            print(f"  {r[1]:>4}eps pop={r[2]}  {r[0][:55]}")

    conn.close()


if __name__ == "__main__":
    main()
