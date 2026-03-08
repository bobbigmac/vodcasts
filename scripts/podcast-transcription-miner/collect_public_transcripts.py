from __future__ import annotations

import argparse
import html
import json
import re
import ssl
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = ROOT / "podcast-transcripts"
DEFAULT_SHOWS_PATH = Path(__file__).with_name("top_shows.json")
USER_AGENT = "Mozilla/5.0 (compatible; vodcasts-public-transcripts/1.0)"

PLAYABLE_TYPES = {
    "text/vtt",
    "text/webvtt",
    "application/x-subrip",
    "application/srt",
}

SRT_TS_RE = re.compile(r"^\d{2}:\d{2}:\d{2}[,.]\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}[,.]\d{3}$")
VTT_TS_RE = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}\.\d{3}$")
VTT_TS_MMSS_RE = re.compile(r"^\d{1,2}:\d{2}\.\d{3}\s+-->\s+\d{1,2}:\d{2}\.\d{3}$")


@dataclass
class TranscriptCandidate:
    url: str
    typ: str
    lang: str
    rel: str


@dataclass
class EpisodeTranscript:
    track_name: str
    episode_guid: str
    release_date: str
    source_url: str
    source_type: str
    language: str
    local_path: str


@dataclass
class ShowReport:
    query: str
    collection_name: str
    collection_id: int | None
    artist_name: str
    feed_url: str
    show_slug: str
    transcript_support: bool
    episodes_considered: int
    episodes_downloaded: int
    skipped_existing: int
    errors: list[str]
    transcript_files: list[EpisodeTranscript]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Collect public timestamped podcast transcripts from RSS feeds.")
    p.add_argument("--shows", default=str(DEFAULT_SHOWS_PATH), help="JSON file containing show names.")
    p.add_argument("--out", default=str(DEFAULT_OUT_DIR), help="Output directory.")
    p.add_argument("--max-episodes-per-show", type=int, default=0, help="Max episodes to inspect per show (0 = all feed items).")
    p.add_argument("--show-limit", type=int, default=0, help="Limit total shows processed (0 = all).")
    p.add_argument("--refresh", action="store_true", help="Re-download existing files.")
    return p.parse_args()


