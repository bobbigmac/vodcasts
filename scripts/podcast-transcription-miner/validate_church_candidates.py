#!/usr/bin/env python3
"""Validate church-podcastindex-candidates.md feeds: fetch each URL, verify it exists,
has real RSS/XML content (not HTML landing page), and has episodes with enclosures.
Output validated feeds split by enclosure type:
  - church-podcastindex-validated-video.md (video enclosures only)
  - church-podcastindex-validated-audio.md (audio enclosures only)
  - church-podcastindex-validated-mixed.md (both video and audio)

Uses DB columns (itunesId, priority, newestItemPubdate) for quality ranking.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from xml.etree import ElementTree as ET

import requests

ROOT = Path(__file__).resolve().parents[2]
CANDIDATES_PATH = ROOT / "feeds" / "church-podcastindex-candidates.md"
DB_PATH = ROOT / "podcastindex-feeds" / "podcastindex_feeds.db"
OUT_DIR = ROOT / "feeds"
CACHE_PATH = ROOT / "tmp" / "church-candidates-validation-cache.json"
USER_AGENT = "actual-plays/vodcasts (+https://github.com/)"
TIMEOUT = 25
MAX_WORKERS = 12
PER_HOST_DELAY = 0.5
PROGRESS_EVERY = 15


def parse_localname(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1].lower()
    if ":" in tag:
        return tag.rsplit(":", 1)[1].lower()
    return tag.lower()


def parse_candidates(path: Path) -> list[dict]:
    """Parse church-podcastindex-candidates.md into list of {slug, url, title, ...}."""
    text = path.read_text(encoding="utf-8")
    entries = []
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            if current and current.get("url"):
                entries.append(current)
            slug = line[3:].strip()
            current = {"slug": slug, "url": "", "title": slug.replace("-", " ").title()}
        elif current is not None:
            if line.strip().startswith("- url:"):
                current["url"] = line.split(":", 1)[1].strip()
            elif line.strip().startswith("- title:"):
                current["title"] = line.split(":", 1)[1].strip()
            elif line.strip().startswith("- tags:"):
                current["tags_raw"] = line.split(":", 1)[1].strip()
    if current and current.get("url"):
        entries.append(current)
    return entries


def looks_like_feed_xml(content: bytes) -> bool:
    s = content[:64 * 1024].decode("utf-8", errors="replace").lstrip().lower()
    if not s:
        return False
    if s.startswith("<!doctype html") or s.startswith("<html"):
        return False
    if "<rss" in s or "<feed" in s or "<rdf:rdf" in s:
        return True
    if "<channel" in s and ("<item" in s or "<enclosure" in s):
        return True
    return False


_VIDEO_EXT_RE = re.compile(r"\.(mp4|m4v|mov|webm|m3u8)(\?|$)", re.IGNORECASE)
_AUDIO_EXT_RE = re.compile(r"\.(mp3|m4a|aac|ogg|wav|flac)(\?|$)", re.IGNORECASE)


def _is_video_enclosure(url: str, typ: str) -> bool:
    u, t = (url or "").lower(), (typ or "").lower()
    if t.startswith("video/"):
        return True
    if "mpegurl" in t or ".m3u8" in u:
        return True
    if _VIDEO_EXT_RE.search(u):
        return True
    return False


def _is_audio_enclosure(url: str, typ: str) -> bool:
    u, t = (url or "").lower(), (typ or "").lower()
    if t.startswith("audio/"):
        return True
    if _AUDIO_EXT_RE.search(u):
        return True
    if ".mp3" in u or ".m4a" in u:
        return True
    return False


def _item_enclosure_types(item: ET.Element) -> tuple[bool, bool]:
    """Return (has_video, has_audio) for enclosures in this item."""
    has_v, has_a = False, False
    for c in item.iter() if hasattr(item, "iter") else list(item):
        local = parse_localname(c.tag)
        url, typ = "", ""
        if local == "enclosure":
            url = (c.attrib.get("url") or "").strip()
            typ = (c.attrib.get("type") or "").lower()
        elif local == "link":
            rel = (c.attrib.get("rel") or "").lower()
            if rel != "enclosure" and "audio" not in (c.attrib.get("type") or "").lower() and "video" not in (c.attrib.get("type") or "").lower():
                continue
            url = (c.attrib.get("href") or "").strip()
            typ = (c.attrib.get("type") or "").lower()
        if not url:
            continue
        if _is_video_enclosure(url, typ):
            has_v = True
        if _is_audio_enclosure(url, typ):
            has_a = True
        if not has_v and not has_a:
            if ".mp4" in url.lower() or ".m4v" in url.lower() or ".webm" in url.lower():
                has_v = True
            elif ".mp3" in url.lower() or ".m4a" in url.lower():
                has_a = True
    return has_v, has_a


def count_items_and_enclosure_types(xml_bytes: bytes) -> tuple[int, int, bool, bool]:
    """Return (item_count, enclosure_count, has_video, has_audio)."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return 0, 0, False, False
    items = root.findall(".//item")
    if not items:
        items = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    if not items:
        items = root.findall(".//{*}entry")
    enc_count = 0
    has_video, has_audio = False, False
    for it in items:
        v, a = _item_enclosure_types(it)
        if v or a:
            enc_count += 1
            has_video = has_video or v
            has_audio = has_audio or a
    return len(items), enc_count, has_video, has_audio


