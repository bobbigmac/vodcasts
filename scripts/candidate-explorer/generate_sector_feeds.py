#!/usr/bin/env python3
"""Generate sector feed files from podcastindex_feeds.db.
Video/mixed only (no audio-only). Excludes feeds already in existing feed files.

Outputs:
  feeds/leisure.md (~100) - leisure, hobbies, DIY, crafts, how-to, arts, photography, brewing, cooking
  feeds/news_extended.md (~200) - news, politics, business not in news.md
  feeds/education.md, feeds/technology.md, feeds/health.md, feeds/science.md, etc.

Usage:
  python scripts/generate_sector_feeds.py
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "podcastindex-feeds" / "podcastindex_feeds.db"
FEEDS_DIR = ROOT / "feeds"
CANDIDATES_DIR = ROOT / "feeds" / "candidates"

# Video enclosure URL patterns - must have these (exclude audio-only)
VIDEO_EXT = ("mp4", "m4v", "webm", "mov", "m3u8")
EXCLUDE_CAT = ("religion", "spirituality", "christianity", "buddhism", "hinduism")


def slugify(value: str, max_length: int = 80) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^\w\s-]", "", value)
    value = re.sub(r"[-\s]+", "-", value).strip("-")
    return value[:max_length] if len(value) > max_length else value or "feed"


def load_existing_urls() -> set[str]:
    """Normalize URLs from primary feed files (church, news, bonus, tech) for dedup."""
    primary = {"church.md", "news.md", "bonus.md", "tech.md", "church-audio-only.md", "dev.md"}
    urls = set()
    for f in FEEDS_DIR.glob("*.md"):
        if f.name not in primary or "content-slate-review" in str(f):
            continue
        text = f.read_text(encoding="utf-8")
        for m in re.finditer(r"-\s*url:\s*(.+?)(?:\s*$|\s+#)", text, re.MULTILINE):
            u = m.group(1).strip().lower()
            u = re.sub(r"^https?://", "", u)
            u = re.sub(r"/+$", "", u)
            u = re.sub(r"\?.*$", "", u)  # strip query for dedup
            if u and "disabled" not in text[max(0, m.start() - 200) : m.start()]:
                urls.add(u)
    return urls


def is_video_url(url: str) -> bool:
    if not url:
        return False
    u = url.lower()
    return any(f".{ext}" in u or f".{ext}?" in u for ext in VIDEO_EXT)


def fetch_video_feeds(
    conn: sqlite3.Connection,
    exclude_urls: set[str],
    category_conditions: list[str],
    limit: int,
    min_episodes: int = 5,
    min_pop: int = 4,
) -> list[dict]:
    """Fetch video feeds matching category conditions."""
    base = (
        "dead=0 AND lastHttpStatus=200 AND episodeCount>=? AND popularityScore>=? "
        "AND contentType LIKE '%xml%' AND url<>'' AND newestEnclosureUrl IS NOT NULL AND newestEnclosureUrl<>'' "
        "AND (lower(newestEnclosureUrl) LIKE '%.mp4%' OR lower(newestEnclosureUrl) LIKE '%.m4v%' "
        "OR lower(newestEnclosureUrl) LIKE '%.webm%' OR lower(newestEnclosureUrl) LIKE '%.mov%' "
        "OR lower(newestEnclosureUrl) LIKE '%.m3u8%') "
        "AND coalesce(lower(trim(category1)),'') NOT IN ('religion','spirituality','christianity') "
        "AND coalesce(lower(trim(category2)),'') NOT IN ('religion','spirituality','christianity') "
        "AND coalesce(lower(trim(category3)),'') NOT IN ('religion','spirituality','christianity') "
        "AND (lower(host) NOT IN ('castbox.fm','ximalaya.com') OR host IS NULL)"
    )
    cat_sql = " OR ".join(f"({c})" for c in category_conditions)
    sql = f"""
        SELECT url, title, episodeCount, popularityScore, category1, category2, category3
        FROM podcasts
        WHERE {base} AND ({cat_sql})
        ORDER BY popularityScore DESC, episodeCount DESC
        LIMIT ?
    """
    cur = conn.execute(sql, [min_episodes, min_pop, limit * 2])
    rows = cur.fetchall()
    seen = set()
    out = []
    for r in rows:
        url = (r[0] or "").strip()
        url_norm = re.sub(r"^https?://", "", url.lower()).split("?")[0].rstrip("/")
        if url_norm in exclude_urls:
            continue
        if url_norm in seen:
            continue
        seen.add(url_norm)
        out.append({
            "url": url,
            "title": r[1] or "Unknown",
            "episodeCount": int(r[2] or 0),
            "popularityScore": int(r[3] or 0),
            "category1": r[4] or "",
            "category2": r[5] or "",
            "category3": r[6] or "",
        })
        if len(out) >= limit:
            break
    return out


def write_feed_file(
    fname: str,
    feeds: list[dict],
    category: str,
    title: str,
    description: str,
) -> None:
    CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
    out = CANDIDATES_DIR / fname
    lines = [
        "# Site",
        f"- id: vodcasts-{fname.replace('.md','')}",
        f"- title: {title}",
        f"- description: {description}",
        "",
        "# Defaults",
        "- min_hours_between_checks: 2",
        "- request_timeout_seconds: 25",
        "- user_agent: actual-plays/vodcasts (+https://github.com/)",
        "",
        "# Feeds",
        "",
    ]
    for f in feeds:
        slug = slugify(f["title"])
        cats = [c for c in [f["category1"], f["category2"], f["category3"]] if c]
        tags = f"podcastindex, video, {category}, eps={f['episodeCount']}, pop={f['popularityScore']}"
        if cats:
            tags += ", " + ", ".join(cats[:3])
        lines.append(f"## {slug}")
        lines.append(f"- url: {f['url']}")
        lines.append(f"- title: {f['title']}")
        lines.append(f"- category: {category}")
        lines.append(f"- tags: {tags}")
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out} ({len(feeds)} feeds)")


def main() -> None:
    if not DB_PATH.exists():
        print(f"DB not found: {DB_PATH}")
        return

    exclude = load_existing_urls()
    print(f"Excluding {len(exclude)} existing feed URLs")

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    used_urls: set[str] = set()

    def norm(u: str) -> str:
        return re.sub(r"^https?://", "", u.lower()).split("?")[0].rstrip("/")

    def add_used(feeds: list[dict]) -> None:
        for f in feeds:
            used_urls.add(norm(f["url"]))

    def exclude_used(feeds: list[dict]) -> list[dict]:
        return [f for f in feeds if norm(f["url"]) not in used_urls]

    # --- LEISURE ---
    # leisure, hobbies, DIY, crafts, how-to, arts, photography, brewing, cooking
    leisure_conds = [
        "lower(category1) IN ('leisure','arts') OR lower(category2) IN ('leisure','arts')",
        "lower(title) LIKE '%photography%' OR lower(title) LIKE '%cooking%' OR lower(title) LIKE '%brew%'",
        "lower(title) LIKE '%diy%' OR lower(title) LIKE '%craft%' OR lower(title) LIKE '%hobby%'",
        "lower(title) LIKE '%how-to%' OR lower(title) LIKE '%how to%'",
        "lower(title) LIKE '%start cooking%' OR lower(title) LIKE '%art of photography%' OR lower(title) LIKE '%behind the shot%'",
    ]
    leisure = fetch_video_feeds(conn, exclude, leisure_conds, 100, min_episodes=10, min_pop=4)
    leisure = exclude_used(leisure)
    add_used(leisure[:100])
    write_feed_file(
        "leisure.md",
        leisure[:100],
        "leisure",
        "VODcasts Leisure",
        "Hobbies, DIY, crafts, how-to, photography, brewing, cooking, and lifestyle video feeds.",
    )

    # --- NEWS_EXTENDED (~200) ---
    # news, politics, business - exclude feeds already in news.md
    news_conds = [
        "lower(category1) IN ('news','government','society') OR lower(category2) IN ('news','government','society')",
        "lower(title) LIKE '%news%' OR lower(title) LIKE '%politics%' OR lower(title) LIKE '%headlines%'",
        "lower(title) LIKE '%business%' OR lower(title) LIKE '%market%' OR lower(title) LIKE '%economy%'",
        "lower(title) LIKE '%bbc%' OR lower(title) LIKE '%npr%' OR lower(title) LIKE '%bloomberg%'",
        "lower(title) LIKE '%fox%' OR lower(title) LIKE '%cnn%' OR lower(title) LIKE '%reuters%'",
    ]
    news_ext = fetch_video_feeds(conn, exclude, news_conds, 200, min_episodes=5, min_pop=3)
    news_ext = exclude_used(news_ext)
    add_used(news_ext[:200])
    write_feed_file(
        "news_extended.md",
        news_ext[:200],
        "news",
        "VODcasts News Extended",
        "Extended news, politics, and business video feeds from PodcastIndex.",
    )

    # --- EDUCATION ---
    edu_conds = [
        "lower(category1) = 'education' OR lower(category2) = 'education'",
        "lower(title) LIKE '%lecture%' OR lower(title) LIKE '%course%' OR lower(title) LIKE '%ted%'",
        "lower(title) LIKE '%learning%' OR lower(title) LIKE '%esl%' OR lower(title) LIKE '%grammar%'",
    ]
    edu = fetch_video_feeds(conn, exclude, edu_conds, 80, min_episodes=15, min_pop=4)
    edu = exclude_used(edu)
    add_used(edu)
    write_feed_file(
        "education.md",
        edu[:80],
        "education",
        "VODcasts Education",
        "Education, lectures, courses, and how-to video feeds.",
    )

    # --- TECHNOLOGY (exclude tech.md) ---
    tech_conds = [
        "lower(category1) = 'technology' OR lower(category2) = 'technology'",
        "lower(title) LIKE '%tech%' OR lower(title) LIKE '%software%' OR lower(title) LIKE '%developer%'",
    ]
    tech = fetch_video_feeds(conn, exclude, tech_conds, 60, min_episodes=10, min_pop=4)
    tech = exclude_used(tech)
    add_used(tech)
    write_feed_file(
        "technology.md",
        tech[:60],
        "technology",
        "VODcasts Technology",
        "Technology and developer video feeds.",
    )

    # --- BUSINESS ---
    biz_conds = [
        "lower(category1) = 'business' OR lower(category2) = 'business'",
        "lower(title) LIKE '%real estate%' OR lower(title) LIKE '%trading%' OR lower(title) LIKE '%entrepreneur%'",
    ]
    biz = fetch_video_feeds(conn, exclude, biz_conds, 70, min_episodes=10, min_pop=4)
    biz = exclude_used(biz)
    add_used(biz)
    write_feed_file(
        "business.md",
        biz[:70],
        "business",
        "VODcasts Business",
        "Business, entrepreneurship, and trading video feeds.",
    )

    # --- HEALTH ---
    health_conds = [
        "lower(category1) = 'health' OR lower(category2) = 'health'",
        "lower(title) LIKE '%nutrition%' OR lower(title) LIKE '%fitness%' OR lower(title) LIKE '%wellness%'",
    ]
    health = fetch_video_feeds(conn, exclude, health_conds, 25, min_episodes=10, min_pop=4)
    health = exclude_used(health)
    add_used(health)
    write_feed_file(
        "health.md",
        health[:25],
        "health",
        "VODcasts Health",
        "Health, nutrition, and wellness video feeds.",
    )

    # --- SCIENCE ---
    science_conds = [
        "lower(category1) = 'science' OR lower(category2) = 'science'",
        "lower(title) LIKE '%science%' OR lower(title) LIKE '%research%'",
    ]
    science = fetch_video_feeds(conn, exclude, science_conds, 25, min_episodes=10, min_pop=4)
    science = exclude_used(science)
    add_used(science)
    write_feed_file(
        "science.md",
        science[:25],
        "science",
        "VODcasts Science",
        "Science and research video feeds.",
    )

    # --- KIDS & FAMILY ---
    kids_conds = ["lower(category1) = 'kids' OR lower(category2) = 'kids'"]
    kids = fetch_video_feeds(conn, exclude, kids_conds, 20, min_episodes=5, min_pop=3)
    kids = exclude_used(kids)
    add_used(kids)
    write_feed_file(
        "kids.md",
        kids[:20],
        "kids",
        "VODcasts Kids",
        "Kids and family video feeds.",
    )

    # --- SPORTS ---
    sports_conds = ["lower(category1) = 'sports' OR lower(category2) = 'sports'"]
    sports = fetch_video_feeds(conn, exclude, sports_conds, 15, min_episodes=5, min_pop=3)
    sports = exclude_used(sports)
    add_used(sports)
    write_feed_file(
        "sports.md",
        sports[:15],
        "sports",
        "VODcasts Sports",
        "Sports video feeds.",
    )

    # --- COMEDY ---
    comedy_conds = ["lower(category1) = 'comedy' OR lower(category2) = 'comedy'"]
    comedy = fetch_video_feeds(conn, exclude, comedy_conds, 15, min_episodes=5, min_pop=3)
    comedy = exclude_used(comedy)
    add_used(comedy)
    write_feed_file(
        "comedy.md",
        comedy[:15],
        "comedy",
        "VODcasts Comedy",
        "Comedy video feeds.",
    )

    # --- MUSIC ---
    music_conds = ["lower(category1) = 'music' OR lower(category2) = 'music'"]
    music = fetch_video_feeds(conn, exclude, music_conds, 15, min_episodes=5, min_pop=3)
    music = exclude_used(music)
    add_used(music)
    write_feed_file(
        "music.md",
        music[:15],
        "music",
        "VODcasts Music",
        "Music video feeds.",
    )

    # --- TV & FILM ---
    tv_conds = [
        "lower(category1) IN ('tv','arts') OR lower(category2) IN ('tv','arts')",
        "lower(title) LIKE '%film%' OR lower(title) LIKE '%movie%'",
    ]
    tv = fetch_video_feeds(conn, exclude, tv_conds, 30, min_episodes=10, min_pop=4)
    tv = exclude_used(tv)
    add_used(tv)
    write_feed_file(
        "tv-arts.md",
        tv[:30],
        "tv",
        "VODcasts TV & Arts",
        "TV, film, and arts video feeds.",
    )

    conn.close()

    total = (
        min(100, len(leisure))
        + min(200, len(news_ext))
        + min(80, len(edu))
        + min(60, len(tech))
        + min(70, len(biz))
        + min(25, len(health))
        + min(25, len(science))
        + min(20, len(kids))
        + min(15, len(sports))
        + min(15, len(comedy))
        + min(15, len(music))
        + min(30, len(tv))
    )
    print(f"\nTotal feeds: ~{total}")


if __name__ == "__main__":
    main()
