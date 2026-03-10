from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import subprocess
import tempfile
import threading
import time
import shlex
import html
import signal
import atexit
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# When this file is executed directly, Python sets `sys.path[0]` to this directory
# (scripts/audio-to-transcripts/), which breaks imports from the repo-root `scripts/` package.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.feed_manifest import parse_feed_for_manifest
from scripts.shared import VODCASTS_ROOT, fetch_url
from scripts.sources import Source, load_sources_config
from transcription_backends import get_backend
from transcription_backends.subtitle_utils import SubtitleValidationError, coerce_subtitle_output


_PLAYABLE_TYPES = {"text/vtt", "application/x-subrip", "application/srt"}

_MEDIA_CONNECT_TIMEOUT_SECONDS = 5
_MEDIA_PROBE_MAX_TIME_SECONDS = 10
_MEDIA_RESOLVE_TIMEOUT_SECONDS = 45

_EXISTING_VTT_MIN_CHARS = 80
_EXISTING_VTT_MIN_WORDS = 10
_TRANSCRIPTION_CONCURRENCY = 2
max_episodes_per_feed = 12
# Episodes under this duration (sec) count as "short" and can fill bonus slots up to double the per-feed limit.
_SHORT_EPISODE_THRESHOLD_SEC = 1500  # 25 min

_TRANSCRIPT_SANITY_FAILURES_PATH = VODCASTS_ROOT / "transcript-sanity-failures.md"
_REVIEW_TRANSCRIPTS_DIR = VODCASTS_ROOT / "review-transcripts"
_WHISPERX_EMPTY_DIAG_LOG = VODCASTS_ROOT / "whisperx-empty-diag.log"


def _log_whisperx_empty_diag(
    *,
    feed_id: str = "",
    ep_slug: str = "",
    media_url: str = "",
    source: str = "",
    **kwargs: Any,
) -> None:
    """Append diagnostic info to log file when WhisperX returns empty. Never loses the reason."""
    from datetime import datetime

    lines = [
        "",
        f"=== {datetime.utcnow().isoformat()}Z {source} ===",
        f"feed_id={feed_id} ep_slug={ep_slug}",
        f"media_url={media_url}",
    ]
    for k, v in kwargs.items():
        lines.append(f"{k}={v}")
    try:
        with open(_WHISPERX_EMPTY_DIAG_LOG, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception as e:
        print(f"[warn] failed to write whisperx-empty-diag.log: {e}", flush=True)

# Feeds with high advice/support density for answer engine (practical, pastoral, how-to).
# Tuned from transcript sampling across 35+ feeds (titles + content).
HIGH_VALUE_FEEDS = frozenset({
    "bridgetown",
    "desiring-god-messages",
    "desiring-god-messages-video",
    "between-sermons-video",
    "bishop-barron-sermons",
    "eric-walsh-sermons",
    "calvary-chapel-fort-lauderdale",
    "calvary-chapel-anne-arundel",
    "connexus-church",
    "dag-heward-mills-video",
    "exceed-life-church",
    "first-baptist-columbia-wf",
    "church-of-the-highlands-weekend-video",
    "church-on-the-rock",
    "dungeness-community-church",
    "fresh-life-church",
    "godspeak-calvary",
    "crossway-milford-sermons",
    "harvest-baptist-ga",
    "amazing-grace-baptist-mount-airy",
    "btic-podcast-video",
    "concord-baptist-church",
    "cbcaiken-sermons",
    "buford-road-baptist",
    "antioch-church",
})

# Feeds with lower advice density for answer engine (liturgical, narrative, institutional, bilingual).
# Kept for future limit tuning; not applied yet.
WEAKER_FEEDS = frozenset({
    "all-saints-homilies",
    "crossccc",
    "catholic-sermons-station-of-the-cross",
    "chinese-bible-church",
    "chinese-community-church-sacramento",
    "lancaster-baptist",
    "faith-christian-churchs",
    "heritage",
    "atlanta-first-umc",
    "city-chapel-church",
    "eaglebrook",
    "first-church-warsaw-methodist",
    "elevation-steven-furtick",
})

# Excluded from the local transcription workflow entirely.
EXCLUDED_TRANSCRIPT_SOURCE_IDS = frozenset({
    "first-love-church-uk",
    "life-church-video",
    "boulder-church-video-podcast",
})


class MediaDownloadError(RuntimeError):
    pass


def _looks_like_direct_media_url(url: str) -> bool:
    u = str(url or "").strip().lower()
    if not u:
        return False
    if ".m3u8" in u:
        return True
    return any(ext in u for ext in (".mp3", ".m4a", ".wav", ".mp4", ".m4v", ".mov", ".webm"))


def _resolve_media_url(url: str, *, execute: bool) -> str:
    raw = str(url or "").strip()
    if not raw or not raw.lower().startswith(("http://", "https://")):
        return raw
    if _looks_like_direct_media_url(raw):
        return raw

    # Some feeds publish landing/admin pages instead of enclosures. Try to resolve them to a
    # concrete media URL via yt-dlp when available.
    cmd = ["yt-dlp", "--no-warnings", "--no-playlist", "-g", raw]
    pretty = " ".join(json.dumps(x) for x in cmd)
    print(f"[cmd] {pretty}")
    if not execute:
        return raw
    try:
        res = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=int(_MEDIA_RESOLVE_TIMEOUT_SECONDS),
        )
    except Exception as e:
        # Vimeo "manage/videos" URLs are admin pages, not public media pages.
        if "vimeo.com/manage/videos/" in raw.lower():
            raise MediaDownloadError(f"unresolvable vimeo manage url: {raw}") from e
        return raw

    lines = [ln.strip() for ln in (res.stdout or "").splitlines() if ln.strip()]
    resolved = next((ln for ln in lines if ln.lower().startswith(("http://", "https://"))), "")
    if not resolved:
        if "vimeo.com/manage/videos/" in raw.lower():
            raise MediaDownloadError(f"unresolvable vimeo manage url: {raw}")
        return raw
    print(f"[media] resolved url={resolved}")
    return resolved


def _pick_fast_temp_root() -> Path | None:
    # Project-local convention: Q:\ is the RAM disk on this machine.
    p = Path("Q:/")
    try:
        if p.exists() and p.is_dir():
            return p
    except Exception:
        pass
    return None


def _canon_env(v: str) -> str:
    v = (v or "").strip()
    if v in ("prod", "main", "full"):
        return "complete"
    return v


def _active_env() -> str:
    v = _canon_env(os.environ.get("VOD_ENV") or "")
    if v:
        return v
    state_file = VODCASTS_ROOT / ".vodcasts-env"
    if state_file.exists():
        try:
            txt = state_file.read_text(encoding="utf-8", errors="replace").strip()
            if txt:
                return _canon_env(txt)
        except Exception:
            pass
    print("[warn] VOD_ENV is not set; defaulting to 'dev'. Run: yarn use dev|church|tech|complete")
    return "dev"


@dataclass(frozen=True)
class TranscriptCandidate:
    url: str
    typ: str
    lang: str
    is_captions: bool
    is_playable: bool


@dataclass(frozen=True)
class WorkItem:
    src: Source
    channel_title: str
    ep: dict[str, Any]
    action: str  # download|generate


