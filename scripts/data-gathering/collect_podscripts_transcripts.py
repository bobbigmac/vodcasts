#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import time
import threading
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = ROOT / "podcast-transcripts"
BASE_URL = "https://podscripts.co"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)
GENERIC_TITLE = "PodScripts.co - Podcast transcripts and discussion"
CLOCK_RE = re.compile(r"(\d{2}:\d{2}:\d{2})")
DATE_RE = re.compile(r"Episode Date:\s*(.+)")


@dataclass
class EpisodeRecord:
    show_slug: str
    show_title: str
    source_kind: str
    source_url: str
    published_date: str
    episode_title: str
    transcript_format: str
    timestamped: bool
    local_path: str
    podcast_source_meta_path: str


@dataclass
class ShowSummary:
    podscripts_id: int
    show_title: str
    show_slug: str
    podcast_url: str
    discovered_episode_links: int
    transcript_files: int
    skipped_existing: int
    errors: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect timestamped podcast transcripts from podscripts.co.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output root for podcast transcript folders.")
    parser.add_argument("--workers", type=int, default=8, help="Concurrent podcast workers.")
    parser.add_argument("--pod-limit", type=int, default=0, help="Limit podcasts processed (0 = all discovered podcasts).")
    parser.add_argument(
        "--episode-limit-per-podcast",
        type=int,
        default=0,
        help="Limit episodes collected from each podcast page (0 = all visible episode links on the page).",
    )
    parser.add_argument("--show-slug", action="append", default=[], help="Only process matching show slug(s).")
    parser.add_argument("--refresh", action="store_true", help="Re-download transcripts even if local file already exists.")
    parser.add_argument(
        "--min-request-interval",
        type=float,
        default=0.35,
        help="Minimum seconds between HTTP requests across all workers.",
    )
    parser.add_argument("--max-retries", type=int, default=5, help="Retries for 429/5xx responses.")
    return parser.parse_args()


def slugify(value: str, max_length: int = 140) -> str:
    text = unicodedata.normalize("NFKD", unescape(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.replace("&", " and ")
    text = text.replace("'", "")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return (text[:max_length].rstrip("-") or "untitled")


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value or "")).strip()


def parse_clock(value: str) -> int:
    hours, minutes, seconds = [int(part) for part in value.split(":")]
    return (hours * 3600) + (minutes * 60) + seconds