def validate_feed(url: str) -> dict:
    """Fetch feed, verify it's real RSS with content. Return validation result."""
    result = {
        "ok": False,
        "url": url,
        "status": None,
        "item_count": 0,
        "enclosure_count": 0,
        "has_video": False,
        "has_audio": False,
        "reason": "",
    }
    try:
        resp = requests.get(
            url,
            timeout=TIMEOUT,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
            },
            allow_redirects=True,
        )
        result["status"] = resp.status_code
        if resp.status_code != 200:
            result["reason"] = f"http {resp.status_code}"
            return result
        content = resp.content
        if not content or len(content) < 200:
            result["reason"] = "empty or tiny response"
            return result
        if not looks_like_feed_xml(content):
            result["reason"] = "not feed xml (likely HTML landing page)"
            return result
        items, enc, has_v, has_a = count_items_and_enclosure_types(content)
        result["item_count"] = items
        result["enclosure_count"] = enc
        result["has_video"] = has_v
        result["has_audio"] = has_a
        if items == 0:
            result["reason"] = "no items in feed"
            return result
        if enc == 0 and items > 0:
            result["reason"] = "items but no enclosures"
            result["ok"] = True
            result["item_count"] = items
        else:
            result["ok"] = True
    except requests.Timeout:
        result["reason"] = "timeout"
    except requests.RequestException as e:
        result["reason"] = str(e)[:80]
    except Exception as e:
        result["reason"] = str(e)[:80]
    return result


def _norm_url(u: str) -> str:
    return re.sub(r"^https?://", "", (u or "").lower()).rstrip("/")