@dataclass(frozen=True)
class WorkOutcome:
    src_id: str
    ep_slug: str
    action: str
    chosen: str
    provided_count: int = 0
    rejected_provided: int = 0
    generated_count: int = 0
    spotcheck_count: int = 0
    errors: int = 0
    dead_media: bool = False


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Cache provided transcripts (podcast:transcript) and optionally generate missing ones using WhisperX.\n"
            "Designed for local/offline processing (no build integration)."
        )
    )
    p.add_argument(
        "--feeds",
        default="",
        help="Feeds config (.md). Default: feeds/<active-env>.md via VOD_ENV or .vodcasts-env.",
    )
    p.add_argument(
        "--cache",
        default="",
        help="Cache directory. Default: cache/<active-env> via VOD_ENV or .vodcasts-env.",
    )
    p.add_argument(
        "--out",
        default="",
        help="Output directory for transcript cache (default: <cache>/transcripts).",
    )
    p.add_argument(
        "--tag",
        default="church,sermons",
        help=(
            "Only process sources that match any of these tags/categories (default: church,sermons). "
            "Accepts comma/pipe-separated values. Use --all-sources to ignore."
        ),
    )
    p.add_argument("--all-sources", action="store_true", help="Process all sources (ignores --tag filter).")
    p.add_argument("--source-id", default="", help="Only process this feed slug/source id (exact match).")
    p.add_argument("--episode-slug", default="", help="Only process this episode slug (exact match).")
    p.add_argument(
        "--max-episodes-per-feed",
        type=int,
        default=10,
        help="Limit episodes processed per feed, preferring most recent by dateText when available (0 = all).",
    )
    p.add_argument(
        "--max-episodes-total",
        type=int,
        default=0,
        help="Limit total episodes processed across all feeds (0 = all).",
    )
    p.add_argument(
        "--concurrency",
        type=int,
        default=0,
        help="Max parallel workers for generation (0 = use default: 2 when execute, 1 when dry-run).",
    )
    p.add_argument(
        "--prefer-shorter",
        action="store_true",
        help="Prefer shorter known-duration episodes first; episodes without known duration are queued later.",
    )
    p.add_argument(
        "--download-provided",
        action="store_true",
        help="Download provided podcast:transcript assets when present (default).",
    )
    p.add_argument(
        "--no-download-provided",
        dest="download_provided",
        action="store_false",
        help="Do not download provided transcripts (generation-only mode).",
    )
    p.set_defaults(download_provided=True)
    p.add_argument(
        "--generate-missing",
        action="store_true",
        help="Generate transcript/subtitles when none are available (or provided transcript is unusable).",
    )
    p.add_argument(
        "--generate-missing-all-sources",
        action="store_true",
        help="When using --all-sources, also generate missing transcripts for non-tagged sources (default: generate only for tagged sources).",
    )
    p.add_argument(
        "--execute",
        action="store_true",
        help="Actually write files / download / run ffmpeg+whisperx. Without this, prints a dry-run plan.",
    )
    p.add_argument("--refresh", action="store_true", help="Re-download/regenerate even if outputs already exist.")
    p.add_argument("--timeout-seconds", type=int, default=45, help="Per-download timeout (default: 45).")
    p.add_argument("--user-agent", default="vodcasts-transcripts/1.0", help="HTTP user-agent for downloads.")

    # WhisperX pipeline (only used when --generate-missing + --execute)
    p.add_argument("--ffmpeg", default="ffmpeg", help="ffmpeg executable (default: ffmpeg).")
    p.add_argument("--whisperx", default="whisperx", help="whisperx executable (default: whisperx).")
    p.add_argument("--whisperx-model", default="medium", help="WhisperX model name (default: medium).")
    p.add_argument("--language", default="en", help="Language code for WhisperX (default: en).")
    p.add_argument(
        "--whisperx-device",
        default="cuda",
        help="Device for transcription (default: cuda). GPU required.",
    )
    p.add_argument(
        "--whisperx-compute-type",
        default="float16",
        help="WhisperX compute type (default: float16). Common: float16, float32, int8.",
    )
    p.add_argument(
        "--whisperx-extra-args",
        default="",
        help='Extra args appended to the whisperx command (e.g. "--batch_size 4 --output_format srt").',
    )
    p.add_argument(
        "--whisperx-worker-url",
        default=(os.environ.get("VODCASTS_WHISPERX_WORKER_URL") or ""),
        help="Optional local WhisperX worker URL (for persistent model reuse). Example: http://127.0.0.1:8776",
    )
    p.add_argument(
        "--backend",
        default="whisperx",
        choices=["whisperx", "parakeet", "moonshine"],
        help="Transcription backend (default: whisperx). parakeet/moonshine run in-process, no worker.",
    )

    # Failure review clips: kept only when generated transcripts fail sanity / generation.
    p.add_argument("--spot-check-every", type=int, default=0, help="Deprecated compatibility flag; normal runs no longer sample successful spot-check MP3s.")
    p.add_argument("--spot-check-seconds", type=int, default=600, help="Failure review MP3 length in seconds (default: 600 = 10 minutes).")
    p.add_argument("--spot-check-bitrate", default="96k", help="Failure review MP3 bitrate (default: 96k).")

    # Acceptance heuristics for provided transcripts
    p.add_argument("--min-text-chars", type=int, default=200, help="Minimum extracted text chars to accept (default: 200).")
    p.add_argument("--min-words", type=int, default=30, help="Minimum extracted word count to accept (default: 30).")
    return p.parse_args()


def _norm(s: str) -> str:
    return str(s or "").strip()


def _duration_key(ep: dict[str, Any]) -> tuple[int, int]:
    raw = ep.get("durationSec")
    try:
        dur = int(raw)
    except Exception:
        dur = 0
    if dur > 0:
        return (0, dur)
    return (1, 10**9)


def _is_short_episode(ep: dict[str, Any], threshold_sec: int = _SHORT_EPISODE_THRESHOLD_SEC) -> bool:
    raw = ep.get("durationSec")
    try:
        dur = int(raw)
        return 0 < dur <= threshold_sec
    except Exception:
        return False


def _recency_key(ep: dict[str, Any]) -> int:
    raw = re.sub(r"[^0-9]", "", _norm(ep.get("dateText") or ""))
    if len(raw) >= 8:
        try:
            return -int(raw[:8])
        except Exception:
            pass
    return 0


def _split_tags(v: str) -> list[str]:
    raw = _norm(v).lower()
    if not raw:
        return []
    parts = [p.strip() for p in re.split(r"[,\|]+", raw) if p.strip()]
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        if p not in seen:
            out.append(p)
            seen.add(p)
    return out


def _matches_any_tag(source: Source, tag: str) -> bool:
    tags = _split_tags(tag)
    if not tags:
        return True
    return any(_matches_tag(source, t) for t in tags)


def _matches_tag(source: Source, tag: str) -> bool:
    t = _norm(tag).lower()
    if not t:
        return True
    if _norm(source.category).lower() == t:
        return True
    if t in _norm(source.category).lower():
        return True
    tags = tuple(_norm(x).lower() for x in (source.tags or ()))
    return t in tags


def _load_sanity_failures() -> set[tuple[str, str]]:
    """Load feed_id/ep_slug pairs from transcript-sanity-failures.md."""
    out: set[tuple[str, str]] = set()
    if not _TRANSCRIPT_SANITY_FAILURES_PATH.exists():
        return out
    # Parse lines like "- feed_id/ep_slug: reason" or "| feed_id | ep_slug | reason |"
    key_re = re.compile(r"([a-zA-Z0-9][\w.-]+)/([\w.-]+)")
    for line in (_TRANSCRIPT_SANITY_FAILURES_PATH.read_text(encoding="utf-8", errors="replace").splitlines() or []):
        m = key_re.search(line)
        if m:
            out.add((m.group(1), m.group(2)))
    return out


_SANITY_FAILURE_LOCK = threading.Lock()


