#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import math
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import requests

from collect_public_transcripts import (
    USER_AGENT,
    candidate_sort_key,
    episode_filename,
    extract_transcript_candidates,
    feed_episode_entries,
    find_episode_node,
    normalize_transcript_payload,
    slugify,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = ROOT / "podcast-transcripts"
DEFAULT_DB_PATH = ROOT / "podcastindex-feeds" / "podcastindex_feeds.db"
DEFAULT_STATE_DB = ROOT / "podcast-transcripts" / "podcastindex-miner-state.sqlite"


def format_bytes(num_bytes: float) -> str:
    value = float(max(0.0, num_bytes))
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} PB"


def format_duration(seconds: float) -> str:
    if not math.isfinite(seconds) or seconds < 0:
        return "unknown"
    total = int(round(seconds))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours or parts:
        parts.append(f"{hours}h")
    if minutes or parts:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


@dataclass
class FeedCandidate:
    feed_id: int
    url: str
    title: str
    host: str
    episode_count: int
    popularity_score: int
    newest_item_pubdate: int
    podcast_guid: str
    metadata: dict[str, Any]


@dataclass
class TranscriptRecord:
    feed_id: int
    feed_url: str
    show_slug: str
    show_title: str
    episode_title: str
    episode_guid: str
    published_date: str
    source_url: str
    source_type: str
    language: str
    local_path: str


@dataclass
class FeedOutcome:
    feed_id: int
    feed_url: str
    show_slug: str
    show_title: str
    host: str
    metadata: dict[str, Any]
    transcript_support: bool
    episodes_considered: int
    episodes_downloaded: int
    skipped_existing: int
    errors: list[str]
    transcript_files: list[TranscriptRecord]
    feed_xml: str
    checked_at: int


