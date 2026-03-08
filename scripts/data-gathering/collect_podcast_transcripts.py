#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)

OFFICIAL_SHOW_META = {
    "lex-fridman": {
        "show_title": "Lex Fridman Podcast",
        "source_kind": "official_html_wp",
        "archive_url": "https://lexfridman.com/category/transcripts/",
        "homepage_url": "https://lexfridman.com/podcast/",
    },
    "mel-robbins": {
        "show_title": "The Mel Robbins Podcast",
        "source_kind": "official_html",
        "archive_url": "https://www.melrobbins.com/podcast/",
        "homepage_url": "https://www.melrobbins.com/podcast/",
    },
    "tim-ferriss": {
        "show_title": "The Tim Ferriss Show",
        "source_kind": "official_html_wp",
        "archive_url": "https://tim.blog/category/the-tim-ferriss-show-transcripts/",
        "homepage_url": "https://tim.blog/podcast/",
    },
    "this-american-life": {
        "show_title": "This American Life",
        "source_kind": "official_html",
        "archive_url": "https://www.thisamericanlife.org/archive",
        "homepage_url": "https://www.thisamericanlife.org/",
    },
}


def slugify(value: str, max_length: int = 120) -> str:
    value = unescape(value).lower()
    value = re.sub(r"[^\w\s-]", "", value)
    value = re.sub(r"[-\s]+", "-", value).strip("-")
    value = value[:max_length].rstrip("-")
    return value or "untitled"


