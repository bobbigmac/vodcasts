from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree as ET


PODCAST_NS = "https://podcastindex.org/namespace/1.0"
ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
PSC_NS = "http://podlove.org/simple-chapters"
MEDIA_NS = "http://search.yahoo.com/mrss/"

_VIDEO_EXT_RE = re.compile(r"\.(mp4|m4v|mov|webm)(\?|$)", re.IGNORECASE)


@dataclass(frozen=True)
class FeedFeatures:
    has_transcript: bool
    has_playable_transcript: bool
    has_chapters: bool
    has_video: bool


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _ns(tag: str) -> str:
    if tag.startswith("{") and "}" in tag:
        return tag.split("}", 1)[0].strip("{")
    return ""


def _text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return (el.text or "").strip()


def _attr(el: ET.Element | None, key: str) -> str:
    if el is None:
        return ""
    return str(el.attrib.get(key) or "").strip()


def _strip_diacritics(s: str) -> str:
    t = str(s or "")
    try:
        norm = unicodedata.normalize("NFKD", t)
        return "".join(ch for ch in norm if not unicodedata.combining(ch))
    except Exception:
        return t


def _slugify_safe(s: str) -> str:
    t = _strip_diacritics(str(s or "").lower())
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    t = re.sub(r"-{2,}", "-", t)
    return t


def _fnv1a32(s: str) -> int:
    h = 0x811C9DC5
    for ch in str(s or ""):
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def _short_hash(s: str, length: int = 6) -> str:
    h = _fnv1a32(s)
    out = base36(h)
    ln = max(4, min(10, int(length or 6)))
    return out[:ln]


def base36(n: int) -> str:
    n = int(n) & 0xFFFFFFFF
    if n == 0:
        return "0"
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = []
    while n:
        n, r = divmod(n, 36)
        out.append(chars[r])
    return "".join(reversed(out))


def _make_episode_slug(*, title: str, date_text: str, ep_id: str) -> str:
    base_title = _slugify_safe(title)
    base = (f"{date_text}-{base_title}" if date_text else base_title) or "episode"
    h = _short_hash(ep_id or title or base, 6)
    return f"{base[:72]}-{h}"


def _parse_time_to_seconds(v: str) -> int | None:
    s = str(v or "").strip()
    if not s:
        return None
    if re.fullmatch(r"\d+(\.\d+)?", s):
        try:
            return max(0, int(float(s)))
        except Exception:
            return None
    parts = [p.strip() for p in s.split(":")]
    if len(parts) < 2 or len(parts) > 3:
        return None
    try:
        nums = [int(float(p)) for p in parts]
    except Exception:
        return None
    if len(nums) == 2:
        hh, mm, ss = 0, nums[0], nums[1]
    else:
        hh, mm, ss = nums
    return max(0, hh * 3600 + mm * 60 + ss)


def _parse_date_text(raw: str) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    try:
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(s)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    try:
        from datetime import datetime

        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return ""


def _is_video_enclosure(url: str, typ: str) -> bool:
    u = (url or "").lower()
    t = (typ or "").lower()
    if t.startswith("video/"):
        return True
    if "mpegurl" in t or u.endswith(".m3u8") or ".m3u8?" in u:
        return True
    if _VIDEO_EXT_RE.search(u):
        return True
    return False


def _pick_best_enclosure(cands: list[dict[str, Any]]) -> dict[str, Any] | None:
    norm = []
    for c in cands or []:
        url = str(c.get("url") or "").strip()
        if not url:
            continue
        norm.append({"url": url, "type": str(c.get("type") or "").lower(), "length": c.get("length")})

    def score(c: dict[str, Any]) -> int:
        u = (c.get("url") or "").lower()
        t = (c.get("type") or "").lower()
        s = 0
        if t.startswith("video/"):
            s += 50
        if ".m3u8" in u:
            s += 45
        if re.search(r"\.(mp4|m4v|mov|webm)(\?|$)", u):
            s += 40
        if "mpegurl" in t:
            s += 35
        if t.startswith("audio/"):
            s += 5
        return s

    if not norm:
        return None
    norm.sort(key=score, reverse=True)
    best = norm[0]
    has_video = any(_is_video_enclosure(c.get("url") or "", c.get("type") or "") for c in norm)
    picked_is_video = _is_video_enclosure(best.get("url") or "", best.get("type") or "")
    out = dict(best)
    out["hasVideoInFeed"] = bool(has_video)
    out["pickedIsVideo"] = bool(picked_is_video)
    # Normalize length to int when possible.
    try:
        ln = int(out.get("length") or 0)
        out["length"] = ln if ln > 0 else None
    except Exception:
        out["length"] = None
    return out