class ThreadLocalSessions:
    def __init__(self) -> None:
        self._local = threading.local()

    def get(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update({
                "User-Agent": USER_AGENT,
                "Accept": "application/json, application/xml, text/xml, text/plain, */*",
            })
            self._local.session = session
        return session


class HostLimiter:
    def __init__(self, per_host: int) -> None:
        self.per_host = max(1, per_host)
        self._lock = threading.Lock()
        self._semaphores: dict[str, threading.Semaphore] = {}

    def semaphore_for(self, host: str) -> threading.Semaphore:
        host = (host or "").lower() or "__unknown__"
        with self._lock:
            sem = self._semaphores.get(host)
            if sem is None:
                sem = threading.Semaphore(self.per_host)
                self._semaphores[host] = sem
            return sem


class PodcastIndexMiner:
    def __init__(
        self,
        db_path: Path,
        out_dir: Path,
        state_db: Path,
        *,
        workers: int,
        per_host: int,
        limit_feeds: int,
        min_popularity: int,
        refresh: bool,
        hosts: list[str],
        feed_timeout: int,
        transcript_timeout: int,
        progress_every: int,
        progress_log: Path | None,
        status_json: Path | None,
    ) -> None:
        self.db_path = db_path.resolve()
        self.out_dir = out_dir.resolve()
        self.state_db = state_db.resolve()
        self.workers = max(1, workers)
        self.per_host = max(1, per_host)
        self.limit_feeds = max(0, limit_feeds)
        self.min_popularity = max(0, min_popularity)
        self.refresh = refresh
        self.hosts = [host.strip().lower() for host in hosts if host.strip()]
        self.feed_timeout = max(5, feed_timeout)
        self.transcript_timeout = max(5, transcript_timeout)
        self.progress_every = max(5, progress_every)
        self.progress_log = progress_log.resolve() if progress_log else None
        self.status_json = status_json.resolve() if status_json else None
        self.sessions = ThreadLocalSessions()
        self.host_limiter = HostLimiter(self.per_host)
        self.manifest_path = self.out_dir / "podcastindex-manifest.json"
        self.report_path = self.out_dir / "PODCASTINDEX_REPORT.md"
        self.retryable_statuses = {408, 425, 429, 500, 502, 503, 504}

    def emit_lines(self, lines: list[str]) -> None:
        if self.progress_log:
            self.progress_log.parent.mkdir(parents=True, exist_ok=True)
            with self.progress_log.open("a", encoding="utf-8") as handle:
                for line in lines:
                    handle.write(line + "\n")
        for line in lines:
            print(line, flush=True)

    def write_status_json(self, payload: dict[str, Any]) -> None:
        if not self.status_json:
            return
        self.status_json.parent.mkdir(parents=True, exist_ok=True)
        self.status_json.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def emit_initializing(self, message: str) -> None:
        self.emit_lines([f"[init] {message}", ""])
        self.write_status_json(
            {
                "phase": "initializing",
                "message": message,
                "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "workers": self.workers,
                "per_host": self.per_host,
            }
        )

    def candidate_where_parts(self) -> tuple[list[str], list[object]]:
        where_parts = [
            "dead = 0",
            "lastHttpStatus = 200",
            "episodeCount > 0",
            "contentType like '%xml%'",
            "url <> ''",
        ]
        params: list[object] = []
        if self.min_popularity > 0:
            where_parts.append("popularityScore >= ?")
            params.append(self.min_popularity)
        if self.hosts:
            host_params = ",".join("?" for _ in self.hosts)
            where_parts.append(f"lower(host) in ({host_params})")
            params.extend(self.hosts)
        return where_parts, params

    def candidate_subquery_sql(self) -> tuple[str, list[object]]:
        where_parts, params = self.candidate_where_parts()
        limit_clause = f" limit {self.limit_feeds}" if self.limit_feeds > 0 else ""
        sql = (
            "select id "
            "from podcasts "
            f"where {' and '.join(where_parts)} "
            "order by popularityScore desc, episodeCount desc, newestItemPubdate desc, id asc"
            f"{limit_clause}"
        )
        return sql, params

    def count_total_candidates(self) -> int:
        sql, params = self.candidate_subquery_sql()
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        try:
            return int(conn.execute(f"select count(*) from ({sql})", params).fetchone()[0])
        finally:
            conn.close()

    def count_checked_candidates(self, conn: sqlite3.Connection) -> int:
        sql, params = self.candidate_subquery_sql()
        pi_conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        try:
            state_db_sql = str(self.state_db).replace("'", "''")
            pi_conn.execute(f"attach database '{state_db_sql}' as state")
            return int(
                pi_conn.execute(
                    f"select count(*) from state.feed_checks where feed_id in ({sql})",
                    params,
                ).fetchone()[0]
            )
        finally:
            pi_conn.close()

    def estimate_existing_bytes(self, conn: sqlite3.Connection) -> int:
        total_bytes = 0
        for (local_path,) in conn.execute("select local_path from transcript_files"):
            path = ROOT / str(local_path)
            if path.exists():
                total_bytes += path.stat().st_size
        for (show_slug,) in conn.execute(
            "select distinct show_slug from feed_checks where transcript_support = 1"
        ):
            show_dir = self.out_dir / str(show_slug)
            for name in ("podcastindex-feed.xml", "podcastindex-podcast-meta.json"):
                path = show_dir / name
                if path.exists():
                    total_bytes += path.stat().st_size
        return total_bytes

    def init_state_db(self) -> sqlite3.Connection:
        self.state_db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.state_db)
        conn.execute("pragma journal_mode = wal")
        conn.execute("pragma synchronous = normal")
        conn.execute(
            """
            create table if not exists feed_checks (
                feed_id integer primary key,
                feed_url text not null,
                show_slug text not null,
                show_title text not null,
                host text not null,
                checked_at integer not null,
                transcript_support integer not null,
                episodes_considered integer not null,
                episodes_downloaded integer not null,
                skipped_existing integer not null,
                error_text text not null
            )
            """
        )
        conn.execute(
            """
            create table if not exists transcript_files (
                local_path text primary key,
                feed_id integer not null,
                feed_url text not null,
                show_slug text not null,
                show_title text not null,
                episode_title text not null,
                episode_guid text not null,
                published_date text not null,
                source_url text not null,
                source_type text not null,
                language text not null,
                local_path_shadow text not null
            )
            """
        )
        conn.execute(
            "create index if not exists idx_transcript_files_show_slug on transcript_files(show_slug)"
        )
        self.migrate_transcript_table(conn)
        conn.commit()
        return conn

    def migrate_transcript_table(self, conn: sqlite3.Connection) -> None:
        columns = {
            row[1]: row
            for row in conn.execute("pragma table_info(transcript_files)").fetchall()
        }
        local_path_col = columns.get("local_path")
        source_url_col = columns.get("source_url")
        if local_path_col and int(local_path_col[5]) == 1 and source_url_col and "local_path_shadow" in columns:
            return

        conn.execute(
            """
            create table if not exists transcript_files_v2 (
                local_path text primary key,
                feed_id integer not null,
                feed_url text not null,
                show_slug text not null,
                show_title text not null,
                episode_title text not null,
                episode_guid text not null,
                published_date text not null,
                source_url text not null,
                source_type text not null,
                language text not null,
                local_path_shadow text not null
            )
            """
        )
        conn.execute("delete from transcript_files_v2")
        conn.execute(
            """
            insert or replace into transcript_files_v2 (
                local_path, feed_id, feed_url, show_slug, show_title, episode_title,
                episode_guid, published_date, source_url, source_type, language, local_path_shadow
            )
            select
                local_path,
                feed_id,
                feed_url,
                show_slug,
                show_title,
                episode_title,
                episode_guid,
                published_date,
                coalesce(source_url, ''),
                coalesce(source_type, ''),
                coalesce(language, ''),
                local_path
            from transcript_files
            where coalesce(local_path, '') <> ''
            order by
                case when coalesce(source_url, '') = '' or coalesce(source_type, '') = 'existing' then 0 else 1 end,
                rowid
            """
        )
        conn.execute("drop table transcript_files")
        conn.execute("alter table transcript_files_v2 rename to transcript_files")
        conn.execute(
            "create index if not exists idx_transcript_files_show_slug on transcript_files(show_slug)"
        )
        conn.commit()

    def load_checked_ids(self, conn: sqlite3.Connection) -> set[int]:
        cursor = conn.execute("select feed_id from feed_checks")
        return {int(row[0]) for row in cursor.fetchall()}

    def iter_candidates(self) -> Iterator[FeedCandidate]:
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row

        where_parts, params = self.candidate_where_parts()
        limit_clause = f" limit {self.limit_feeds}" if self.limit_feeds > 0 else ""
        sql = (
            "select * "
            "from podcasts "
            f"where {' and '.join(where_parts)} "
            "order by popularityScore desc, episodeCount desc, newestItemPubdate desc, id asc"
            f"{limit_clause}"
        )
        cursor = conn.execute(sql, params)
        while True:
            rows = cursor.fetchmany(1000)
            if not rows:
                break
            for row in rows:
                yield FeedCandidate(
                    feed_id=int(row["id"]),
                    url=str(row["url"]),
                    title=str(row["title"]),
                    host=str(row["host"]),
                    episode_count=int(row["episodeCount"] or 0),
                    popularity_score=int(row["popularityScore"] or 0),
                    newest_item_pubdate=int(row["newestItemPubdate"] or 0),
                    podcast_guid=str(row["podcastGuid"] or ""),
                    metadata={key: row[key] for key in row.keys()},
                )
        conn.close()

    def fetch_bytes(self, url: str, timeout: int) -> bytes:
        host = urlparse(url).netloc.lower() or "__unknown__"
        sem = self.host_limiter.semaphore_for(host)
        with sem:
            session = self.sessions.get()
            last_exc: Exception | None = None
            for attempt in range(4):
                try:
                    response = session.get(url, timeout=timeout)
                    if response.status_code in self.retryable_statuses:
                        raise requests.HTTPError(
                            f"{response.status_code} {response.reason}",
                            response=response,
                        )
                    response.raise_for_status()
                    return response.content
                except requests.HTTPError as exc:
                    last_exc = exc
                    status = getattr(exc.response, "status_code", None)
                    if status not in self.retryable_statuses or attempt == 3:
                        raise
                except (requests.Timeout, requests.ConnectionError) as exc:
                    last_exc = exc
                    if attempt == 3:
                        raise
                time.sleep(min(6, 0.75 * (attempt + 1)))
            if last_exc is not None:
                raise last_exc
            raise RuntimeError(f"unreachable fetch failure for {url}")

    def process_feed(self, feed: FeedCandidate) -> FeedOutcome:
        checked_at = int(time.time())
        show_slug = slugify(feed.title)
        show_title = feed.title
        errors: list[str] = []
        transcript_files: list[TranscriptRecord] = []
        episodes_downloaded = 0
        skipped_existing = 0
        feed_xml = ""
        transcript_support = False
        episodes_considered = 0

        try:
            feed_xml = self.fetch_bytes(feed.url, self.feed_timeout).decode("utf-8", errors="replace")
        except Exception as exc:
            return FeedOutcome(
                feed_id=feed.feed_id,
                feed_url=feed.url,
                show_slug=show_slug,
                show_title=show_title,
                host=feed.host,
                metadata=feed.metadata,
                transcript_support=False,
                episodes_considered=0,
                episodes_downloaded=0,
                skipped_existing=0,
                errors=[f"feed fetch failed: {exc}"],
                transcript_files=[],
                feed_xml="",
                checked_at=checked_at,
            )

        transcript_support = "<podcast:transcript" in feed_xml.lower()
        if not transcript_support:
            return FeedOutcome(
                feed_id=feed.feed_id,
                feed_url=feed.url,
                show_slug=show_slug,
                show_title=show_title,
                host=feed.host,
                metadata=feed.metadata,
                transcript_support=False,
                episodes_considered=0,
                episodes_downloaded=0,
                skipped_existing=0,
                errors=[],
                transcript_files=[],
                feed_xml="",
                checked_at=checked_at,
            )

        try:
            root = ET.fromstring(feed_xml)
        except Exception as exc:
            return FeedOutcome(
                feed_id=feed.feed_id,
                feed_url=feed.url,
                show_slug=show_slug,
                show_title=show_title,
                host=feed.host,
                metadata=feed.metadata,
                transcript_support=True,
                episodes_considered=0,
                episodes_downloaded=0,
                skipped_existing=0,
                errors=[f"feed xml parse failed: {exc}"],
                transcript_files=[],
                feed_xml=feed_xml,
                checked_at=checked_at,
            )

        show_dir = self.out_dir / show_slug
        episodes = feed_episode_entries(root, 0)
        episodes_considered = len(episodes)

        for episode in episodes:
            track_name = str(episode.get("trackName") or "")
            episode_guid = str(episode.get("episodeGuid") or "")
            release_date = str(episode.get("releaseDate") or "")
            node = find_episode_node(root, episode_guid, track_name)
            if node is None:
                continue
            candidates = extract_transcript_candidates(node)
            if not candidates:
                continue
            candidates.sort(key=candidate_sort_key)
            output_path = show_dir / episode_filename(release_date, track_name, episode_guid)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if output_path.exists() and not self.refresh:
                skipped_existing += 1
                transcript_files.append(
                    TranscriptRecord(
                        feed_id=feed.feed_id,
                        feed_url=feed.url,
                        show_slug=show_slug,
                        show_title=show_title,
                        episode_title=track_name,
                        episode_guid=episode_guid,
                        published_date=release_date,
                        source_url="",
                        source_type="existing",
                        language="",
                        local_path=str(output_path.relative_to(ROOT)).replace("\\", "/"),
                    )
                )
                continue

            last_error = ""
            for candidate in candidates:
                try:
                    payload = self.fetch_bytes(candidate.url, self.transcript_timeout)
                    source_type, vtt = normalize_transcript_payload(payload)
                    output_path.write_text(vtt, encoding="utf-8")
                    transcript_files.append(
                        TranscriptRecord(
                            feed_id=feed.feed_id,
                            feed_url=feed.url,
                            show_slug=show_slug,
                            show_title=show_title,
                            episode_title=track_name,
                            episode_guid=episode_guid,
                            published_date=release_date,
                            source_url=candidate.url,
                            source_type=source_type,
                            language=candidate.lang,
                            local_path=str(output_path.relative_to(ROOT)).replace("\\", "/"),
                        )
                    )
                    episodes_downloaded += 1
                    last_error = ""
                    break
                except Exception as exc:
                    last_error = f"{candidate.url} ({exc})"
            if last_error:
                errors.append(f"{track_name}: {last_error}")

        return FeedOutcome(
            feed_id=feed.feed_id,
            feed_url=feed.url,
            show_slug=show_slug,
            show_title=show_title,
            host=feed.host,
            metadata=feed.metadata,
            transcript_support=True,
            episodes_considered=episodes_considered,
            episodes_downloaded=episodes_downloaded,
            skipped_existing=skipped_existing,
            errors=errors,
            transcript_files=transcript_files,
            feed_xml=feed_xml,
            checked_at=checked_at,
        )

    def persist_outcome(self, conn: sqlite3.Connection, outcome: FeedOutcome) -> None:
        conn.execute(
            """
            insert into feed_checks (
                feed_id, feed_url, show_slug, show_title, host, checked_at,
                transcript_support, episodes_considered, episodes_downloaded,
                skipped_existing, error_text
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(feed_id) do update set
                feed_url = excluded.feed_url,
                show_slug = excluded.show_slug,
                show_title = excluded.show_title,
                host = excluded.host,
                checked_at = excluded.checked_at,
                transcript_support = excluded.transcript_support,
                episodes_considered = excluded.episodes_considered,
                episodes_downloaded = excluded.episodes_downloaded,
                skipped_existing = excluded.skipped_existing,
                error_text = excluded.error_text
            """,
            (
                outcome.feed_id,
                outcome.feed_url,
                outcome.show_slug,
                outcome.show_title,
                outcome.host,
                outcome.checked_at,
                1 if outcome.transcript_support else 0,
                outcome.episodes_considered,
                outcome.episodes_downloaded,
                outcome.skipped_existing,
                "\n".join(outcome.errors[:50]),
            ),
        )
        for record in outcome.transcript_files:
            conn.execute(
                """
                insert into transcript_files (
                    local_path, feed_id, feed_url, show_slug, show_title, episode_title,
                    episode_guid, published_date, source_url, source_type, language, local_path_shadow
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(local_path) do update set
                    feed_id = excluded.feed_id,
                    feed_url = excluded.feed_url,
                    show_slug = excluded.show_slug,
                    show_title = excluded.show_title,
                    episode_title = excluded.episode_title,
                    episode_guid = excluded.episode_guid,
                    published_date = excluded.published_date,
                    source_url = case
                        when excluded.source_url <> '' then excluded.source_url
                        else transcript_files.source_url
                    end,
                    source_type = excluded.source_type,
                    language = excluded.language,
                    local_path_shadow = excluded.local_path_shadow
                """,
                (
                    record.local_path,
                    record.feed_id,
                    record.feed_url,
                    record.show_slug,
                    record.show_title,
                    record.episode_title,
                    record.episode_guid,
                    record.published_date,
                    record.source_url,
                    record.source_type,
                    record.language,
                    record.local_path,
                ),
            )
        conn.commit()

    def write_show_sidecars(self, outcome: FeedOutcome) -> None:
        if not outcome.transcript_support:
            return
        show_dir = self.out_dir / outcome.show_slug
        show_dir.mkdir(parents=True, exist_ok=True)
        meta_path = show_dir / "podcastindex-podcast-meta.json"
        existing_records: dict[str, dict] = {}
        if meta_path.exists():
            try:
                existing_meta = json.loads(meta_path.read_text(encoding="utf-8"))
                for item in existing_meta.get("records", []):
                    if isinstance(item, dict) and item.get("local_path"):
                        existing_records[str(item["local_path"])] = item
            except Exception:
                pass
        for record in outcome.transcript_files:
            existing_records[record.local_path] = asdict(record)
        meta = {
            "podcast_meta_version": 1,
            "source_kind": "podcastindex_feed_scan",
            "feed_id": outcome.feed_id,
            "show_slug": outcome.show_slug,
            "show_title": outcome.show_title,
            "feed_url": outcome.feed_url,
            "host": outcome.host,
            "podcastindex_metadata": outcome.metadata,
            "transcript_count": len(existing_records),
            "records": sorted(existing_records.values(), key=lambda item: (item["published_date"], item["episode_title"], item["local_path"])),
            "errors": outcome.errors[:50],
            "checked_at": outcome.checked_at,
        }
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if outcome.feed_xml:
            (show_dir / "podcastindex-feed.xml").write_text(outcome.feed_xml, encoding="utf-8")

    def write_manifest_and_report(self, conn: sqlite3.Connection) -> None:
        cursor = conn.execute(
            """
            select feed_id, feed_url, show_slug, show_title, episode_title, episode_guid,
                   published_date, source_url, source_type, language, local_path
            from transcript_files
            order by show_slug, published_date, episode_title, local_path
            """
        )
        rows = [
            {
                "feed_id": int(row[0]),
                "feed_url": row[1],
                "show_slug": row[2],
                "show_title": row[3],
                "episode_title": row[4],
                "episode_guid": row[5],
                "published_date": row[6],
                "source_url": row[7],
                "source_type": row[8],
                "language": row[9],
                "local_path": row[10],
            }
            for row in cursor.fetchall()
        ]
        self.manifest_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        summary_cursor = conn.execute(
            """
            select f.show_slug, f.show_title, f.feed_url, f.host,
                   count(t.local_path) as transcript_count,
                   max(f.checked_at) as last_checked
            from feed_checks f
            left join transcript_files t on t.feed_id = f.feed_id
            where f.transcript_support = 1
            group by f.feed_id, f.show_slug, f.show_title, f.feed_url, f.host
            order by transcript_count desc, f.show_slug asc
            """
        )
        lines = [
            "# PodcastIndex Transcript Miner Report",
            "",
            f"Generated: {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
            f"Transcript files captured: {len(rows)}",
            "",
        ]
        for row in summary_cursor.fetchall():
            lines.append(f"## {row[1]}")
            lines.append(f"- Show slug: `{row[0]}`")
            lines.append(f"- Feed: {row[2]}")
            lines.append(f"- Host: {row[3]}")
            lines.append(f"- Transcript files: {row[4]}")
            lines.append(f"- Last checked: {row[5]}")
            lines.append("")
        self.report_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def outcome_disk_bytes(self, outcome: FeedOutcome) -> int:
        total_bytes = 0
        seen_paths: set[str] = set()
        for record in outcome.transcript_files:
            if record.local_path in seen_paths:
                continue
            seen_paths.add(record.local_path)
            path = ROOT / record.local_path
            if path.exists():
                total_bytes += path.stat().st_size
        if outcome.transcript_support:
            show_dir = self.out_dir / outcome.show_slug
            for name in ("podcastindex-feed.xml", "podcastindex-podcast-meta.json"):
                path = show_dir / name
                if path.exists():
                    total_bytes += path.stat().st_size
        return total_bytes

    def print_progress(
        self,
        *,
        start_time: float,
        total_candidates: int,
        baseline_checked: int,
        baseline_transcript_feeds: int,
        baseline_transcript_files: int,
        baseline_disk_bytes: int,
        completed: int,
        submitted: int,
        transcript_feeds_found: int,
        transcript_files_found: int,
        added_disk_bytes: int,
        inflight: int,
        force: bool = False,
    ) -> None:
        now_ts = time.time()
        checked_total = baseline_checked + completed
        transcript_feeds_total = baseline_transcript_feeds + transcript_feeds_found
        transcript_files_total = baseline_transcript_files + transcript_files_found
        disk_total_bytes = baseline_disk_bytes + added_disk_bytes
        elapsed = max(0.001, now_ts - start_time)
        feed_rate = completed / elapsed
        transcript_file_rate = transcript_files_found / elapsed
        progress_ratio = (checked_total / total_candidates) if total_candidates > 0 else 0.0
        remaining = max(0, total_candidates - checked_total)
        eta_seconds = (remaining / feed_rate) if feed_rate > 0 else math.inf
        transcript_feed_hit_rate = (transcript_feeds_total / checked_total) if checked_total > 0 else 0.0
        transcript_file_yield = (transcript_files_total / checked_total) if checked_total > 0 else 0.0
        projected_transcript_files = int(round(transcript_file_yield * total_candidates)) if total_candidates > 0 else transcript_files_total
        avg_bytes_per_file = (disk_total_bytes / transcript_files_total) if transcript_files_total > 0 else 0.0
        projected_disk_bytes = int(round(avg_bytes_per_file * projected_transcript_files)) if transcript_files_total > 0 else 0
        lines = [
            "[progress] "
            f"feeds={checked_total:,}/{total_candidates:,} ({progress_ratio:.2%}) "
            f"remaining={remaining:,} inflight={inflight} submitted={submitted:,} "
            f"rate={feed_rate:.2f} feeds/s eta={format_duration(eta_seconds)}"
        ,
            "[yield] "
            f"transcript_feeds={transcript_feeds_total:,} ({transcript_feed_hit_rate:.2%} of checked) "
            f"transcript_files={transcript_files_total:,} "
            f"recent_file_rate={transcript_file_rate:.2f}/s "
            f"projected_files~={projected_transcript_files:,}"
        ,
            "[disk] "
            f"current={format_bytes(disk_total_bytes)} "
            f"avg_per_transcript={format_bytes(avg_bytes_per_file)} "
            f"projected_if_yield_holds~={format_bytes(projected_disk_bytes)}"
        ]
        if force:
            lines.append("")
        self.emit_lines(lines)
        self.write_status_json(
            {
                "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "total_candidates": total_candidates,
                "checked_total": checked_total,
                "progress_ratio": progress_ratio,
                "remaining_candidates": remaining,
                "inflight": inflight,
                "submitted_this_run": submitted,
                "completed_this_run": completed,
                "elapsed_seconds": elapsed,
                "feed_rate_per_second": feed_rate,
                "eta_seconds": eta_seconds if math.isfinite(eta_seconds) else None,
                "transcript_feeds_total": transcript_feeds_total,
                "transcript_files_total": transcript_files_total,
                "transcript_feed_hit_rate": transcript_feed_hit_rate,
                "transcript_file_rate_per_second": transcript_file_rate,
                "projected_transcript_files": projected_transcript_files,
                "disk_bytes_total": disk_total_bytes,
                "avg_bytes_per_transcript": avg_bytes_per_file,
                "projected_disk_bytes": projected_disk_bytes,
                "workers": self.workers,
                "per_host": self.per_host,
                "started_at": dt.datetime.fromtimestamp(start_time, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "updated_at_epoch": now_ts,
            }
        )

    def run(self) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        start_time = time.time()
        self.emit_initializing("opening state database and loading prior crawl state")
        state_conn = self.init_state_db()
        checked_ids = set() if self.refresh else self.load_checked_ids(state_conn)
        self.emit_initializing("counting candidate feeds from PodcastIndex inventory")
        total_candidates = self.count_total_candidates()
        self.emit_initializing("matching already-checked feeds against the current candidate set")
        baseline_checked = 0 if self.refresh else self.count_checked_candidates(state_conn)
        baseline_transcript_feeds = 0 if self.refresh else int(
            state_conn.execute("select count(*) from feed_checks where transcript_support = 1").fetchone()[0]
        )
        baseline_transcript_files = 0 if self.refresh else int(
            state_conn.execute("select count(*) from transcript_files").fetchone()[0]
        )
        self.emit_initializing("estimating existing on-disk size for previously downloaded transcript artifacts")
        baseline_disk_bytes = 0 if self.refresh else self.estimate_existing_bytes(state_conn)
        submitted = 0
        completed = 0
        transcript_feeds = 0
        transcript_files = 0
        added_disk_bytes = 0
        max_inflight = self.workers
        inflight: set[concurrent.futures.Future[FeedOutcome]] = set()
        candidates = self.iter_candidates()
        last_progress_at = 0.0
        self.emit_lines([
            "[start] "
            f"candidate_feeds={total_candidates:,} "
            f"already_checked={baseline_checked:,} "
            f"transcript_feeds={baseline_transcript_feeds:,} "
            f"transcript_files={baseline_transcript_files:,} "
            f"disk={format_bytes(baseline_disk_bytes)} "
            f"workers={self.workers} per_host={self.per_host}",
            "",
        ])
        self.print_progress(
            start_time=start_time,
            total_candidates=total_candidates,
            baseline_checked=baseline_checked,
            baseline_transcript_feeds=baseline_transcript_feeds,
            baseline_transcript_files=baseline_transcript_files,
            baseline_disk_bytes=baseline_disk_bytes,
            completed=completed,
            submitted=submitted,
            transcript_feeds_found=transcript_feeds,
            transcript_files_found=transcript_files,
            added_disk_bytes=added_disk_bytes,
            inflight=len(inflight),
            force=True,
        )

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers) as executor:
            exhausted = False
            while inflight or not exhausted:
                while not exhausted and len(inflight) < max_inflight:
                    try:
                        candidate = next(candidates)
                    except StopIteration:
                        exhausted = True
                        break
                    if not self.refresh and candidate.feed_id in checked_ids:
                        continue
                    inflight.add(executor.submit(self.process_feed, candidate))
                    submitted += 1
                if not inflight:
                    continue
                done, inflight = concurrent.futures.wait(
                    inflight,
                    timeout=5,
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )
                for future in done:
                    outcome = future.result()
                    self.persist_outcome(state_conn, outcome)
                    self.write_show_sidecars(outcome)
                    completed += 1
                    checked_ids.add(outcome.feed_id)
                    if outcome.transcript_support:
                        transcript_feeds += 1
                        transcript_files += len(outcome.transcript_files)
                        added_disk_bytes += self.outcome_disk_bytes(outcome)
                    if completed % 50 == 0:
                        self.write_manifest_and_report(state_conn)
                now = time.time()
                if now - last_progress_at >= self.progress_every:
                    self.print_progress(
                        start_time=start_time,
                        total_candidates=total_candidates,
                        baseline_checked=baseline_checked,
                        baseline_transcript_feeds=baseline_transcript_feeds,
                        baseline_transcript_files=baseline_transcript_files,
                        baseline_disk_bytes=baseline_disk_bytes,
                        completed=completed,
                        submitted=submitted,
                        transcript_feeds_found=transcript_feeds,
                        transcript_files_found=transcript_files,
                        added_disk_bytes=added_disk_bytes,
                        inflight=len(inflight),
                        force=True,
                    )
                    last_progress_at = now
        self.write_manifest_and_report(state_conn)
        self.print_progress(
            start_time=start_time,
            total_candidates=total_candidates,
            baseline_checked=baseline_checked,
            baseline_transcript_feeds=baseline_transcript_feeds,
            baseline_transcript_files=baseline_transcript_files,
            baseline_disk_bytes=baseline_disk_bytes,
            completed=completed,
            submitted=submitted,
            transcript_feeds_found=transcript_feeds,
            transcript_files_found=transcript_files,
            added_disk_bytes=added_disk_bytes,
            inflight=0,
            force=True,
        )
        state_conn.close()
        self.emit_lines([
            f"[done] checked={completed} submitted={submitted} "
            f"transcript_feeds={transcript_feeds} transcript_files={transcript_files} "
            f"out={self.out_dir}"
        ])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mine PodcastIndex feed inventory for feeds that expose podcast:transcript tags.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="Path to the local PodcastIndex SQLite database.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Transcript output root.")
    parser.add_argument("--state-db", default=str(DEFAULT_STATE_DB), help="Path to miner state SQLite DB.")
    parser.add_argument("--workers", type=int, default=16, help="Global worker pool size.")
    parser.add_argument("--per-host", type=int, default=2, help="Max concurrent HTTP requests per host.")
    parser.add_argument("--limit-feeds", type=int, default=0, help="Limit number of candidate feeds scanned (0 = no limit).")
    parser.add_argument("--min-popularity", type=int, default=0, help="Minimum popularityScore from the PodcastIndex DB.")
    parser.add_argument("--host", action="append", default=[], help="Restrict scanning to specific host(s). Repeatable.")
    parser.add_argument("--feed-timeout", type=int, default=30, help="Timeout in seconds for feed fetches.")
    parser.add_argument("--transcript-timeout", type=int, default=30, help="Timeout in seconds for transcript fetches.")
    parser.add_argument("--progress-every", type=int, default=15, help="Emit live progress every N seconds.")
    parser.add_argument("--progress-log", default=str(ROOT / "tmp" / "podcastindex-miner.progress.log"), help="Append human-readable progress lines to this log file.")
    parser.add_argument("--status-json", default=str(ROOT / "tmp" / "podcastindex-miner.status.json"), help="Write the latest progress snapshot to this JSON file.")
    parser.add_argument("--refresh", action="store_true", help="Recheck feeds already present in the miner state DB.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    miner = PodcastIndexMiner(
        db_path=Path(args.db_path),
        out_dir=Path(args.out_dir),
        state_db=Path(args.state_db),
        workers=int(args.workers),
        per_host=int(args.per_host),
        limit_feeds=int(args.limit_feeds),
        min_popularity=int(args.min_popularity),
        refresh=bool(args.refresh),
        hosts=list(args.host or []),
        feed_timeout=int(args.feed_timeout),
        transcript_timeout=int(args.transcript_timeout),
        progress_every=int(args.progress_every),
        progress_log=Path(args.progress_log) if args.progress_log else None,
        status_json=Path(args.status_json) if args.status_json else None,
    )
    miner.run()


if __name__ == "__main__":
    main()