def clean_text(value: str) -> str:
    value = unescape(value)
    if any(token in value for token in ("â€", "â€™", "â€œ", "â€\x9d", "Â")):
        try:
            repaired = value.encode("latin1").decode("utf-8")
            value = repaired
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    value = value.replace("\xa0", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def parse_clock(value: str) -> int:
    parts = [int(part) for part in value.strip().split(":")]
    if len(parts) == 2:
        minutes, seconds = parts
        return minutes * 60 + seconds
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return hours * 3600 + minutes * 60 + seconds
    raise ValueError(f"Unsupported clock value: {value}")


def format_vtt_time(seconds: int) -> str:
    if seconds < 0:
        seconds = 0
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.000"


def build_vtt(cues: list[tuple[int, str]]) -> str:
    lines = ["WEBVTT", ""]
    if not cues:
        return "\n".join(lines) + "\n"

    for index, (start, text) in enumerate(cues):
        end = cues[index + 1][0] if index + 1 < len(cues) else start + 5
        if end <= start:
            end = start + 5
        lines.append(f"{format_vtt_time(start)} --> {format_vtt_time(end)}")
        lines.extend(text.splitlines() or [""])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def extract_json_ld(soup: BeautifulSoup) -> list[dict]:
    payloads: list[dict] = []
    for script in soup.find_all("script", type="application/ld+json"):
        raw = (script.string or script.get_text() or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            payloads.extend(item for item in data if isinstance(item, dict))
        elif isinstance(data, dict):
            if isinstance(data.get("@graph"), list):
                payloads.extend(item for item in data["@graph"] if isinstance(item, dict))
            else:
                payloads.append(data)
    return payloads


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@dataclass
class TranscriptRecord:
    show_slug: str
    show_title: str
    episode_title: str
    episode_id: str
    published_date: str
    source_kind: str
    source_url: str
    transcript_format: str
    timestamped: bool
    file_path: str

    def to_dict(self) -> dict:
        return {
            "show_slug": self.show_slug,
            "show_title": self.show_title,
            "episode_title": self.episode_title,
            "episode_id": self.episode_id,
            "published_date": self.published_date,
            "source_kind": self.source_kind,
            "source_url": self.source_url,
            "transcript_format": self.transcript_format,
            "timestamped": self.timestamped,
            "file_path": self.file_path,
        }


class PodcastTranscriptCollector:
    def __init__(self, output_root: Path, mel_max_episode: int = 400, limit: int | None = None) -> None:
        self.output_root = output_root
        self.mel_max_episode = mel_max_episode
        self.limit = limit
        self.manifest_name = "collected-manifest.json"
        self.report_name = "COLLECTED_REPORT.md"
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.timeout = 45
        self.records: list[TranscriptRecord] = []

    def get_json(self, url: str, **kwargs) -> object:
        response = self.session.get(url, timeout=self.timeout, **kwargs)
        response.encoding = "utf-8"
        response.raise_for_status()
        return response.json()

    def get_text(self, url: str, allow_404: bool = False, **kwargs) -> str | None:
        response = self.session.get(url, timeout=self.timeout, **kwargs)
        response.encoding = "utf-8"
        if allow_404 and response.status_code == 404:
            return None
        response.raise_for_status()
        return response.text

    def load_existing_records(self) -> list[TranscriptRecord]:
        manifest_path = self.output_root / self.manifest_name
        if not manifest_path.exists():
            return []
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return [TranscriptRecord(**item) for item in data]

    def save_manifest_and_report(self) -> None:
        self.output_root.mkdir(parents=True, exist_ok=True)
        manifest_path = self.output_root / self.manifest_name
        manifest_path.write_text(
            json.dumps([record.to_dict() for record in self.records], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        groups: dict[str, list[TranscriptRecord]] = {}
        for record in self.records:
            groups.setdefault(record.show_slug, []).append(record)

        report_lines = [
            "# Podcast Transcript Report",
            "",
            f"Total transcripts: {len(self.records)}",
            f"Shows: {len(groups)}",
            "",
        ]

        for show_slug in sorted(groups):
            items = sorted(groups[show_slug], key=lambda item: (item.published_date, item.episode_title))
            timestamped = sum(1 for item in items if item.timestamped)
            formats: dict[str, int] = {}
            for item in items:
                formats[item.transcript_format] = formats.get(item.transcript_format, 0) + 1
            format_summary = ", ".join(f"{fmt}={count}" for fmt, count in sorted(formats.items()))
            report_lines.extend(
                [
                    f"## {items[0].show_title}",
                    "",
                    f"- Show slug: `{show_slug}`",
                    f"- Count: {len(items)}",
                    f"- Timestamped: {timestamped}",
                    f"- Formats: {format_summary}",
                    f"- Source kind: `{items[0].source_kind}`",
                    "",
                ]
            )

        write_text(self.output_root / self.report_name, "\n".join(report_lines).rstrip() + "\n")
        self.write_show_sidecars(groups)

    def write_show_sidecars(self, groups: dict[str, list[TranscriptRecord]]) -> None:
        for show_slug, items in groups.items():
            show_dir = self.output_root / show_slug
            show_dir.mkdir(parents=True, exist_ok=True)
            formats: dict[str, int] = {}
            for item in items:
                formats[item.transcript_format] = formats.get(item.transcript_format, 0) + 1
            meta = dict(OFFICIAL_SHOW_META.get(show_slug, {}))
            meta.update(
                {
                    "podcast_meta_version": 1,
                    "show_slug": show_slug,
                    "show_title": items[0].show_title,
                    "transcript_count": len(items),
                    "timestamped_count": sum(1 for item in items if item.timestamped),
                    "formats": formats,
                    "source_urls_sample": [item.source_url for item in items[:20]],
                    "records_path": str((self.output_root / self.manifest_name).relative_to(self.output_root.parent)).replace("\\", "/"),
                    "records": [item.to_dict() for item in items],
                }
            )
            write_text(show_dir / "podcast-meta.json", json.dumps(meta, indent=2, ensure_ascii=False) + "\n")

    def merge_records(self, new_records: Iterable[TranscriptRecord], show_slugs: set[str]) -> None:
        existing = self.load_existing_records()
        preserved = [record for record in existing if record.show_slug not in show_slugs]
        self.records = preserved + list(new_records)
        self.records.sort(key=lambda item: (item.show_slug, item.published_date, item.episode_title))
        self.save_manifest_and_report()

    def collect_lex(self) -> list[TranscriptRecord]:
        show_slug = "lex-fridman"
        show_title = "Lex Fridman Podcast"
        category_id = 3393
        records: list[TranscriptRecord] = []

        url = "https://lexfridman.com/wp-json/wp/v2/posts"
        params = {
            "categories": category_id,
            "per_page": 100,
            "orderby": "date",
            "order": "desc",
            "_fields": "id,date,slug,link,title,content",
            "page": 1,
        }

        first = self.session.get(url, params=params, timeout=self.timeout)
        first.encoding = "utf-8"
        first.raise_for_status()
        total_pages = int(first.headers.get("X-WP-TotalPages", "1"))

        for page in range(1, total_pages + 1):
            params["page"] = page
            data = self.get_json(url, params=params)
            for post in data:
                content_html = post["content"]["rendered"]
                soup = BeautifulSoup(content_html, "lxml")
                cues: list[tuple[int, str]] = []
                for segment in soup.select("div.ts-segment"):
                    name = clean_text(segment.select_one(".ts-name").get_text(" ", strip=True)) if segment.select_one(".ts-name") else ""
                    timestamp_tag = segment.select_one(".ts-timestamp")
                    text_tag = segment.select_one(".ts-text")
                    if not timestamp_tag or not text_tag:
                        continue
                    timestamp_match = re.search(r"\(([\d:]+)\)", timestamp_tag.get_text(" ", strip=True))
                    if not timestamp_match:
                        continue
                    start = parse_clock(timestamp_match.group(1))
                    text = clean_text(text_tag.get_text(" ", strip=True))
                    if name:
                        text = f"{name}: {text}"
                    cues.append((start, text))

                if not cues:
                    continue

                raw_title = clean_text(post["title"]["rendered"])
                episode_title = raw_title.removeprefix("Transcript for ").strip()
                filename = f"{post['date'][:10]}-{slugify(episode_title)}.vtt"
                relative_path = Path(show_slug) / filename
                write_text(self.output_root / relative_path, build_vtt(cues))
                records.append(
                    TranscriptRecord(
                        show_slug=show_slug,
                        show_title=show_title,
                        episode_title=episode_title,
                        episode_id=post["slug"],
                        published_date=post["date"][:10],
                        source_kind="official_html_wp",
                        source_url=post["link"],
                        transcript_format="vtt",
                        timestamped=True,
                        file_path=str(relative_path).replace("\\", "/"),
                    )
                )
                print(f"[lex] {episode_title}", flush=True)
                if self.limit and len(records) >= self.limit:
                    return records
        return records

    def collect_tim(self) -> list[TranscriptRecord]:
        show_slug = "tim-ferriss"
        show_title = "The Tim Ferriss Show"
        category_id = 41
        records: list[TranscriptRecord] = []

        url = "https://tim.blog/wp-json/wp/v2/posts"
        params = {
            "categories": category_id,
            "per_page": 100,
            "orderby": "date",
            "order": "desc",
            "_fields": "id,date,slug,link,title,content",
            "page": 1,
        }

        first = self.session.get(url, params=params, timeout=self.timeout)
        first.encoding = "utf-8"
        first.raise_for_status()
        total_pages = int(first.headers.get("X-WP-TotalPages", "1"))

        for page in range(1, total_pages + 1):
            params["page"] = page
            data = self.get_json(url, params=params)
            for post in data:
                raw_title = clean_text(post["title"]["rendered"])
                episode_title = raw_title.removeprefix("The Tim Ferriss Show Transcripts:").strip()
                content_html = post["content"]["rendered"]
                text = clean_text(BeautifulSoup(content_html, "lxml").get_text("\n", strip=True))

                start_index = text.find("Transcripts may contain")
                if start_index != -1:
                    text = text[start_index:]
                speaker_match = re.search(r"\n[A-Z][A-Za-z0-9 .,'’&/-]{1,80}:\n?", text)
                if speaker_match:
                    text = text[speaker_match.start() + 1 :].strip()

                filename = f"{post['date'][:10]}-{slugify(episode_title)}.txt"
                relative_path = Path(show_slug) / filename
                write_text(self.output_root / relative_path, text + "\n")
                records.append(
                    TranscriptRecord(
                        show_slug=show_slug,
                        show_title=show_title,
                        episode_title=episode_title,
                        episode_id=post["slug"],
                        published_date=post["date"][:10],
                        source_kind="official_html_wp",
                        source_url=post["link"],
                        transcript_format="txt",
                        timestamped=False,
                        file_path=str(relative_path).replace("\\", "/"),
                    )
                )
                print(f"[tim] {episode_title}", flush=True)
                if self.limit and len(records) >= self.limit:
                    return records
        return records

    def collect_mel(self) -> list[TranscriptRecord]:
        show_slug = "mel-robbins"
        show_title = "The Mel Robbins Podcast"
        records: list[TranscriptRecord] = []

        for episode_number in range(1, self.mel_max_episode + 1):
            url = f"https://www.melrobbins.com/episode/episode-{episode_number}/"
            html = self.get_text(url, allow_404=True)
            if html is None:
                continue

            soup = BeautifulSoup(html, "lxml")
            cues: list[tuple[int, str]] = []
            for block in soup.select("div[id^=clip-]"):
                toggle = block.select_one("[data-timestamp]")
                if not toggle:
                    continue
                timestamp = toggle.get("data-timestamp", "").strip()
                if not timestamp:
                    continue
                paragraphs: list[str] = []
                for paragraph in block.select(".prose.type-p p"):
                    text = clean_text(paragraph.get_text(" ", strip=True))
                    if not text or text.lower() in {"read more", "read less"}:
                        continue
                    if text == "&":
                        continue
                    paragraphs.append(text)
                if not paragraphs:
                    continue
                text = "\n".join(paragraphs)
                cues.append((parse_clock(timestamp), text))

            if not cues:
                continue

            title = soup.title.get_text(" ", strip=True) if soup.title else f"Episode {episode_number}"
            title = re.sub(r"\s*-\s*Mel Robbins\s*$", "", title).strip()

            published_date = ""
            for payload in extract_json_ld(soup):
                date_value = payload.get("datePublished") or payload.get("dateCreated")
                if date_value:
                    published_date = str(date_value)[:10]
                    break
            if not published_date:
                published_date = f"episode-{episode_number:03d}"

            filename = f"{published_date}-{slugify(title)}.vtt"
            relative_path = Path(show_slug) / filename
            write_text(self.output_root / relative_path, build_vtt(cues))
            records.append(
                TranscriptRecord(
                    show_slug=show_slug,
                    show_title=show_title,
                    episode_title=title,
                    episode_id=f"episode-{episode_number}",
                    published_date=published_date,
                    source_kind="official_html",
                    source_url=url,
                    transcript_format="vtt",
                    timestamped=True,
                    file_path=str(relative_path).replace("\\", "/"),
                )
            )
            print(f"[mel] {episode_number}: {title}", flush=True)
            time.sleep(0.15)
            if self.limit and len(records) >= self.limit:
                return records

        return records

    def collect_tal(self) -> list[TranscriptRecord]:
        show_slug = "this-american-life"
        show_title = "This American Life"
        records: list[TranscriptRecord] = []
        seen_links: set[str] = set()
        page = 0

        while True:
            archive_url = "https://www.thisamericanlife.org/archive"
            if page:
                archive_url = f"{archive_url}?page={page}"
            try:
                html = self.get_text(archive_url)
            except requests.RequestException:
                break
            if not html:
                break

            soup = BeautifulSoup(html, "lxml")
            new_links: list[str] = []
            for anchor in soup.select("a[href]"):
                href = anchor.get("href", "")
                if re.match(r"^/\d+/.+", href) and href not in seen_links:
                    seen_links.add(href)
                    new_links.append(href)

            if not new_links:
                break

            for href in new_links:
                url = f"https://www.thisamericanlife.org{href}"
                try:
                    episode_html = self.get_text(url)
                except requests.RequestException:
                    print(f"[tal-skip] {url}", flush=True)
                    continue
                if not episode_html:
                    continue
                episode_soup = BeautifulSoup(episode_html, "lxml")
                content_blocks = episode_soup.select("div.content")
                if not content_blocks:
                    continue
                transcript_block = max(content_blocks, key=lambda block: len(block.get_text(" ", strip=True)))
                transcript_text = clean_text(transcript_block.get_text("\n", strip=True))
                if len(transcript_text) < 200:
                    continue

                title = episode_soup.title.get_text(" ", strip=True) if episode_soup.title else href.strip("/").replace("-", " ")
                title = re.sub(r"\s*\|\s*This American Life\s*$", "", title).strip()

                published_date = ""
                date_match = re.search(r"([A-Z][a-z]+ \d{1,2}, \d{4})", episode_soup.get_text(" ", strip=True))
                if date_match:
                    try:
                        published_date = time.strftime("%Y-%m-%d", time.strptime(date_match.group(1), "%B %d, %Y"))
                    except ValueError:
                        published_date = ""
                if not published_date:
                    published_date = "undated"

                filename = f"{published_date}-{slugify(title)}.txt"
                relative_path = Path(show_slug) / filename
                write_text(self.output_root / relative_path, transcript_text + "\n")
                records.append(
                    TranscriptRecord(
                        show_slug=show_slug,
                        show_title=show_title,
                        episode_title=title,
                        episode_id=href.strip("/").split("/")[0],
                        published_date=published_date,
                        source_kind="official_html",
                        source_url=url,
                        transcript_format="txt",
                        timestamped=False,
                        file_path=str(relative_path).replace("\\", "/"),
                    )
                )
                print(f"[tal] {title}", flush=True)
                if self.limit and len(records) >= self.limit:
                    return records

            if 'pager-next' not in html and 'Load More' not in html:
                break
            page += 1
        return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect public podcast transcripts into podcast-transcripts/.")
    parser.add_argument(
        "--shows",
        default="lex,mel,tim",
        help="Comma-separated list of sources to collect: lex, mel, tim, tal",
    )
    parser.add_argument(
        "--out-dir",
        default="podcast-transcripts",
        help="Output directory for transcripts and reports.",
    )
    parser.add_argument(
        "--mel-max-episode",
        type=int,
        default=400,
        help="Highest Mel Robbins episode number to probe.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional per-show item limit for smoke tests or partial pulls.",
    )
    args = parser.parse_args()

    selected = {item.strip() for item in args.shows.split(",") if item.strip()}
    valid = {"lex", "mel", "tim", "tal"}
    unknown = selected - valid
    if unknown:
        parser.error(f"Unknown shows: {', '.join(sorted(unknown))}")

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    collector = PodcastTranscriptCollector(
        Path(args.out_dir),
        mel_max_episode=args.mel_max_episode,
        limit=args.limit,
    )
    new_records: list[TranscriptRecord] = []
    if "lex" in selected:
        new_records.extend(collector.collect_lex())
    if "mel" in selected:
        new_records.extend(collector.collect_mel())
    if "tim" in selected:
        new_records.extend(collector.collect_tim())
    if "tal" in selected:
        new_records.extend(collector.collect_tal())

    show_slug_map = {
        "lex": "lex-fridman",
        "mel": "mel-robbins",
        "tim": "tim-ferriss",
        "tal": "this-american-life",
    }
    collector.merge_records(new_records, {show_slug_map[item] for item in selected})
    print(
        f"Collected {len(new_records)} transcripts into {collector.output_root}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