def http_get(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, application/xml, text/xml, text/plain, */*",
        },
    )
    ctx = ssl.create_default_context()
    return urllib.request.urlopen(req, timeout=40, context=ctx).read()


def slugify(text: str, *, max_len: int = 120) -> str:
    value = (text or "").strip().lower()
    value = re.sub(r"[^\w\s-]", "", value)
    value = re.sub(r"[-\s]+", "-", value).strip("-")
    if not value:
        value = "item"
    return value[:max_len].rstrip("-")


def parse_localname(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1].lower()
    if ":" in tag:
        return tag.rsplit(":", 1)[1].lower()
    return tag.lower()


def load_shows(path: Path, show_limit: int) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    shows = [str(item).strip() for item in data if str(item).strip()]
    if show_limit > 0:
        shows = shows[:show_limit]
    return shows


def search_show(query: str) -> dict[str, Any] | None:
    params = urllib.parse.urlencode({
        "media": "podcast",
        "entity": "podcast",
        "limit": "8",
        "term": query,
    })
    payload = json.loads(http_get(f"https://itunes.apple.com/search?{params}").decode("utf-8"))
    results = payload.get("results") or []
    if not results:
        return None
    return results[0]


def lookup_episodes(collection_id: int, limit: int) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({
        "id": str(collection_id),
        "entity": "podcastEpisode",
        "limit": str(limit),
    })
    payload = json.loads(http_get(f"https://itunes.apple.com/lookup?{params}").decode("utf-8"))
    results = payload.get("results") or []
    return [item for item in results if item.get("wrapperType") == "podcastEpisode"]


def find_episode_node(root: ET.Element, guid: str, track_name: str) -> ET.Element | None:
    guid = (guid or "").strip()
    track_name = (track_name or "").strip().lower()
    items = root.findall(".//item")
    if not items:
        items = root.findall(".//{*}entry")
    for item in items:
        text_candidates: list[str] = []
        for child in list(item):
            local = parse_localname(child.tag)
            if local == "guid" and (child.text or "").strip() == guid:
                return item
            if local in {"title", "guid", "id"} and child.text:
                text_candidates.append(child.text.strip().lower())
        if track_name and any(track_name == value for value in text_candidates):
            return item
    return None


def item_text(item: ET.Element, *names: str) -> str:
    wanted = {name.lower() for name in names}
    for child in list(item):
        local = parse_localname(child.tag)
        if local in wanted and (child.text or "").strip():
            return child.text.strip()
    return ""


def normalize_release_date(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
    ):
        try:
            dt = __import__("datetime").datetime.strptime(value, fmt)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
    return value


def feed_episode_entries(root: ET.Element, limit: int) -> list[dict[str, str]]:
    items = root.findall(".//item")
    if not items:
        items = root.findall(".//{*}entry")
    entries: list[dict[str, str]] = []
    for item in items:
        title = item_text(item, "title")
        guid = item_text(item, "guid", "id") or title
        release_date = normalize_release_date(
            item_text(item, "pubDate", "published", "updated", "date")
        )
        entries.append({
            "trackName": title,
            "episodeGuid": guid,
            "releaseDate": release_date,
        })
        if limit > 0 and len(entries) >= limit:
            break
    return entries


def extract_transcript_candidates(item: ET.Element) -> list[TranscriptCandidate]:
    out: list[TranscriptCandidate] = []
    for child in list(item):
        if parse_localname(child.tag) != "transcript":
            continue
        url = (child.attrib.get("url") or child.attrib.get("href") or "").strip()
        typ = (child.attrib.get("type") or "").strip().lower()
        lang = (child.attrib.get("{http://www.w3.org/XML/1998/namespace}lang") or child.attrib.get("lang") or "").strip()
        rel = (child.attrib.get("rel") or "").strip().lower()
        if not url:
            continue
        out.append(TranscriptCandidate(url=url, typ=typ, lang=lang, rel=rel))
    return out


def normalize_vtt_timestamp_commas(text: str) -> str:
    lines: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", raw)
        line = re.sub(r"(\d{1,2}:\d{2}),(\d{3})", r"\1.\2", line)
        lines.append(line)
    return "\n".join(lines).rstrip() + "\n"


def extract_text_from_vtt(text: str) -> str:
    parts: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.upper().startswith("WEBVTT"):
            continue
        if VTT_TS_RE.match(line) or VTT_TS_MMSS_RE.match(line) or SRT_TS_RE.match(line):
            continue
        if "-->" in line:
            continue
        if line.startswith("NOTE"):
            continue
        cleaned = re.sub(r"<[^>]+>", "", line).strip()
        if cleaned:
            parts.append(cleaned)
    return " ".join(parts).strip()


def extract_text_from_srt(text: str) -> str:
    parts: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.isdigit() or SRT_TS_RE.match(line):
            continue
        cleaned = re.sub(r"<[^>]+>", "", line).strip()
        if cleaned:
            parts.append(cleaned)
    return " ".join(parts).strip()


def looks_like_vtt(text: str) -> bool:
    stripped = text.lstrip()
    if stripped.upper().startswith("WEBVTT"):
        return True
    return any(
        VTT_TS_RE.match(line.strip()) or VTT_TS_MMSS_RE.match(line.strip())
        for line in stripped.splitlines()[:200]
    )


def looks_like_srt(text: str) -> bool:
    stripped = text.lstrip()
    return any(SRT_TS_RE.match(line.strip()) for line in stripped.splitlines()[:200])


def srt_to_vtt(text: str) -> str:
    lines = ["WEBVTT", ""]
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if line.strip().isdigit():
            continue
        if SRT_TS_RE.match(line.strip()):
            lines.append(line.replace(",", "."))
        else:
            lines.append(line)
    return "\n".join(lines).rstrip() + "\n"


def candidate_sort_key(candidate: TranscriptCandidate) -> tuple[int, int, int]:
    playable = 0 if candidate.typ in PLAYABLE_TYPES else 1
    captionish = 0 if candidate.rel in {"captions", "subtitles"} else 1
    english = 0 if candidate.lang.lower().startswith("en") else 1
    return (playable, captionish, english)


def normalize_transcript_payload(raw: bytes) -> tuple[str, str]:
    text = html.unescape(raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")).strip()
    if looks_like_vtt(text):
        vtt = text if text.lstrip().upper().startswith("WEBVTT") else f"WEBVTT\n\n{text}\n"
        vtt = normalize_vtt_timestamp_commas(vtt)
        extracted = extract_text_from_vtt(vtt)
        if len(extracted) < 80:
            raise ValueError("transcript text too short after VTT parse")
        return "vtt", vtt
    if looks_like_srt(text):
        extracted = extract_text_from_srt(text)
        if len(extracted) < 80:
            raise ValueError("transcript text too short after SRT parse")
        return "srt", srt_to_vtt(text)
    raise ValueError("payload is not recognizable VTT/SRT")


def episode_filename(release_date: str, track_name: str, guid: str) -> str:
    date_part = "unknown-date"
    if release_date:
        date_part = release_date[:10]
    suffix = slugify(track_name)
    if guid:
        suffix = f"{suffix}-{slugify(guid, max_len=24)}"
    return f"{date_part}-{suffix}.vtt"


def write_report(out_dir: Path, reports: list[ShowReport]) -> None:
    manifest = {
        "generated_at": __import__("datetime").datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "shows": [asdict(report) for report in reports],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    lines = [
        "# Public Podcast Transcript Report",
        "",
        "Seed list: Edison/Podnews-style top U.S. podcast names, checked on 2026-03-08.",
        "",
    ]
    total_files = sum(len(report.transcript_files) for report in reports)
    transcript_shows = sum(1 for report in reports if report.transcript_files)
    lines.append(f"- Shows checked: {len(reports)}")
    lines.append(f"- Shows with downloadable feed transcripts: {transcript_shows}")
    lines.append(f"- Transcript files written: {total_files}")
    lines.append("")
    for report in reports:
        lines.append(f"## {report.collection_name or report.query}")
        lines.append(f"- Query: {report.query}")
        lines.append(f"- Feed: {report.feed_url or 'not found'}")
        lines.append(f"- Transcript support in feed: {'yes' if report.transcript_support else 'no'}")
        lines.append(f"- Episodes considered: {report.episodes_considered}")
        lines.append(f"- Episodes downloaded: {report.episodes_downloaded}")
        lines.append(f"- Existing kept: {report.skipped_existing}")
        if report.errors:
            lines.append(f"- Errors: {' | '.join(report.errors[:5])}")
        if report.transcript_files:
            lines.append("- Files:")
            for entry in report.transcript_files[:10]:
                lines.append(f"  - {entry.local_path} [{entry.source_type}]")
            if len(report.transcript_files) > 10:
                lines.append(f"  - ... {len(report.transcript_files) - 10} more")
        lines.append("")
    (out_dir / "REPORT.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_show_sidecars(show_dir: Path, report: ShowReport, feed_xml: str) -> None:
    if not report.transcript_files:
        return
    show_dir.mkdir(parents=True, exist_ok=True)
    meta = asdict(report)
    meta["podcast_meta_version"] = 1
    meta["podcast_feed_path"] = str((show_dir / "podcast-feed.xml").relative_to(ROOT))
    (show_dir / "podcast-meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (show_dir / "podcast-feed.xml").write_text(feed_xml, encoding="utf-8")


def collect_show(query: str, out_dir: Path, max_episodes: int, refresh: bool) -> ShowReport:
    result = search_show(query)
    if result is None:
        return ShowReport(
            query=query,
            collection_name="",
            collection_id=None,
            artist_name="",
            feed_url="",
            show_slug=slugify(query),
            transcript_support=False,
            episodes_considered=0,
            episodes_downloaded=0,
            skipped_existing=0,
            errors=["itunes search returned no results"],
            transcript_files=[],
        )

    collection_name = str(result.get("collectionName") or query)
    collection_id = int(result["collectionId"]) if result.get("collectionId") else None
    feed_url = str(result.get("feedUrl") or "")
    artist_name = str(result.get("artistName") or "")
    show_slug = slugify(collection_name)
    show_dir = out_dir / show_slug
    errors: list[str] = []
    files: list[EpisodeTranscript] = []
    skipped_existing = 0
    transcript_support = False

    if not feed_url or collection_id is None:
        errors.append("missing feed url or collection id")
        return ShowReport(query, collection_name, collection_id, artist_name, feed_url, show_slug, False, 0, 0, 0, errors, files)

    try:
        xml = http_get(feed_url).decode("utf-8", errors="replace")
    except Exception as exc:
        errors.append(f"feed fetch failed: {exc}")
        return ShowReport(query, collection_name, collection_id, artist_name, feed_url, show_slug, False, 0, 0, 0, errors, files)

    transcript_support = "<podcast:transcript" in xml.lower()
    try:
        root = ET.fromstring(xml)
    except Exception as exc:
        errors.append(f"feed xml parse failed: {exc}")
        return ShowReport(
            query,
            collection_name,
            collection_id,
            artist_name,
            feed_url,
            show_slug,
            transcript_support,
            0,
            0,
            0,
            errors,
            files,
        )

    episodes: list[dict[str, Any]]
    if max_episodes == 0:
        episodes = feed_episode_entries(root, 0)
    else:
        try:
            episodes = lookup_episodes(collection_id, max_episodes)
        except Exception as exc:
            errors.append(f"itunes episode lookup failed: {exc}")
            episodes = feed_episode_entries(root, max_episodes)

    for episode in episodes:
        track_name = str(episode.get("trackName") or "")
        episode_guid = str(episode.get("episodeGuid") or episode.get("trackId") or "")
        release_date = str(episode.get("releaseDate") or "")
        node = find_episode_node(root, episode_guid, track_name)
        if node is None:
            continue
        candidates = extract_transcript_candidates(node)
        if not candidates:
            continue
        candidates.sort(key=candidate_sort_key)
        filename = episode_filename(release_date, track_name, episode_guid)
        output_path = show_dir / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists() and not refresh:
            skipped_existing += 1
            files.append(EpisodeTranscript(
                track_name=track_name,
                episode_guid=episode_guid,
                release_date=release_date,
                source_url="",
                source_type="existing",
                language="",
                local_path=str(output_path.relative_to(ROOT)),
            ))
            continue
        last_error = ""
        for candidate in candidates:
            try:
                payload = http_get(candidate.url)
                source_type, vtt = normalize_transcript_payload(payload)
                output_path.write_text(vtt, encoding="utf-8")
                files.append(EpisodeTranscript(
                    track_name=track_name,
                    episode_guid=episode_guid,
                    release_date=release_date,
                    source_url=candidate.url,
                    source_type=source_type,
                    language=candidate.lang,
                    local_path=str(output_path.relative_to(ROOT)),
                ))
                last_error = ""
                break
            except Exception as exc:
                last_error = f"{candidate.url} ({exc})"
        if last_error:
            errors.append(f"{track_name}: {last_error}")

    report = ShowReport(
        query=query,
        collection_name=collection_name,
        collection_id=collection_id,
        artist_name=artist_name,
        feed_url=feed_url,
        show_slug=show_slug,
        transcript_support=transcript_support,
        episodes_considered=len(episodes),
        episodes_downloaded=sum(1 for item in files if item.source_type != "existing"),
        skipped_existing=skipped_existing,
        errors=errors,
        transcript_files=files,
    )
    write_show_sidecars(show_dir, report, xml)
    return report


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    shows = load_shows(Path(args.shows), int(args.show_limit or 0))
    reports = [collect_show(show, out_dir, int(args.max_episodes_per_show), bool(args.refresh)) for show in shows]
    write_report(out_dir, reports)
    total = sum(len(report.transcript_files) for report in reports)
    print(f"[done] shows={len(reports)} transcript_files={total} out={out_dir}")


if __name__ == "__main__":
    main()