def _append_sanity_failure(feed_id: str, ep_slug: str, reason: str) -> None:
    """Append a failure entry to transcript-sanity-failures.md."""
    key = f"{feed_id}/{ep_slug}"
    entry = f"- {key}: {reason}\n"
    with _SANITY_FAILURE_LOCK:
        if _TRANSCRIPT_SANITY_FAILURES_PATH.exists():
            content = _TRANSCRIPT_SANITY_FAILURES_PATH.read_text(encoding="utf-8", errors="replace")
            if key in content:
                return  # already listed
            content = content.rstrip()
            if content and not content.endswith("\n"):
                content += "\n"
            content += entry
        else:
            content = (
                "# Transcript Sanity Failures\n\n"
                "Episodes that failed transcript sanity checks. Remove an entry to allow regeneration.\n\n"
                + entry
            )
        _TRANSCRIPT_SANITY_FAILURES_PATH.write_text(content, encoding="utf-8")


def _move_failed_to_review(
    feed_id: str,
    ep_slug: str,
    vtt_text: str,
    spot_mp3_path: Path | None,
    *,
    execute: bool,
    cache_feed_dir: Path | None = None,
) -> None:
    """Move failed VTT and spot MP3 to review-transcripts/feed_id/ for manual inspection."""
    if not execute:
        return
    review_feed = _REVIEW_TRANSCRIPTS_DIR / feed_id
    review_feed.mkdir(parents=True, exist_ok=True)
    vtt_dest = review_feed / f"{ep_slug}.vtt"
    vtt_dest.write_text(vtt_text or "", encoding="utf-8")
    print(f"[review] {feed_id}/{ep_slug}: vtt -> {vtt_dest.relative_to(VODCASTS_ROOT)}")
    if spot_mp3_path and spot_mp3_path.exists():
        mp3_dest = review_feed / f"{ep_slug}.spotcheck.mp3"
        shutil.move(str(spot_mp3_path), str(mp3_dest))
        print(f"[review] {feed_id}/{ep_slug}: spotcheck -> {mp3_dest.relative_to(VODCASTS_ROOT)}")
    if cache_feed_dir and cache_feed_dir.exists():
        try:
            if not any(cache_feed_dir.iterdir()):
                cache_feed_dir.rmdir()
                print(f"[review] removed empty {cache_feed_dir.relative_to(VODCASTS_ROOT)}")
        except OSError:
            pass


def _capture_failure_spotcheck(
    *,
    media_url: str,
    ffmpeg_cmd: str,
    spot_mp3_path: Path,
    spot_seconds: int,
    spot_bitrate: str,
    execute: bool,
) -> Path | None:
    """Capture a short debug clip only for failed episodes."""
    if not execute or not media_url:
        return None
    try:
        media_input = _resolve_media_url(media_url, execute=execute)
        spot_mp3_path.parent.mkdir(parents=True, exist_ok=True)
        _run(
            [
                ffmpeg_cmd,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(media_input),
                "-t",
                str(max(1, int(spot_seconds or 0))),
                "-vn",
                "-acodec",
                "libmp3lame",
                "-b:a",
                str(spot_bitrate or "96k"),
                str(spot_mp3_path),
            ],
            execute=True,
        )
        if spot_mp3_path.exists():
            return spot_mp3_path
    except Exception as e:
        print(f"[warn] failed to capture review spotcheck: {e}")
    return None


_SRT_TS_RE = re.compile(r"^\d{2}:\d{2}:\d{2}[,.]\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}[,.]\d{3}")
_VTT_TS_RE = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}\.\d{3}")
# WhisperX outputs MM:SS.mmm (e.g. 00:00.546 --> 04:30.114) instead of HH:MM:SS.mmm
_VTT_TS_MMSS_RE = re.compile(r"^\d{1,2}:\d{2}[,.]\d{3}\s+-->\s+\d{1,2}:\d{2}[,.]\d{3}")