def format_vtt_time(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.000"


def build_vtt(cues: Iterable[tuple[int, str]]) -> str:
    ordered = sorted(cues, key=lambda item: item[0])
    lines = ["WEBVTT", ""]
    if not ordered:
        return "\n".join(lines) + "\n"
    for index, (start_seconds, text) in enumerate(ordered):
        end_seconds = ordered[index + 1][0] if index + 1 < len(ordered) else start_seconds + 5
        if end_seconds <= start_seconds:
            end_seconds = start_seconds + 5
        lines.append(f"{format_vtt_time(start_seconds)} --> {format_vtt_time(end_seconds)}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def parse_episode_date(raw_value: str) -> str:
    value = normalize_space(raw_value)
    if not value:
        return ""
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return value


def extract_title_from_page(soup: BeautifulSoup, show_title: str) -> str:
    meta_title = soup.find("meta", property="og:title")
    if meta_title and meta_title.get("content"):
        title = normalize_space(meta_title["content"])
        prefix = f"{show_title} - "
        suffix = " Transcript and Discussion"
        if title.startswith(prefix) and title.endswith(suffix):
            return title[len(prefix):-len(suffix)].strip()
    page_title = normalize_space((soup.title.string if soup.title and soup.title.string else ""))
    prefix = f"{show_title} - "
    suffix = " Transcript and Discussion"
    if page_title.startswith(prefix) and page_title.endswith(suffix):
        return page_title[len(prefix):-len(suffix)].strip()
    heading = soup.find(["h1", "h2"], string=True)
    return normalize_space(heading.get_text(" ", strip=True) if heading else page_title)


def unique_strings(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def record_key(record: EpisodeRecord) -> str:
    return record.source_url or record.local_path


class PodscriptsCollector:
    def __init__(
        self,
        out_dir: Path,
        *,
        workers: int,
        pod_limit: int,
        episode_limit_per_podcast: int,
        show_slugs: list[str],
        refresh: bool,
        min_request_interval: float,
        max_retries: int,
    ) -> None:
        self.out_dir = out_dir.resolve()
        self.workers = max(1, workers)
        self.pod_limit = max(0, pod_limit)
        self.episode_limit_per_podcast = max(0, episode_limit_per_podcast)
        self.show_slugs = {slug.strip().lower() for slug in show_slugs if slug.strip()}
        self.refresh = refresh
        self.timeout = 45
        self.min_request_interval = max(0.0, float(min_request_interval))
        self.max_retries = max(1, int(max_retries))
        self.records: list[EpisodeRecord] = []
        self.show_summaries: list[ShowSummary] = []
        self.catalog: list[dict] = []
        self.catalog_all: list[dict] = []
        self.catalog_meta: dict[str, object] = {}
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self._rate_lock = threading.Lock()
        self._last_request_started_at = 0.0
        self.manifest_path = self.out_dir / "podscripts-manifest.json"
        self.report_path = self.out_dir / "PODSCRIPTS_REPORT.md"
        self.catalog_path = self.out_dir / "podscripts-catalog.json"

    def load_existing_records(self) -> list[EpisodeRecord]:
        merged: dict[str, EpisodeRecord] = {}

        if self.manifest_path.exists():
            try:
                data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            record = EpisodeRecord(**item)
                            if record.local_path and not (ROOT / record.local_path).exists():
                                continue
                            merged[record_key(record)] = record
            except Exception:
                pass

        for meta_path in self.out_dir.glob("*/podscripts-podcast-meta.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            show_dir = meta_path.parent
            show_slug = show_dir.name
            show_title = str(meta.get("show_title") or show_slug.replace("-", " ").title())
            meta_path_rel = str(meta_path.relative_to(ROOT)).replace("\\", "/")
            known_by_local_path: dict[str, EpisodeRecord] = {}
            records = meta.get("records")
            if isinstance(records, list):
                for item in records:
                    if not isinstance(item, dict):
                        continue
                    try:
                        record = EpisodeRecord(**item)
                    except TypeError:
                        continue
                    if record.local_path and not (ROOT / record.local_path).exists():
                        continue
                    merged[record_key(record)] = record
                    known_by_local_path[record.local_path] = record

            for transcript_path in show_dir.glob("*-podscripts.vtt"):
                local_path = str(transcript_path.relative_to(ROOT)).replace("\\", "/")
                existing = known_by_local_path.get(local_path)
                if existing is not None:
                    merged[record_key(existing)] = existing
                    continue
                filename = transcript_path.stem
                published_date = ""
                if re.match(r"^\d{4}-\d{2}-\d{2}-", filename):
                    published_date = filename[:10]
                episode_slug = filename
                if published_date:
                    episode_slug = episode_slug[11:]
                if episode_slug.endswith("-podscripts"):
                    episode_slug = episode_slug[:-11]
                episode_title = episode_slug.replace("-", " ").strip().title()
                synthesized = EpisodeRecord(
                    show_slug=show_slug,
                    show_title=show_title,
                    source_kind="podscripts_html",
                    source_url="",
                    published_date=published_date,
                    episode_title=episode_title,
                    transcript_format="vtt",
                    timestamped=True,
                    local_path=local_path,
                    podcast_source_meta_path=meta_path_rel,
                )
                merged[record_key(synthesized)] = synthesized

        return list(merged.values())

    def get_text(self, url: str) -> str:
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            with self._rate_lock:
                now = time.monotonic()
                wait_for = self.min_request_interval - (now - self._last_request_started_at)
                if wait_for > 0:
                    time.sleep(wait_for)
                self._last_request_started_at = time.monotonic()
            try:
                response = self.session.get(url, timeout=self.timeout)
                response.encoding = "utf-8"
                if response.status_code == 429 or 500 <= response.status_code < 600:
                    response.raise_for_status()
                response.raise_for_status()
                return response.text
            except requests.HTTPError as exc:
                last_error = exc
                status_code = exc.response.status_code if exc.response is not None else 0
                if status_code == 429 or 500 <= status_code < 600:
                    time.sleep(min(12.0, (2 ** attempt) * 0.75))
                    continue
                raise
            except Exception as exc:
                last_error = exc
                time.sleep(min(12.0, (2 ** attempt) * 0.5))
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"failed to fetch {url}")

    def fetch_catalog(self) -> list[dict]:
        html = self.get_text(f"{BASE_URL}/")
        soup = BeautifulSoup(html, "html.parser")
        podsearch = soup.find("podsearch")
        if podsearch is None:
            raise RuntimeError("podscripts homepage did not expose the podsearch catalog")
        pods_attr = podsearch.get("pods") or "[]"
        categories_attr = podsearch.get("categories") or "[]"
        self.catalog_all = json.loads(pods_attr)
        self.catalog_meta = {
            "source_url": f"{BASE_URL}/",
            "catalog_generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "podcast_count": len(self.catalog_all),
            "episode_count": int(podsearch.get("ep-count") or 0),
            "categories": json.loads(categories_attr),
        }
        self.catalog = list(self.catalog_all)
        if self.show_slugs:
            self.catalog = [item for item in self.catalog if slugify(str(item.get("podcast_title") or "")) in self.show_slugs]
        if self.pod_limit > 0:
            self.catalog = self.catalog[:self.pod_limit]
        return self.catalog

    def is_valid_podcast_page(self, html: str) -> bool:
        soup = BeautifulSoup(html, "html.parser")
        title = normalize_space(soup.title.string if soup.title and soup.title.string else "")
        return title != GENERIC_TITLE and "Episode Date:" in html

    def extract_episode_links(self, html: str, show_slug: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        prefix = f"/podcasts/{show_slug}/"
        links: list[str] = []
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            if not href.startswith(prefix):
                continue
            if href.rstrip("/") == prefix.rstrip("/"):
                continue
            if "facebook.com" in href or "twitter.com" in href:
                continue
            if href.rstrip("/").count("/") < 3:
                continue
            links.append(href.rstrip("/"))
        links = unique_strings(links)
        if self.episode_limit_per_podcast > 0:
            links = links[:self.episode_limit_per_podcast]
        return links

    def episode_filename(self, published_date: str, episode_title: str) -> str:
        date_part = published_date[:10] if published_date else "unknown-date"
        title_part = slugify(episode_title, max_length=110)
        return f"{date_part}-{title_part}-podscripts.vtt"

    def parse_episode(self, show_title: str, show_slug: str, episode_url: str, show_dir: Path) -> tuple[EpisodeRecord | None, bool]:
        html = self.get_text(episode_url)
        soup = BeautifulSoup(html, "html.parser")

        episode_title = extract_title_from_page(soup, show_title)
        date_text = ""
        for span in soup.find_all(["span", "p", "div"]):
            text = normalize_space(span.get_text(" ", strip=True))
            if text.startswith("Episode Date:"):
                date_text = text.split("Episode Date:", 1)[1].strip()
                break
        published_date = parse_episode_date(date_text)

        transcript = soup.select_one(".podcast-transcript")
        if transcript is None:
            return None, False

        cues: list[tuple[int, str]] = []
        for block in transcript.select(".single-sentence"):
            ts_node = block.select_one(".pod_timestamp_indicator")
            if ts_node is None:
                continue
            ts_match = CLOCK_RE.search(ts_node.get_text(" ", strip=True))
            if ts_match is None:
                continue
            parts = [
                normalize_space(node.get_text(" ", strip=True))
                for node in block.select(".pod_text")
            ]
            text = normalize_space(" ".join(part for part in parts if part))
            if not text:
                continue
            cues.append((parse_clock(ts_match.group(1)), text))
        if not cues:
            return None, False

        local_filename = self.episode_filename(published_date, episode_title)
        output_path = show_dir / local_filename
        output_path.parent.mkdir(parents=True, exist_ok=True)
        existed_before = output_path.exists()
        if not existed_before or self.refresh:
            output_path.write_text(build_vtt(cues), encoding="utf-8")

        meta_filename = "podscripts-podcast-meta.json"
        return (
            EpisodeRecord(
                show_slug=show_slug,
                show_title=show_title,
                source_kind="podscripts_html",
                source_url=episode_url,
                published_date=published_date,
                episode_title=episode_title,
                transcript_format="vtt",
                timestamped=True,
                local_path=str(output_path.relative_to(ROOT)).replace("\\", "/"),
                podcast_source_meta_path=str((show_dir / meta_filename).relative_to(ROOT)).replace("\\", "/"),
            ),
            existed_before,
        )

    def collect_show(self, pod: dict) -> tuple[ShowSummary, list[EpisodeRecord]]:
        pod_id = int(pod.get("id") or 0)
        show_title = normalize_space(str(pod.get("podcast_title") or ""))
        show_slug = slugify(show_title)
        podcast_url = f"{BASE_URL}/podcasts/{show_slug}/"
        errors: list[str] = []
        show_dir = self.out_dir / show_slug

        try:
            html = self.get_text(podcast_url)
        except Exception as exc:
            return ShowSummary(pod_id, show_title, show_slug, podcast_url, 0, 0, 0, [f"podcast page fetch failed: {exc}"]), []
        if not self.is_valid_podcast_page(html):
            return ShowSummary(pod_id, show_title, show_slug, podcast_url, 0, 0, 0, ["podcast page not found for derived slug"]), []

        episode_links = self.extract_episode_links(html, show_slug)
        records: list[EpisodeRecord] = []
        skipped_existing = 0
        for relative_link in episode_links:
            episode_url = f"{BASE_URL}{relative_link}"
            try:
                record, existed_before = self.parse_episode(show_title, show_slug, episode_url, show_dir)
            except Exception as exc:
                errors.append(f"{episode_url}: {exc}")
                continue
            if record is None:
                errors.append(f"{episode_url}: missing transcript blocks")
                continue
            if existed_before and not self.refresh:
                skipped_existing += 1
            records.append(record)

        if records:
            self.write_show_sidecar(
                show_dir=show_dir,
                pod_id=pod_id,
                show_title=show_title,
                show_slug=show_slug,
                podcast_url=podcast_url,
                episode_links=episode_links,
                records=records,
                errors=errors,
            )

        return (
            ShowSummary(
                podscripts_id=pod_id,
                show_title=show_title,
                show_slug=show_slug,
                podcast_url=podcast_url,
                discovered_episode_links=len(episode_links),
                transcript_files=len(records),
                skipped_existing=skipped_existing,
                errors=errors,
            ),
            records,
        )

    def write_show_sidecar(
        self,
        *,
        show_dir: Path,
        pod_id: int,
        show_title: str,
        show_slug: str,
        podcast_url: str,
        episode_links: list[str],
        records: list[EpisodeRecord],
        errors: list[str],
    ) -> None:
        show_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "podcast_meta_version": 1,
            "source_kind": "podscripts_html",
            "source_homepage": BASE_URL,
            "podscripts_podcast_id": pod_id,
            "show_title": show_title,
            "show_slug": show_slug,
            "podcast_url": podcast_url,
            "transcript_count": len(records),
            "timestamped_count": len(records),
            "visible_episode_links": len(episode_links),
            "source_urls_sample": [record.source_url for record in records[:20]],
            "records_path": str(self.manifest_path.relative_to(ROOT)).replace("\\", "/"),
            "records": [],
            "errors": errors[:50],
        }
        existing_path = show_dir / "podscripts-podcast-meta.json"
        merged_records: dict[str, EpisodeRecord] = {}
        if existing_path.exists():
            try:
                existing_meta = json.loads(existing_path.read_text(encoding="utf-8"))
                existing_records = existing_meta.get("records")
                if isinstance(existing_records, list):
                    for item in existing_records:
                        if not isinstance(item, dict):
                            continue
                        try:
                            record = EpisodeRecord(**item)
                        except TypeError:
                            continue
                        merged_records[record.local_path] = record
            except Exception:
                pass
        for record in records:
            merged_records[record.local_path] = record
        meta["transcript_count"] = len(merged_records)
        meta["timestamped_count"] = len(merged_records)
        meta["source_urls_sample"] = [record.source_url for record in list(merged_records.values())[:20] if record.source_url]
        meta["records"] = [asdict(record) for record in sorted(merged_records.values(), key=lambda item: (item.published_date, item.episode_title, item.local_path))]
        (show_dir / "podscripts-podcast-meta.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def save(self) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        merged_records = {record_key(record): record for record in self.load_existing_records()}
        for record in self.records:
            merged_records[record_key(record)] = record
        merged_list = sorted(
            merged_records.values(),
            key=lambda item: (item.show_slug, item.published_date, item.episode_title, item.source_url),
        )

        self.catalog_path.write_text(
            json.dumps({"meta": self.catalog_meta, "podcasts": self.catalog_all}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        self.manifest_path.write_text(
            json.dumps([asdict(record) for record in merged_list], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        grouped: dict[str, list[EpisodeRecord]] = {}
        for record in merged_list:
            grouped.setdefault(record.show_slug, []).append(record)

        report_lines = [
            "# Podscripts Transcript Report",
            "",
            f"Generated: {datetime.utcnow().isoformat(timespec='seconds')}Z",
            f"Catalog podcasts discovered: {self.catalog_meta.get('podcast_count', 0)}",
            f"Catalog episodes reported by source: {self.catalog_meta.get('episode_count', 0)}",
            f"Podcasts processed: {len(self.show_summaries)}",
            f"Transcript files captured: {len(merged_list)}",
            "",
        ]
        report_lines.append(f"Podcasts with captured transcripts: {len(grouped)}")
        report_lines.append("")
        summary_by_slug = {summary.show_slug: summary for summary in self.show_summaries if summary.transcript_files}
        for show_slug, records in grouped.items():
            show_dir = self.out_dir / show_slug
            meta_path = show_dir / "podscripts-podcast-meta.json"
            existing_meta: dict[str, object] = {}
            if meta_path.exists():
                try:
                    existing_meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    existing_meta = {}
            summary = summary_by_slug.get(show_slug)
            source_urls_sample = [record.source_url for record in records if record.source_url][:20]
            meta = {
                "podcast_meta_version": 1,
                "source_kind": "podscripts_html",
                "source_homepage": BASE_URL,
                "podscripts_podcast_id": existing_meta.get("podscripts_podcast_id", 0),
                "show_title": existing_meta.get("show_title") or records[0].show_title,
                "show_slug": show_slug,
                "podcast_url": existing_meta.get("podcast_url") or f"{BASE_URL}/podcasts/{show_slug}/",
                "transcript_count": len(records),
                "timestamped_count": len(records),
                "visible_episode_links": summary.discovered_episode_links if summary else existing_meta.get("visible_episode_links", len(records)),
                "source_urls_sample": source_urls_sample,
                "records_path": str(self.manifest_path.relative_to(ROOT)).replace("\\", "/"),
                "records": [asdict(record) for record in records],
                "errors": (summary.errors[:50] if summary and summary.errors else existing_meta.get("errors", [])),
            }
            meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        for show_slug, records in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
            summary = summary_by_slug.get(show_slug)
            report_lines.append(f"## {records[0].show_title}")
            report_lines.append(f"- Show slug: `{show_slug}`")
            report_lines.append(f"- Podcast URL: {summary.podcast_url if summary else f'{BASE_URL}/podcasts/{show_slug}/'}")
            if summary:
                report_lines.append(f"- Visible episode links: {summary.discovered_episode_links}")
            report_lines.append(f"- Transcript files: {len(records)}")
            if summary:
                report_lines.append(f"- Existing kept: {summary.skipped_existing}")
                if summary.errors:
                    report_lines.append(f"- Errors: {' | '.join(summary.errors[:3])}")
            report_lines.append("")
        self.report_path.write_text("\n".join(report_lines).rstrip() + "\n", encoding="utf-8")

    def run(self) -> None:
        catalog = self.fetch_catalog()
        self.out_dir.mkdir(parents=True, exist_ok=True)

        completed = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = [executor.submit(self.collect_show, pod) for pod in catalog]
            for future in concurrent.futures.as_completed(futures):
                summary, records = future.result()
                self.show_summaries.append(summary)
                self.records.extend(records)
                completed += 1
                if completed % 25 == 0:
                    self.save()
                    print(
                        f"[checkpoint] podcasts={completed}/{len(catalog)} "
                        f"captured={len(self.records)}"
                    )
        self.save()


def main() -> None:
    args = parse_args()
    collector = PodscriptsCollector(
        out_dir=Path(args.out_dir),
        workers=int(args.workers),
        pod_limit=int(args.pod_limit),
        episode_limit_per_podcast=int(args.episode_limit_per_podcast),
        show_slugs=list(args.show_slug or []),
        refresh=bool(args.refresh),
        min_request_interval=float(args.min_request_interval),
        max_retries=int(args.max_retries),
    )
    collector.run()
    print(
        f"[done] podcasts={len(collector.show_summaries)} "
        f"transcript_files={len(collector.records)} "
        f"out={collector.out_dir}"
    )


if __name__ == "__main__":
    main()