def load_cache(path: Path) -> dict[str, dict]:
    """Load validation cache: url -> result dict (ok, item_count, has_video, has_audio, etc)."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_cache(path: Path, cache: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8")


def load_db_metadata(conn: sqlite3.Connection, urls: set[str]) -> dict[str, dict]:
    """Load itunesId, priority, newestItemPubdate, popularityScore for each URL."""
    url_to_norm = {_norm_url(u): u for u in urls}
    out = {}
    cursor = conn.execute(
        "select url, itunesId, priority, newestItemPubdate, popularityScore, episodeCount "
        "from podcasts where url <> ''"
    )
    for row in cursor.fetchall():
        u = (row[0] or "").strip()
        if not u:
            continue
        u_norm = _norm_url(u)
        if u_norm in url_to_norm:
            orig = url_to_norm[u_norm]
            out[orig] = {
                "itunesId": int(row[1] or 0),
                "priority": int(row[2] or -1),
                "newestItemPubdate": int(row[3] or 0),
                "popularityScore": int(row[4] or 0),
                "episodeCount": int(row[5] or 0),
            }
    return out


def quality_score(rec: dict, db_meta: dict | None) -> float:
    """Higher = better. Favors: verified items, enclosures, popularity, recency, itunesId."""
    score = 0.0
    items = rec.get("item_count") or 0
    enclosures = rec.get("enclosure_count") or 0
    score += min(items * 2, 500)
    score += min(enclosures * 3, 300)
    if db_meta:
        pop = db_meta.get("popularityScore") or 0
        score += min(pop * 20, 200)
        if db_meta.get("itunesId", 0) > 0:
            score += 50
        if db_meta.get("priority", -1) >= 0:
            score += 30
        newest = db_meta.get("newestItemPubdate") or 0
        if newest > time.time() - 86400 * 180:
            score += 40
        elif newest > time.time() - 86400 * 365:
            score += 20
    return score


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate church candidate feeds.")
    parser.add_argument("--input", default=str(CANDIDATES_PATH), help="Input candidates markdown")
    parser.add_argument("--limit", type=int, default=0, help="Limit feeds to validate (0=all)")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    parser.add_argument("--min-items", type=int, default=3, help="Min verified items to pass")
    parser.add_argument("--no-resume", action="store_true", help="Ignore cache and revalidate all")
    parser.add_argument("--progress-every", type=int, default=PROGRESS_EVERY, help="Print progress every N seconds")
    args = parser.parse_args()

    candidates = parse_candidates(Path(args.input))
    if args.limit > 0:
        candidates = candidates[: args.limit]

    cache = {} if args.no_resume else load_cache(CACHE_PATH)
    cache_lock = threading.Lock()
    to_validate = [c for c in candidates if _norm_url(c["url"]) not in {_norm_url(k) for k in cache}]
    skipped = len(candidates) - len(to_validate)

    if skipped:
        print(f"Resuming: {skipped} already in cache, {len(to_validate)} to validate")
    else:
        print(f"Validating {len(to_validate)} feeds (workers={args.workers})...")

    validated = []
    failed = 0
    start = time.time()
    last_progress = start
    completed = 0

    def apply_cached(c: dict, r: dict) -> None:
        if r["ok"] and r.get("item_count", 0) >= args.min_items:
            validated.append({
                **c,
                "item_count": r["item_count"],
                "enclosure_count": r.get("enclosure_count", 0),
                "has_video": r.get("has_video", False),
                "has_audio": r.get("has_audio", False),
            })
        else:
            nonlocal failed
            failed += 1

    for c in candidates:
        key = _norm_url(c["url"])
        if key in cache:
            r = cache[key]
            r["url"] = c["url"]
            apply_cached(c, r)
            completed += 1

    if not to_validate:
        print(f"All {len(candidates)} feeds already cached. Writing output...")
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(validate_feed, c["url"]): c for c in to_validate}
            for fut in concurrent.futures.as_completed(futures):
                c = futures[fut]
                try:
                    r = fut.result()
                except Exception as e:
                    r = {"ok": False, "url": c["url"], "reason": str(e)[:60]}
                apply_cached(c, r)
                completed += 1
                with cache_lock:
                    cache[_norm_url(c["url"])] = {
                        "ok": r.get("ok", False),
                        "item_count": r.get("item_count", 0),
                        "enclosure_count": r.get("enclosure_count", 0),
                        "has_video": r.get("has_video", False),
                        "has_audio": r.get("has_audio", False),
                        "reason": r.get("reason", ""),
                    }
                now = time.time()
                if now - last_progress >= args.progress_every:
                    elapsed = now - start
                    rate = completed / elapsed if elapsed > 0 else 0
                    remaining = len(candidates) - completed
                    eta = remaining / rate if rate > 0 else 0
                    print(f"  {completed}/{len(candidates)} | passed={len(validated)} failed={failed} | {rate:.1f}/s | ETA {eta/60:.1f}m")
                    last_progress = now
                    save_cache(CACHE_PATH, cache)

        save_cache(CACHE_PATH, cache)

    elapsed = time.time() - start
    print(f"Done: {len(validated)} passed, {failed} failed ({elapsed:.1f}s)")

    if not validated:
        print("No validated feeds to output.")
        return

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) if DB_PATH.exists() else None
    urls = {v["url"] for v in validated}
    db_meta = load_db_metadata(conn, urls) if conn else {}
    if conn:
        conn.close()

    for v in validated:
        v["_score"] = quality_score(v, db_meta.get(v["url"]))
    validated.sort(key=lambda x: -x["_score"])

    video_only = [v for v in validated if v.get("has_video") and not v.get("has_audio")]
    audio_only = [v for v in validated if v.get("has_audio") and not v.get("has_video")]
    mixed = [v for v in validated if v.get("has_video") and v.get("has_audio")]
    # Feeds with enclosures but unclear type (e.g. generic URLs) go to audio as default
    other = [v for v in validated if not v.get("has_video") and not v.get("has_audio") and v.get("enclosure_count", 0) > 0]
    if other:
        audio_only = audio_only + other

    def write_feed_file(basename: str, items: list[dict], enclosure_label: str) -> None:
        if not items:
            return
        lines = [
            f"# Church/Sermon/Bible feeds from PodcastIndex — validated ({enclosure_label})",
            "<!-- Generated by scripts/podcast-transcription-miner/validate_church_candidates.py -->",
            "<!-- Feeds verified to exist, return RSS/XML (not HTML), and have episodes. -->",
            f"<!-- Ranked by quality. Total: {len(items)} -->",
            "",
            "# Feeds",
            "",
        ]
        for v in items:
            meta = db_meta.get(v["url"]) or {}
            pop = meta.get("popularityScore", 0)
            lines.append(f"## {v['slug']}")
            lines.append(f"- url: {v['url']}")
            lines.append(f"- title: {v['title']}")
            lines.append(f"- category: sermons")
            tags = f"sermons, podcastindex, {enclosure_label}, verified_items={v['item_count']}, enclosures={v.get('enclosure_count', 0)}, popularity={pop}"
            lines.append(f"- tags: {tags}")
            lines.append("")
        out = OUT_DIR / basename
        out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        print(f"  {out.name}: {len(items)} feeds")

    print("Writing output files:")
    write_feed_file("church-podcastindex-validated-video.md", video_only, "video")
    write_feed_file("church-podcastindex-validated-audio.md", audio_only, "audio")
    write_feed_file("church-podcastindex-validated-mixed.md", mixed, "mixed")


if __name__ == "__main__":
    main()
