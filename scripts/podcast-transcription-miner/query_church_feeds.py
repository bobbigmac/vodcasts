#!/usr/bin/env python3
"""Query podcastindex_feeds.db for church/sermon/bible-study feeds.
Outputs two markdown files: high-value (6+ episodes) and low-value (<=5 episodes).
Excludes feeds already in feeds/church.md or feeds/church-audio-only.md.

Usage:
  python query_church_feeds.py [--high-cap N] [--low-cap N]
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "podcastindex-feeds" / "podcastindex_feeds.db"
DEFAULT_EXCLUDED_HOSTS = ("castbox.fm", "ximalaya.com")

# Church-related search terms (broad match in title, description, categories)
CHURCH_TERMS = [
    "sermon", "church", "bible", "christian", "pastor", "ministry", "worship",
    "gospel", "faith", "evangel", "baptist", "methodist", "presbyterian",
    "catholic", "orthodox", "pentecostal", "calvary", "reformed", "lutheran",
    "homily", "teaching", "devotional", "scripture", "theology", "apologetics",
    "cbn", "700 club", "desiring god", "truth for life", "ligonier",
    "hillsong", "elevation", "life.church", "james river", "bethel",
]

# Excluded patterns (from mine_podcastindex_transcripts)
EXCLUDED = (
    "horoscope", "zodiac", "affirmation", "white noise", "sleep sounds",
    "rain sounds", "nature sounds", "binaural", "solfeggio", "432hz", "528hz",
    "deep house", "dj mix", "lofi", "lo-fi", "pure music", "ambient music",
    "meditation music", "sleep music", "asmr", "sound effects",
)


def slugify(value: str, max_length: int = 120) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^\w\s-]", "", value)
    value = re.sub(r"[-\s]+", "-", value).strip("-")
    return value[:max_length] if len(value) > max_length else value


def load_existing_urls() -> set[str]:
    """Normalize URLs from church.md and church-audio-only.md for dedup."""
    urls = set()
    for fname in ("feeds/church.md", "feeds/church-audio-only.md"):
        path = ROOT / fname
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"- url:\s*(.+?)(?:\s*$|\s+#)", text, re.MULTILINE):
            u = m.group(1).strip().lower()
            u = re.sub(r"^https?://", "", u)
            u = re.sub(r"/+$", "", u)
            urls.add(u)
    return urls


def main() -> None:
    parser = argparse.ArgumentParser(description="Query PodcastIndex for church feeds.")
    parser.add_argument("--high-cap", type=int, default=5000, help="Max high-value feeds to output")
    parser.add_argument("--low-cap", type=int, default=3000, help="Max low-value feeds to output")
    args = parser.parse_args()

    existing = load_existing_urls()

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    # Simpler query: filter by category (Religion & Spirituality) or title/desc match
    # Using fewer LIKE terms for performance; we'll refine in Python
    text_sql = (
        "lower("
        "coalesce(title, '') || ' ' || "
        "coalesce(description, '') || ' ' || "
        "coalesce(category1, '') || ' ' || "
        "coalesce(category2, '') || ' ' || "
        "coalesce(category3, '')"
        ")"
    )
    # Religion category OR key terms (fewer for speed)
    key_terms = ["sermon", "church", "bible", "christian", "pastor", "ministry", "gospel", "faith"]
    term_conditions = " or ".join(f"{text_sql} like ?" for _ in key_terms)
    term_params = [f"%{t}%" for t in key_terms]

    where = (
        "dead = 0 and lastHttpStatus = 200 and episodeCount > 0 "
        "and contentType like '%xml%' and url <> '' "
        f"and ({term_conditions})"
    )

    sql = (
        "select id, url, title, host, episodeCount, popularityScore, "
        "newestItemPubdate, category1, category2, category3, description "
        f"from podcasts where {where} "
        "order by episodeCount desc, popularityScore desc, newestItemPubdate desc"
    )
    cursor = conn.execute(sql, term_params)
    rows = cursor.fetchall()

    # Filter out excluded patterns and expand to all church terms in Python
    def passes_filter(row) -> bool:
        combined = " ".join(
            str(x or "").lower()
            for x in [
                row["title"],
                row["description"],
                row["category1"],
                row["category2"],
                row["category3"],
            ]
        )
        for exc in EXCLUDED:
            if exc in combined:
                return False
        for term in CHURCH_TERMS:
            if term in combined:
                return True
        return False

    rows = [r for r in rows if passes_filter(r)]
    conn.close()

    def url_normalized(row) -> str:
        u = (row["url"] or "").strip().lower()
        u = re.sub(r"^https?://", "", u)
        u = re.sub(r"/+$", "", u)
        return u

    def is_duplicate(row) -> bool:
        u = url_normalized(row)
        for ex in existing:
            if ex in u or u in ex:
                return True
        return False

    high = []
    low = []
    seen_urls: set[str] = set()

    for row in rows:
        if is_duplicate(row):
            continue
        u = url_normalized(row)
        if u in seen_urls:
            continue
        if "castbox.fm" in u or "ximalaya.com" in u:
            continue
        seen_urls.add(u)

        ep_count = int(row["episodeCount"] or 0)
        rec = {
            "id": row["id"],
            "url": row["url"],
            "title": row["title"] or "Unknown",
            "host": row["host"] or "",
            "episodeCount": ep_count,
            "popularityScore": int(row["popularityScore"] or 0),
            "category1": row["category1"] or "",
            "category2": row["category2"] or "",
            "category3": row["category3"] or "",
        }
        if ep_count >= 6:
            high.append(rec)
        else:
            low.append(rec)

    # Cap output for manageability; already sorted by episodeCount, popularityScore
    high = high[: args.high_cap]
    low = low[: args.low_cap]

    def write_feed_block(rec: dict) -> str:
        slug = slugify(rec["title"])
        lines = [
            f"## {slug}",
            f"- url: {rec['url']}",
            f"- title: {rec['title']}",
            f"- category: sermons",
            f"- tags: sermons, podcastindex, episode_count={rec['episodeCount']}, popularity={rec['popularityScore']}",
        ]
        cats = [c for c in [rec["category1"], rec["category2"], rec["category3"]] if c]
        if cats:
            lines.append(f"- podcastindex_categories: {', '.join(cats)}")
        return "\n".join(lines)

    out_high = ROOT / "feeds" / "church-podcastindex-candidates.md"
    out_low = ROOT / "feeds" / "church-podcastindex-low-value.md"

    header_high = f"""# Church/Sermon/Bible feeds from PodcastIndex — candidates (6+ episodes)
<!-- Generated by scripts/podcast-transcription-miner/query_church_feeds.py -->
<!-- Manually review and add to church.md or church-audio-only.md as desired -->
<!-- Excludes feeds already in church.md and church-audio-only.md -->
<!-- Showing top {len(high)} of qualifying feeds (sorted by episodeCount, popularityScore) -->

# Feeds

"""

    header_low = """# Church/Sermon/Bible feeds from PodcastIndex — low value (<=5 episodes)
<!-- Generated by scripts/podcast-transcription-miner/query_church_feeds.py -->
<!-- Lower priority for manual review -->

# Feeds

"""

    out_high.write_text(
        header_high + "\n\n".join(write_feed_block(r) for r in high),
        encoding="utf-8",
    )
    out_low.write_text(
        header_low + "\n\n".join(write_feed_block(r) for r in low),
        encoding="utf-8",
    )

    print(f"High-value (6+ eps): {len(high)} feeds -> {out_high}")
    print(f"Low-value (<=5 eps): {len(low)} feeds -> {out_low}")


if __name__ == "__main__":
    main()