def _extract_text_from_srt(s: str) -> str:
    out: list[str] = []
    for raw in (s or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.isdigit():
            continue
        if _SRT_TS_RE.match(line):
            continue
        # Drop common formatting tags
        line = re.sub(r"<[^>]+>", "", line).strip()
        if not line:
            continue
        out.append(line)
    return " ".join(out).strip()


def _extract_text_from_vtt(s: str) -> str:
    out: list[str] = []
    for raw in (s or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.upper().startswith("WEBVTT"):
            continue
        # Accept both standard WebVTT timestamps (.) and common "VTT-but-actually-SRT" timestamps (,).
        # Also WhisperX MM:SS.mmm format (e.g. 00:00.546 --> 04:30.114).
        if _VTT_TS_RE.match(line) or _SRT_TS_RE.match(line) or _VTT_TS_MMSS_RE.match(line):
            continue
        if "-->" in line and re.search(
            r"\d{2}:\d{2}:\d{2}[\.,]\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}[\.,]\d{3}|"
            r"\d{1,2}:\d{2}[\.,]\d{3}\s+-->\s+\d{1,2}:\d{2}[\.,]\d{3}",
            line,
        ):
            continue
        if line.startswith("NOTE"):
            continue
        line = re.sub(r"<[^>]+>", "", line).strip()
        if not line:
            continue
        out.append(line)
    return " ".join(out).strip()


def _normalize_vtt_timestamp_commas(vtt: str) -> str:
    """
    WebVTT requires '.' as the millisecond separator, but some sources (and some tools) output ','.
    Normalize cue timing lines so cached .vtt files remain browser-playable.
    Supports both HH:MM:SS and MM:SS formats.
    """
    lines: list[str] = []
    changed = False
    for raw in (vtt or "").splitlines():
        line = raw.rstrip("\n")
        if "-->" in line and "," in line:
            fixed = re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", line)
            fixed = re.sub(r"(\d{1,2}:\d{2}),(\d{3})", r"\1.\2", fixed)
            if fixed != line:
                changed = True
            line = fixed
        lines.append(line)
    if not changed:
        return vtt
    return "\n".join(lines).rstrip() + "\n"


def _srt_to_vtt(srt: str) -> str:
    lines: list[str] = ["WEBVTT", ""]
    for raw in (srt or "").splitlines():
        line = raw.rstrip("\n")
        if line.strip().isdigit():
            continue
        if _SRT_TS_RE.match(line.strip()):
            lines.append(line.replace(",", "."))
            continue
        lines.append(line)
    return "\n".join(lines).rstrip() + "\n"


def _looks_like_srt(text: str) -> bool:
    s = (text or "").lstrip()
    if not s:
        return False
    # Heuristic: has at least one timestamp line
    return any(_SRT_TS_RE.match(ln.strip()) for ln in s.splitlines()[:200])


def _looks_like_vtt(text: str) -> bool:
    s = (text or "").lstrip()
    if not s:
        return False
    if s.upper().startswith("WEBVTT"):
        return True
    return any(
        _VTT_TS_RE.match(ln.strip()) or _VTT_TS_MMSS_RE.match(ln.strip())
        for ln in s.splitlines()[:200]
    )


def _is_sensible_text(text: str, *, min_chars: int, min_words: int) -> bool:
    t = (text or "").strip()
    if len(t) < int(min_chars):
        return False
    words = [w for w in re.split(r"\s+", t) if w]
    if len(words) < int(min_words):
        return False
    letters = sum(ch.isalpha() for ch in t)
    return letters >= max(20, int(0.2 * len(t)))


class ProvidedTranscriptRejected(ValueError):
    pass


class GeneratedTranscriptRejected(RuntimeError):
    pass


def _count_srt_timestamps(text: str) -> int:
    return sum(1 for ln in (text or "").splitlines() if _SRT_TS_RE.match(ln.strip()))


def _count_vtt_timestamps(text: str) -> int:
    cnt = 0
    for ln in (text or "").splitlines():
        s = ln.strip()
        if _VTT_TS_RE.match(s) or _VTT_TS_MMSS_RE.match(s):
            cnt += 1
            continue
        if "-->" in s and re.search(
            r"\d{2}:\d{2}:\d{2}[\.,]\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}[\.,]\d{3}|"
            r"\d{1,2}:\d{2}[\.,]\d{3}\s+-->\s+\d{1,2}:\d{2}[\.,]\d{3}",
            s,
        ):
            cnt += 1
    return cnt


def _normalize_provided_subtitles_to_vtt(text: str, *, min_chars: int, min_words: int) -> tuple[str, str]:
    """
    Returns (kind, vtt_text). Raises ProvidedTranscriptRejected when the payload isn't believable subtitles.
    """
    raw = (text or "").replace("\x00", "").lstrip("\ufeff")
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    raw = html.unescape(raw)

    variants = [raw]
    stripped = re.sub(r"<[^>]+>", "", raw)
    if stripped != raw:
        variants.append(stripped)

    kind = ""
    picked = ""
    for v in variants:
        if _looks_like_vtt(v):
            kind = "vtt"
            picked = v
            break
        if _looks_like_srt(v):
            kind = "srt"
            picked = v
            break

    if not kind:
        raise ProvidedTranscriptRejected("does not look like VTT/SRT")

    if kind == "vtt":
        vtt = picked if picked.lstrip().upper().startswith("WEBVTT") else ("WEBVTT\n\n" + picked.strip() + "\n")
        vtt = _normalize_vtt_timestamp_commas(vtt)
        ts = _count_vtt_timestamps(vtt)
        extracted = _extract_text_from_vtt(vtt)
    else:
        ts = _count_srt_timestamps(picked)
        extracted = _extract_text_from_srt(picked)
        vtt = _srt_to_vtt(picked)

    if ts < 2:
        raise ProvidedTranscriptRejected(f"too few subtitle timestamps ({ts})")

    if not _is_sensible_text(extracted, min_chars=int(min_chars), min_words=int(min_words)):
        words = [w for w in re.split(r"\s+", extracted.strip()) if w]
        raise ProvidedTranscriptRejected(
            f"fails transcript sanity (chars={len(extracted)} words={len(words)} min_chars={int(min_chars)} min_words={int(min_words)})"
        )

    return kind, vtt


def _vtt_seems_complete(vtt: str, *, min_chars: int, min_words: int) -> bool:
    if not _looks_like_vtt(vtt):
        return False
    if _count_vtt_timestamps(vtt) < 2:
        return False
    extracted = _extract_text_from_vtt(vtt)
    return _is_sensible_text(extracted, min_chars=int(min_chars), min_words=int(min_words))


def _vtt_file_seems_complete(path: Path, *, min_chars: int, min_words: int) -> bool:
    try:
        if not path.exists():
            return False
        if path.stat().st_size < 80:
            return False
        txt = path.read_text(encoding="utf-8", errors="replace")
        if _count_vtt_timestamps(txt) < 3:
            return False
        return _vtt_seems_complete(_normalize_vtt_timestamp_commas(txt), min_chars=int(min_chars), min_words=int(min_words))
    except Exception:
        return False


def _pick_best_transcript_candidate(ep: dict[str, Any]) -> TranscriptCandidate | None:
    raw = ep.get("transcriptsAll") or []
    cands: list[TranscriptCandidate] = []
    for t in raw:
        if not isinstance(t, dict):
            continue
        url = _norm(t.get("url") or "")
        typ = _norm(t.get("type") or "").lower()
        if not url or not typ:
            continue
        lang = _norm(t.get("lang") or "en") or "en"
        is_captions = bool(t.get("isCaptions"))
        is_playable = typ in _PLAYABLE_TYPES
        cands.append(TranscriptCandidate(url=url, typ=typ, lang=lang, is_captions=is_captions, is_playable=is_playable))

    if not cands:
        return None

    def score(c: TranscriptCandidate) -> tuple[int, int, int]:
        # Prefer playable, captions, English.
        return (1 if c.is_playable else 0, 1 if c.is_captions else 0, 1 if c.lang.lower().startswith("en") else 0)

    cands.sort(key=score, reverse=True)
    return cands[0]


def _run(cmd: list[str], *, execute: bool) -> None:
    pretty = " ".join(json.dumps(x) for x in cmd)
    print(f"[cmd] {pretty}")
    if not execute:
        return

    creationflags = 0
    start_new_session = False
    if os.name != "nt":
        start_new_session = True

    p = subprocess.Popen(
        cmd,
        start_new_session=start_new_session,
        creationflags=creationflags,
    )
    try:
        rc = p.wait()
        if rc != 0:
            raise subprocess.CalledProcessError(rc, cmd)
    except KeyboardInterrupt:
        print("[cancel] ctrl+c received; stopping subprocess")
        _kill_process_tree(p)
        raise


@contextmanager
def _timed(label: str) -> Any:
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt = time.perf_counter() - t0
        print(f"[time] {label}: {dt:.2f}s")


def _kill_process_tree(p: subprocess.Popen[Any]) -> None:
    if p.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(int(p.pid)), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            return
        try:
            os.killpg(int(p.pid), signal.SIGTERM)
        except Exception:
            p.terminate()
    except Exception:
        try:
            p.kill()
        except Exception:
            pass


def _download_bytes(url: str, *, timeout_seconds: int, user_agent: str, execute: bool, label: str = "download") -> bytes | None:
    if not execute:
        return None
    with _timed(str(label or "download")):
        res = fetch_url(url, timeout_seconds=timeout_seconds, user_agent=user_agent)
    if res.status < 200 or res.status >= 300 or not res.content:
        raise ValueError(f"download failed: http {res.status} ({res.url})")
    print(f"[download] bytes={len(res.content)} url={res.url}")
    return res.content


def _write_text(path: Path, text: str, *, execute: bool) -> None:
    if not execute:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    print(f"[write] {path}")


def _write_bytes(path: Path, data: bytes, *, execute: bool) -> None:
    if not execute:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    print(f"[write] {path} ({len(data)} bytes)")


def _maybe_normalize_existing_vtt(path: Path, *, execute: bool) -> None:
    if not execute:
        return
    try:
        txt = path.read_text(encoding="utf-8", errors="replace")
        fixed = _normalize_vtt_timestamp_commas(txt)
        if fixed != txt:
            _write_text(path, fixed, execute=True)
            print(f"[fix] {path}: normalized VTT timestamps (, -> .)")
    except Exception:
        # Best-effort only; validation/skip logic decides correctness.
        pass


def _ensure_non_empty_transcript(srt_text: str, vtt_text: str) -> None:
    """Raise if the effective VTT would be empty (WhisperX produced no speech)."""
    effective = (vtt_text or "").strip() or (_srt_to_vtt(srt_text or "").strip() if (srt_text or "").strip() else "")
    if not effective:
        raise ValueError("whisperx produced empty transcript (no speech detected or VAD filtered all)")


def _generate_transcript(
    *,
    backend: Any,
    media_url: str,
    ffmpeg_cmd: str,
    language: str,
    spot_mp3_path: Path | None,
    spot_seconds: int,
    spot_bitrate: str,
    execute: bool,
) -> tuple[str, str]:
    """
    Returns (srt_text, vtt_text). Never returns empty; raises if no speech detected.
    """
    if not execute:
        # dry-run placeholder
        return "", ""

    with tempfile.TemporaryDirectory(prefix="vodcasts.transcribe.") as td:
        tmp = Path(td)
        wav_path = tmp / "audio.wav"

        media_input: str = _resolve_media_url(media_url, execute=execute)
        u = media_url.lower()
        resolved_u = media_input.lower()
        should_prefetch = resolved_u.startswith(("http://", "https://")) and ".m3u8" not in resolved_u and _looks_like_direct_media_url(resolved_u)
        if should_prefetch:
            media_path = tmp / "media"
            try:
                # Quick probe: if we can't even start receiving bytes quickly, treat it as dead for this run.
                # (Don't throttle the real download; we only want fast-fail on "dead/stalled" URLs.)
                probe_path = tmp / "media.probe"
                with _timed("media_probe"):
                    _run(
                        [
                            "curl",
                            "-f",
                            "-sS",
                            "-L",
                            "--max-time",
                            str(int(_MEDIA_PROBE_MAX_TIME_SECONDS)),
                            "--connect-timeout",
                            str(int(_MEDIA_CONNECT_TIMEOUT_SECONDS)),
                            "-A",
                            "vodcasts-transcripts/1.0",
                            "-o",
                            str(probe_path),
                            "--range",
                            "0-0",
                            media_input,
                        ],
                        execute=True,
                    )
                with _timed("media_download"):
                    _run(
                        [
                            "curl",
                            "-f",
                            "-sS",
                            "-L",
                            "--connect-timeout",
                            str(int(_MEDIA_CONNECT_TIMEOUT_SECONDS)),
                            "-A",
                            "vodcasts-transcripts/1.0",
                            "-o",
                            str(media_path),
                            media_input,
                        ],
                        execute=True,
                    )
            except Exception as e:
                raise MediaDownloadError(str(e)) from e
            if not media_path.exists():
                raise MediaDownloadError("media download produced no file")
            sz = int(media_path.stat().st_size)
            if sz <= 0:
                raise MediaDownloadError("media download produced empty file")
            print(f"[media] bytes={sz} url={media_input}")
            media_input = str(media_path)

        ffmpeg_label = "ffmpeg_decode" if media_input != media_url else "ffmpeg_fetch_decode"
        with _timed(ffmpeg_label):
            _run(
                [
                    ffmpeg_cmd,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    media_input,
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    str(wav_path),
                ],
                execute=True,
            )

        if spot_mp3_path is not None:
            spot_mp3_path.parent.mkdir(parents=True, exist_ok=True)
            _run(
                [
                    ffmpeg_cmd,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(wav_path),
                    "-t",
                    str(max(1, int(spot_seconds or 0))),
                    "-vn",
                    "-acodec",
                    "libmp3lame",
                    "-b:a",
                    str(spot_bitrate or "96k"),
                    str(spot_mp3_path),
                ],
                execute=True,
            )

        with _timed("transcribe"):
            srt_text, vtt_text = backend.transcribe(wav_path, language)
        srt_text, vtt_text = coerce_subtitle_output(srt_text, vtt_text)
        _ensure_non_empty_transcript(srt_text, vtt_text)
        return srt_text, vtt_text or _srt_to_vtt(srt_text)


def _process_work_item(
    *,
    item: WorkItem,
    out_dir: Path,
    backend: Any,
    require_cuda: bool,
    download_provided: bool,
    execute: bool,
    generate_missing: bool,
    timeout_seconds: int,
    user_agent: str,
    min_text_chars: int,
    min_words: int,
    ffmpeg_cmd: str,
    language: str,
    spot_check_seconds: int,
    spot_check_bitrate: str,
    sanity_failures: set[tuple[str, str]],
) -> WorkOutcome:
    ep = item.ep
    ep_slug = _norm(ep.get("slug") or "")
    media_url = _norm((ep.get("media") or {}).get("url") if isinstance(ep.get("media"), dict) else "")
    feed_out = out_dir / item.src.id
    final_vtt = feed_out / f"{ep_slug}.vtt"
    cand = _pick_best_transcript_candidate(ep)

    chosen = ""
    provided_count = 0
    rejected_provided = 0
    generated_count = 0
    spotcheck_count = 0
    errors = 0
    dead_media = False
    spot_mp3: Path | None = None

    try:
        if item.action == "download":
            if cand is None:
                raise ValueError("planned download but no transcript candidate exists")
            print(f"[want] {item.src.id}/{ep_slug}: provided transcript ({cand.typ}, {cand.lang}) {cand.url}")
            b = _download_bytes(
                cand.url,
                timeout_seconds=int(timeout_seconds),
                user_agent=str(user_agent),
                execute=bool(execute),
                label=f"download_provided {item.src.id}/{ep_slug}",
            )
            if b is None and not bool(execute):
                chosen = "provided"
            else:
                assert b is not None
                text = b.decode("utf-8", errors="replace")
                with _timed("validate_provided"):
                    _provided_kind, vtt = _normalize_provided_subtitles_to_vtt(
                        text,
                        min_chars=int(min_text_chars),
                        min_words=int(min_words),
                    )
                with _timed("write_vtt"):
                    _write_text(final_vtt, vtt, execute=bool(execute))
                chosen = "provided"
                provided_count += 1

        elif item.action == "generate":
            if not media_url:
                raise ValueError("planned generate but missing media url")
            if require_cuda and not bool(execute):
                chosen = "generated"
            else:
                if require_cuda:
                    print("[gpu] require_cuda=1 device=cuda (no cpu fallback)")
                print(f"[gen] {item.src.id}/{ep_slug}: whisperx from media {media_url}")

                srt_text, vtt_text = _generate_transcript(
                    backend=backend,
                    media_url=media_url,
                    ffmpeg_cmd=str(ffmpeg_cmd),
                    language=str(language),
                    spot_mp3_path=None,
                    spot_seconds=int(spot_check_seconds or 600),
                    spot_bitrate=str(spot_check_bitrate or "96k"),
                    execute=bool(execute),
                )

                vtt_out = vtt_text or (_srt_to_vtt(srt_text) if srt_text else "")
                vtt_out = _normalize_vtt_timestamp_commas(vtt_out)
                if not _vtt_seems_complete(vtt_out, min_chars=_EXISTING_VTT_MIN_CHARS, min_words=_EXISTING_VTT_MIN_WORDS):
                    spot_mp3 = _capture_failure_spotcheck(
                        media_url=media_url,
                        ffmpeg_cmd=str(ffmpeg_cmd),
                        spot_mp3_path=feed_out / f"{ep_slug}.spotcheck.mp3",
                        spot_seconds=int(spot_check_seconds or 600),
                        spot_bitrate=str(spot_check_bitrate or "96k"),
                        execute=bool(execute),
                    )
                    if spot_mp3 is not None:
                        spotcheck_count += 1
                    _move_failed_to_review(item.src.id, ep_slug, vtt_out, spot_mp3, execute=bool(execute), cache_feed_dir=feed_out)
                    _append_sanity_failure(item.src.id, ep_slug, "generated subtitles failed transcript sanity")
                    raise GeneratedTranscriptRejected("generated subtitles failed transcript sanity")
                with _timed("write_vtt"):
                    _write_text(final_vtt, vtt_out, execute=bool(execute))
                chosen = "generated"
                generated_count += 1
        else:
            raise ValueError(f"unknown action: {item.action}")

    except MediaDownloadError as e:
        errors += 1
        chosen = "error"
        dead_media = True
        print(f"[dead] {item.src.id}/{ep_slug}: media unreachable; skipping rest of feed this run: {e}")

    except Exception as e:
        is_reject = isinstance(e, ProvidedTranscriptRejected)
        is_generated_reject = isinstance(e, GeneratedTranscriptRejected)
        is_validation_error = isinstance(e, SubtitleValidationError)
        if is_reject:
            rejected_provided += 1
            print(f"[reject] {item.src.id}/{ep_slug}: {e}")
            chosen = "rejected"
        elif is_generated_reject:
            errors += 1
            print(f"[error] {item.src.id}/{ep_slug}: {e}")
            chosen = "error"
        else:
            errors += 1
            print(f"[error] {item.src.id}/{ep_slug}: {e}")
            chosen = "error"
            if item.action == "generate":
                _log_whisperx_empty_diag(
                    feed_id=item.src.id,
                    ep_slug=ep_slug,
                    media_url=media_url or "",
                    source="generate_failed",
                    error=str(e),
                    exc_type=type(e).__name__,
                )
                spot_mp3 = _capture_failure_spotcheck(
                    media_url=media_url,
                    ffmpeg_cmd=str(ffmpeg_cmd),
                    spot_mp3_path=feed_out / f"{ep_slug}.spotcheck.mp3",
                    spot_seconds=int(spot_check_seconds or 600),
                    spot_bitrate=str(spot_check_bitrate or "96k"),
                    execute=bool(execute),
                )
                if spot_mp3 is not None:
                    spotcheck_count += 1
                review_vtt = e.vtt_text if is_validation_error else ""
                _move_failed_to_review(item.src.id, ep_slug, review_vtt, spot_mp3, execute=bool(execute), cache_feed_dir=feed_out)
                if is_validation_error:
                    _append_sanity_failure(item.src.id, ep_slug, "generated subtitles failed VTT validation")

        if item.action == "download" and bool(generate_missing) and media_url:
            if (item.src.id, ep_slug) in sanity_failures:
                print(f"[skip] {item.src.id}/{ep_slug}: in transcript-sanity-failures (remove to retry)")
            elif require_cuda and not bool(execute):
                pass
            else:
                why = "rejected" if is_reject else "download failed"
                print(f"[fallback] {item.src.id}/{ep_slug}: generating because provided transcript {why}")
                try:
                    srt_text, vtt_text = _generate_transcript(
                        backend=backend,
                        media_url=media_url,
                        ffmpeg_cmd=str(ffmpeg_cmd),
                        language=str(language),
                        spot_mp3_path=None,
                        spot_seconds=int(spot_check_seconds or 600),
                        spot_bitrate=str(spot_check_bitrate or "96k"),
                        execute=bool(execute),
                    )
                    vtt_out = vtt_text or (_srt_to_vtt(srt_text) if srt_text else "")
                    vtt_out = _normalize_vtt_timestamp_commas(vtt_out)
                    if not _vtt_seems_complete(vtt_out, min_chars=_EXISTING_VTT_MIN_CHARS, min_words=_EXISTING_VTT_MIN_WORDS):
                        spot_mp3 = _capture_failure_spotcheck(
                            media_url=media_url,
                            ffmpeg_cmd=str(ffmpeg_cmd),
                            spot_mp3_path=feed_out / f"{ep_slug}.spotcheck.mp3",
                            spot_seconds=int(spot_check_seconds or 600),
                            spot_bitrate=str(spot_check_bitrate or "96k"),
                            execute=bool(execute),
                        )
                        if spot_mp3 is not None:
                            spotcheck_count += 1
                        _move_failed_to_review(item.src.id, ep_slug, vtt_out, spot_mp3, execute=bool(execute), cache_feed_dir=feed_out)
                        _append_sanity_failure(item.src.id, ep_slug, "fallback generated subtitles failed transcript sanity")
                        raise GeneratedTranscriptRejected("fallback generated subtitles failed transcript sanity")
                    with _timed("write_vtt"):
                        _write_text(final_vtt, vtt_out, execute=bool(execute))
                    chosen = "generated"
                    generated_count += 1
                except MediaDownloadError as e2:
                    errors += 1
                    chosen = "error"
                    dead_media = True
                    print(f"[dead] {item.src.id}/{ep_slug}: media unreachable; skipping rest of feed this run: {e2}")
                except Exception as e2:
                    errors += 1
                    chosen = "error"
                    print(f"[error] {item.src.id}/{ep_slug}: fallback generation failed: {e2}")
                    is_generated_reject_2 = isinstance(e2, GeneratedTranscriptRejected)
                    is_validation_error_2 = isinstance(e2, SubtitleValidationError)
                    _log_whisperx_empty_diag(
                        feed_id=item.src.id,
                        ep_slug=ep_slug,
                        media_url=media_url or "",
                        source="fallback_generate_failed",
                        error=str(e2),
                        exc_type=type(e2).__name__,
                    )
                    if not is_generated_reject_2:
                        spot_mp3 = _capture_failure_spotcheck(
                            media_url=media_url,
                            ffmpeg_cmd=str(ffmpeg_cmd),
                            spot_mp3_path=feed_out / f"{ep_slug}.spotcheck.mp3",
                            spot_seconds=int(spot_check_seconds or 600),
                            spot_bitrate=str(spot_check_bitrate or "96k"),
                            execute=bool(execute),
                        )
                        if spot_mp3 is not None:
                            spotcheck_count += 1
                        review_vtt = e2.vtt_text if is_validation_error_2 else ""
                        _move_failed_to_review(item.src.id, ep_slug, review_vtt, spot_mp3, execute=bool(execute), cache_feed_dir=feed_out)
                        if is_validation_error_2:
                            _append_sanity_failure(item.src.id, ep_slug, "fallback generated subtitles failed VTT validation")

    return WorkOutcome(
        src_id=item.src.id,
        ep_slug=ep_slug,
        action=item.action,
        chosen=(chosen or "error"),
        provided_count=provided_count,
        rejected_provided=rejected_provided,
        generated_count=generated_count,
        spotcheck_count=spotcheck_count,
        errors=errors,
        dead_media=dead_media,
    )


def main() -> None:
    args = _parse_args()

    # Prefer the RAM-disk temp drive on Windows when available.
    # Use a per-run temp root so we don't leave files behind on the ramdisk.
    run_temp = None
    old_tempdir = getattr(tempfile, "tempdir", None)
    old_env_temp = os.environ.get("TEMP")
    old_env_tmp = os.environ.get("TMP")

    fast_root = _pick_fast_temp_root() if os.name == "nt" else None
    if fast_root is None and os.name == "nt" and bool(args.execute):
        raise RuntimeError("Q:\\ RAM disk not found; refusing to run in --execute mode to avoid writing temp files to the SSD.")
    if fast_root is not None:
        run_temp = tempfile.TemporaryDirectory(prefix="vodcasts.tmp.", dir=str(fast_root))
        tempfile.tempdir = run_temp.name
        os.environ["TEMP"] = run_temp.name
        os.environ["TMP"] = run_temp.name
        print(f"[temp] dir={run_temp.name}")

        def _cleanup_temp() -> None:
            try:
                tempfile.tempdir = old_tempdir
            except Exception:
                pass
            if old_env_temp is None:
                os.environ.pop("TEMP", None)
            else:
                os.environ["TEMP"] = old_env_temp
            if old_env_tmp is None:
                os.environ.pop("TMP", None)
            else:
                os.environ["TMP"] = old_env_tmp
            try:
                run_temp.cleanup()
            except Exception:
                pass

        atexit.register(_cleanup_temp)
    else:
        print(f"[temp] dir={tempfile.gettempdir()} (no Q:/ ramdisk found)")

    env_name = _active_env()
    feeds_defaulted = not str(args.feeds or "").strip()
    cache_defaulted = not str(args.cache or "").strip()
    feeds_path = Path(args.feeds) if not feeds_defaulted else (VODCASTS_ROOT / "feeds" / f"{env_name}.md")
    cache_dir = (Path(args.cache) if not cache_defaulted else (VODCASTS_ROOT / "cache" / env_name)).resolve()
    feeds_cache_dir = cache_dir / "feeds"
    out_dir = (Path(args.out) if args.out else (cache_dir / "transcripts")).resolve()
    # Transcripts always go to project cache, never temp/ramdisk
    if str(out_dir).upper().startswith("Q:"):
        raise RuntimeError(f"transcript out_dir must not be on temp drive Q:; got {out_dir}")

    cfg = load_sources_config(feeds_path)
    sources = list(cfg.sources)

    tag = _norm(args.tag)
    only_source_id = _norm(args.source_id or "")
    if only_source_id:
        sources = [s for s in sources if s.id == only_source_id]
    elif not args.all_sources and tag:
        sources = [s for s in sources if _matches_any_tag(s, tag)]
    sources = [s for s in sources if s.id not in EXCLUDED_TRANSCRIPT_SOURCE_IDS]

    # Focus tagged sources first without excluding others when --all-sources is set.
    if args.all_sources and tag:
        sources.sort(key=lambda s: (not _matches_any_tag(s, tag), s.id))
    else:
        sources.sort(key=lambda s: s.id)

    only_episode_slug = _norm(args.episode_slug or "")

    env_part = f" env={env_name}" if (feeds_defaulted or cache_defaulted) else ""
    out_abs = str(out_dir.resolve())
    print(f"[plan]{env_part} feeds={feeds_path} cache={cache_dir}")
    print(f"[plan] transcript out (absolute): {out_abs}")
    print(
        "[plan] "
        + f"sources={len(sources)} download_provided={bool(args.download_provided)} "
        + f"generate_missing={bool(args.generate_missing)} execute={bool(args.execute)} "
        + f"prefer_shorter={bool(args.prefer_shorter)}"
    )
    if only_source_id:
        print(f"[plan] filter: source_id={only_source_id}")
    if only_episode_slug:
        print(f"[plan] filter: episode_slug={only_episode_slug}")

    require_cuda = bool(args.generate_missing)
    whisperx_device = _norm(args.whisperx_device or "cuda").lower()
    if require_cuda and whisperx_device != "cuda":
        raise ValueError("CUDA is required for generation; --whisperx-device must be 'cuda'.")

    # Note: we only enforce CUDA availability after planning, and only if we actually need generation.

    max_total = int(args.max_episodes_total or 0)

    sanity_failures = _load_sanity_failures()
    if sanity_failures:
        print(f"[plan] transcript_sanity_failures={len(sanity_failures)} (skip listed until removed from {_TRANSCRIPT_SANITY_FAILURES_PATH.name})")

    backend_name = str(args.backend or "whisperx").strip().lower()
    if backend_name == "whisperx":
        backend = get_backend(
            "whisperx",
            worker_url=str(args.whisperx_worker_url or ""),
            whisperx_cmd=str(args.whisperx),
            model=str(args.whisperx_model),
            device=str(args.whisperx_device),
            compute_type=str(args.whisperx_compute_type),
            extra_args=str(args.whisperx_extra_args),
        )
    elif backend_name == "parakeet":
        backend = get_backend("parakeet", device="cuda", config="balanced")
    elif backend_name == "moonshine":
        backend = get_backend("moonshine", language=str(args.language))
    else:
        raise ValueError(f"unknown backend: {backend_name!r}")
    print(f"[plan] backend={backend_name}")

    missing_feed = 0
    skipped_existing = 0
    skipped_sanity_failure = 0
    planned_download = 0
    planned_download_with_media_for_fallback = 0
    planned_generate = 0
    planned_missed = 0

    work: list[WorkItem] = []
    for src in sources:
        feed_path = feeds_cache_dir / f"{src.id}.xml"
        if not feed_path.exists():
            missing_feed += 1
            continue

        xml_text = feed_path.read_text(encoding="utf-8", errors="replace")
        _features, channel_title, episodes, _image = parse_feed_for_manifest(xml_text, source_id=src.id, source_title=src.title)

        eps = [e for e in (episodes or []) if isinstance(e, dict)]
        # Prefer more recent entries when a feed's ordering is ambiguous.
        eps.sort(key=lambda e: _norm(e.get("dateText") or ""), reverse=True)
        max_per_feed = int(max_episodes_per_feed or 0)
        if max_per_feed > 0:
            base_limit = max_per_feed * 2 if src.id in HIGH_VALUE_FEEDS else max_per_feed
            first_batch = eps[:base_limit]
            remainder = eps[base_limit:]
            short_bonus = [e for e in remainder if _is_short_episode(e)][:base_limit]
            eps = first_batch + short_bonus
        if only_episode_slug:
            eps = [e for e in eps if isinstance(e, dict) and _norm(e.get("slug") or "") == only_episode_slug]
        elif bool(args.prefer_shorter):
            eps.sort(
                key=lambda e: (
                    _duration_key(e),
                    _recency_key(e),
                )
            )

        feed_out = (out_dir / src.id).resolve()
        for ep in eps:
            ep_slug = _norm(ep.get("slug") or "")
            if not ep_slug:
                continue

            final_vtt = (feed_out / f"{ep_slug}.vtt").resolve()

            media_url = _norm((ep.get("media") or {}).get("url") if isinstance(ep.get("media"), dict) else "")
            cand = _pick_best_transcript_candidate(ep)

            required: list[Path] = []
            action = ""
            if cand is not None and bool(args.download_provided):
                action = "download"
                required = [final_vtt]
            elif bool(args.generate_missing) and media_url and (
                bool(args.generate_missing_all_sources) or only_source_id or (not args.all_sources) or (not tag) or _matches_any_tag(src, tag)
            ):
                if (src.id, ep_slug) in sanity_failures:
                    skipped_sanity_failure += 1
                    continue
                action = "generate"
                required = [final_vtt]
            else:
                planned_missed += 1
                continue

            # Belt-and-suspenders: skip if we already have this episode (glob by exact slug, avoids path bugs)
            skipped_via_glob = False
            if not bool(args.refresh) and action == "generate":
                for p in feed_out.glob("*.vtt"):
                    if p.stem == ep_slug:
                        try:
                            if p.stat().st_size > 1024:
                                _maybe_normalize_existing_vtt(p, execute=bool(args.execute))
                                skipped_existing += 1
                                skipped_via_glob = True
                                break
                        except OSError:
                            pass
                if skipped_via_glob:
                    continue

            if not bool(args.refresh) and required and all(p.exists() for p in required):
                # Restartable runs: treat an existing valid VTT as complete and never regenerate it.
                # Fast path: substantial file (>1KB) = assume complete, never duplicate work
                try:
                    sz = final_vtt.stat().st_size
                    if sz > 1024:
                        _maybe_normalize_existing_vtt(final_vtt, execute=bool(args.execute))
                        skipped_existing += 1
                        continue
                except OSError:
                    pass
                if _vtt_file_seems_complete(final_vtt, min_chars=_EXISTING_VTT_MIN_CHARS, min_words=_EXISTING_VTT_MIN_WORDS):
                    _maybe_normalize_existing_vtt(final_vtt, execute=bool(args.execute))
                    skipped_existing += 1
                    continue
                # File exists but failed completeness - would regenerate; log why
                try:
                    txt = final_vtt.read_text(encoding="utf-8", errors="replace")
                    ts = _count_vtt_timestamps(txt)
                    print(f"[plan] {src.id}/{ep_slug}: existing file incomplete (timestamps={ts} size={final_vtt.stat().st_size}) - will regenerate")
                except Exception:
                    print(f"[plan] {src.id}/{ep_slug}: existing file unreadable - will regenerate")

            work.append(WorkItem(src=src, channel_title=channel_title, ep=ep, action=action))
            if action == "download":
                planned_download += 1
                if bool(args.generate_missing) and bool(media_url):
                    planned_download_with_media_for_fallback += 1
            else:
                planned_generate += 1

            if max_total and len(work) >= max_total:
                break
        if max_total and len(work) >= max_total:
            break

    if bool(args.prefer_shorter):
        work.sort(
            key=lambda item: (
                _duration_key(item.ep),
                _recency_key(item.ep),
                item.src.id,
                _norm(item.ep.get("slug") or ""),
            )
        )

    print(
        "[plan] "
        + f"episodes_to_process={len(work)} download={planned_download} generate={planned_generate} "
        + f"skipped_existing={skipped_existing} skipped_sanity_failure={skipped_sanity_failure} "
        + f"missing_feed={missing_feed} missed_no_action={planned_missed}"
    )

    # Generation can also happen as a fallback when a provided transcript is rejected.
    # All backends require CUDA/GPU; no CPU fallback.
    if require_cuda and bool(args.execute) and (planned_generate > 0 or planned_download_with_media_for_fallback > 0):
        try:
            import torch  # type: ignore

            if not getattr(torch, "cuda", None) or not torch.cuda.is_available():
                raise RuntimeError("torch.cuda.is_available() is False")
        except Exception as e:
            raise RuntimeError(
                "CUDA is required for WhisperX generation but is not available.\n"
                "Fix: run scripts/audio-to-transcripts/setup-venv.ps1 (it installs torch+cu128), then retry."
            ) from e

    # Progress UI (rich if available).
    use_rich = False
    progress = None
    try:
        from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn  # type: ignore

        use_rich = True
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            transient=True,
        )
    except Exception:
        use_rich = False

    processed = 0
    provided_count = 0
    rejected_provided = 0
    generated_count = 0
    spotcheck_count = 0
    errors = 0

    task = None
    if use_rich and progress is not None:
        progress.start()
        task = progress.add_task("transcripts", total=len(work))

    dead_media_feeds: set[str] = set()
    skipped_dead_media = 0

    def _advance(desc: str) -> None:
        if use_rich and progress is not None and task is not None:
            progress.update(task, advance=1, description=desc)
        else:
            done = processed + 1
            total = max(1, len(work))
            print(f"[{done}/{total}] {desc}")

    def _set_status(desc: str) -> None:
        if use_rich and progress is not None and task is not None:
            progress.update(task, description=desc)

    interrupted = False
    try:
        concurrency = int(args.concurrency or 0)
        if concurrency > 0:
            max_workers = concurrency
        else:
            max_workers = _TRANSCRIPTION_CONCURRENCY if bool(args.execute) and bool(args.generate_missing) else 1
        pending = list(work)
        active_feeds: set[str] = set()
        future_to_item: dict[Future[WorkOutcome], WorkItem] = {}

        def _maybe_skip_without_worker(item: WorkItem) -> bool:
            nonlocal skipped_existing, skipped_dead_media, processed
            ep_slug = _norm(item.ep.get("slug") or "")
            if item.src.id in dead_media_feeds:
                _advance(f"skip: {item.src.id}/{ep_slug}")
                skipped_dead_media += 1
                print(f"[skip] {item.src.id}/{ep_slug}: skipped (media dead earlier in this feed)")
                processed += 1
                return True
            final_vtt = out_dir / item.src.id / f"{ep_slug}.vtt"
            if not bool(args.refresh) and final_vtt.exists():
                if _vtt_file_seems_complete(final_vtt, min_chars=_EXISTING_VTT_MIN_CHARS, min_words=_EXISTING_VTT_MIN_WORDS):
                    _maybe_normalize_existing_vtt(final_vtt, execute=bool(args.execute))
                    skipped_existing += 1
                    _advance(f"skip: {item.src.id}/{ep_slug}")
                    print(f"[skip] {item.src.id}/{ep_slug}: already have valid vtt")
                    print(f"[ok] {item.src.id}/{ep_slug}: skipped_existing")
                    processed += 1
                    return True
            return False

        def _pop_next_runnable() -> WorkItem | None:
            i = 0
            while i < len(pending):
                item = pending[i]
                if item.src.id in active_feeds:
                    i += 1
                    continue
                pending.pop(i)
                if _maybe_skip_without_worker(item):
                    continue
                return item
            return None

        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="vodcasts-transcripts") as pool:
            while pending or future_to_item:
                while len(future_to_item) < max_workers:
                    item = _pop_next_runnable()
                    if item is None:
                        break
                    _set_status(f"{item.action}: {item.src.id}/{_norm(item.ep.get('slug') or '')}")
                    active_feeds.add(item.src.id)
                    fut = pool.submit(
                        _process_work_item,
                        item=item,
                        out_dir=out_dir,
                        backend=backend,
                        require_cuda=require_cuda,
                        download_provided=bool(args.download_provided),
                        execute=bool(args.execute),
                        generate_missing=bool(args.generate_missing),
                        timeout_seconds=int(args.timeout_seconds),
                        user_agent=str(args.user_agent),
                        min_text_chars=int(args.min_text_chars),
                        min_words=int(args.min_words),
                        ffmpeg_cmd=str(args.ffmpeg),
                        language=str(args.language),
                        spot_check_seconds=int(args.spot_check_seconds or 600),
                        spot_check_bitrate=str(args.spot_check_bitrate or "96k"),
                        sanity_failures=sanity_failures,
                    )
                    future_to_item[fut] = item

                if not future_to_item:
                    continue

                done, _pending_futures = wait(tuple(future_to_item.keys()), return_when=FIRST_COMPLETED)
                for fut in done:
                    item = future_to_item.pop(fut)
                    active_feeds.discard(item.src.id)
                    outcome = fut.result()
                    if outcome.dead_media:
                        dead_media_feeds.add(item.src.id)
                    provided_count += int(outcome.provided_count)
                    rejected_provided += int(outcome.rejected_provided)
                    generated_count += int(outcome.generated_count)
                    spotcheck_count += int(outcome.spotcheck_count)
                    errors += int(outcome.errors)
                    _advance(f"{outcome.action}: {outcome.src_id}/{outcome.ep_slug}")
                    print(f"[ok] {outcome.src_id}/{outcome.ep_slug}: {outcome.chosen}")
                    processed += 1

    except KeyboardInterrupt:
        interrupted = True
        print("[cancel] interrupted; exiting")
    finally:
        if use_rich and progress is not None:
            try:
                progress.stop()
            except Exception:
                pass

    if bool(args.execute) and out_dir.exists():
        removed = 0
        for d in sorted(out_dir.iterdir()):
            if d.is_dir() and not any(d.iterdir()):
                try:
                    d.rmdir()
                    removed += 1
                except OSError:
                    pass
        if removed:
            print(f"[cleanup] removed {removed} empty feed dir(s) from {out_dir.relative_to(VODCASTS_ROOT)}")

    print(
        "[done] "
        + f"processed={processed} provided={provided_count} rejected_provided={rejected_provided} generated={generated_count} "
        + f"spotcheck_mp3={spotcheck_count} skipped_dead_media={skipped_dead_media} dead_feeds={len(dead_media_feeds)} "
        + f"skipped_existing={skipped_existing} missing_feed={missing_feed} errors={errors}"
    )
    if interrupted:
        raise SystemExit(130)


if __name__ == "__main__":
    main()