def parse_feed_for_manifest(xml_text: str, *, source_id: str, source_title: str) -> tuple[FeedFeatures, str, list[dict[str, Any]]]:
    """
    Parse RSS/Atom XML into a client-friendly episode list matching the app’s shape.
    Returns (features, channel_title, episodes).
    """
    xml = (xml_text or "").strip()
    if not xml:
        return FeedFeatures(False, False, False, False), (source_title or source_id), []

    try:
        root = ET.fromstring(xml)
    except Exception:
        return FeedFeatures(False, False, False, False), (source_title or source_id), []

    channel_title = source_title or source_id
    channel = None
    for ch in list(root):
        if _local(ch.tag).lower() == "channel":
            channel = ch
            break

    is_atom = _local(root.tag).lower() == "feed" or channel is None
    if channel is not None:
        t = next((c for c in list(channel) if _local(c.tag).lower() == "title"), None)
        if _text(t):
            channel_title = _text(t)
    else:
        t = next((c for c in list(root) if _local(c.tag).lower() == "title"), None)
        if _text(t):
            channel_title = _text(t)

    items = []
    if is_atom:
        items = [c for c in list(root) if _local(c.tag).lower() == "entry"]
    else:
        items = [c for c in list(channel) if _local(c.tag).lower() == "item"] if channel is not None else []

    has_transcript = False
    has_playable_transcript = False
    has_chapters = False
    has_video = False

    episodes = []
    idx = 0
    for item in items:
        idx += 1
        title = _text(next((c for c in list(item) if _local(c.tag).lower() == "title"), None)) or "(untitled)"

        guid = _text(next((c for c in list(item) if _local(c.tag).lower() == "guid"), None))
        atom_id = _text(next((c for c in list(item) if _local(c.tag).lower() == "id"), None))

        link = ""
        if is_atom:
            # Prefer rel=alternate href.
            for l in [c for c in list(item) if _local(c.tag).lower() == "link"]:
                rel = _attr(l, "rel").lower()
                href = _attr(l, "href")
                if href and (rel == "alternate" or not rel):
                    link = href
                    break
            if not link:
                # Some Atom feeds use <link>text</link>
                link = _text(next((c for c in list(item) if _local(c.tag).lower() == "link"), None))
        else:
            link = _text(next((c for c in list(item) if _local(c.tag).lower() == "link"), None))

        # Dates
        date_raw = ""
        for tag in ("pubDate", "published", "updated"):
            el = next((c for c in list(item) if _local(c.tag).lower() == tag.lower()), None)
            if _text(el):
                date_raw = _text(el)
                break
        date_text = _parse_date_text(date_raw)

        # Description: keep raw HTML; client will sanitize.
        desc = ""
        # content:encoded
        for c in list(item):
            if _local(c.tag).lower() == "encoded":
                if _text(c):
                    desc = _text(c)
                    break
        if not desc:
            for tag in ("description", "summary", "content"):
                el = next((c for c in list(item) if _local(c.tag).lower() == tag.lower()), None)
                if _text(el):
                    desc = _text(el)
                    break

        # Duration
        duration_raw = ""
        for c in list(item):
            if _local(c.tag).lower() != "duration":
                continue
            ns = _ns(c.tag)
            if ns == ITUNES_NS or "itunes" in ns.lower() or "itunes" in c.tag.lower():
                duration_raw = _text(c) or _attr(c, "value")
                break
        duration_sec = _parse_time_to_seconds(duration_raw) if duration_raw else None

        # Enclosures
        enclosures: list[dict[str, Any]] = []
        if is_atom:
            for l in [c for c in list(item) if _local(c.tag).lower() == "link"]:
                rel = _attr(l, "rel").lower()
                if rel and rel != "enclosure":
                    continue
                href = _attr(l, "href")
                if href:
                    enclosures.append({"url": href, "type": _attr(l, "type"), "length": _attr(l, "length")})
        else:
            for e in [c for c in list(item) if _local(c.tag).lower() == "enclosure"]:
                enclosures.append({"url": _attr(e, "url"), "type": _attr(e, "type"), "length": _attr(e, "length")})

        for m in [c for c in list(item) if _local(c.tag).lower() == "content" and (_ns(c.tag) == MEDIA_NS or "mrss" in c.tag.lower() or "media" in c.tag.lower())]:
            enclosures.append({"url": _attr(m, "url"), "type": _attr(m, "type"), "length": _attr(m, "fileSize") or _attr(m, "length")})

        media = _pick_best_enclosure(enclosures)
        if media and media.get("hasVideoInFeed"):
            has_video = True

        # Chapters (inline + external)
        psc_chapters = []
        for psc in [c for c in list(item) if _local(c.tag).lower() == "chapters" and (_ns(c.tag) == PSC_NS)]:
            for ch in list(psc):
                if _local(ch.tag).lower() != "chapter":
                    continue
                t0 = _parse_time_to_seconds(_attr(ch, "start"))
                if t0 is None:
                    continue
                psc_chapters.append({"t": t0, "name": _attr(ch, "title") or _text(ch) or "Chapter"})
        if psc_chapters:
            has_chapters = True

        podcast_chapters_url = ""
        podcast_chapters_type = ""
        for c in list(item):
            if _local(c.tag).lower() != "chapters":
                continue
            if _ns(c.tag) == PODCAST_NS:
                podcast_chapters_url = _attr(c, "url")
                podcast_chapters_type = _attr(c, "type") or "application/json"
                if podcast_chapters_url:
                    has_chapters = True
                break

        # Transcripts
        transcripts_all = []
        for c in list(item):
            if _local(c.tag).lower() != "transcript":
                continue
            if _ns(c.tag) != PODCAST_NS:
                continue
            url = _attr(c, "url")
            typ = _attr(c, "type").lower()
            rel = _attr(c, "rel").lower()
            lang = _attr(c, "language") or "en"
            if not url or not typ:
                continue
            is_captions = rel == "captions"
            is_playable = typ in ("text/vtt", "application/x-subrip", "application/srt")
            transcripts_all.append({"url": url, "type": typ, "lang": lang, "isCaptions": is_captions, "isPlayable": is_playable})
            has_transcript = True
            if is_playable:
                has_playable_transcript = True

        transcripts_all.sort(key=lambda t: (not t.get("isPlayable"), not t.get("isCaptions")))
        transcripts = [t for t in transcripts_all if t.get("isPlayable")]

        ep_id = (atom_id or guid or (media.get("url") if media else "") or link or f"{title}#{idx}")[:240]
        slug = _make_episode_slug(title=title, date_text=date_text, ep_id=ep_id)

        episodes.append(
            {
                "id": ep_id,
                "slug": slug,
                "title": title,
                "link": link,
                "date": None,
                "dateText": date_text,
                "descriptionHtml": desc or "",
                "channelTitle": channel_title,
                "durationSec": int(duration_sec) if isinstance(duration_sec, int) and duration_sec > 0 else None,
                "media": (
                    {
                        "url": media.get("url") or "",
                        "type": media.get("type") or "",
                        "bytes": media.get("length") if isinstance(media.get("length"), int) else None,
                        "hasVideoInFeed": bool(media.get("hasVideoInFeed")),
                        "pickedIsVideo": bool(media.get("pickedIsVideo")),
                    }
                    if media and media.get("url")
                    else None
                ),
                "chaptersInline": psc_chapters or None,
                "chaptersExternal": {"url": podcast_chapters_url, "type": podcast_chapters_type} if podcast_chapters_url else None,
                "transcripts": transcripts,
                "transcriptsAll": transcripts_all,
            }
        )

    features = FeedFeatures(
        has_transcript=bool(has_transcript),
        has_playable_transcript=bool(has_playable_transcript),
        has_chapters=bool(has_chapters),
        has_video=bool(has_video),
    )
    return features, channel_title, episodes
