from __future__ import annotations

import argparse
import json
import os
import re
import sys
import subprocess
import tempfile
import time
import shlex
import html
import signal
import atexit
import urllib.error
import urllib.request
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
from whisperx_worker_common import WorkerWhisperxOptions, parse_worker_extra_args


_PLAYABLE_TYPES = {"text/vtt", "application/x-subrip", "application/srt"}

_MEDIA_CONNECT_TIMEOUT_SECONDS = 5
_MEDIA_PROBE_MAX_TIME_SECONDS = 10

_EXISTING_VTT_MIN_CHARS = 80
_EXISTING_VTT_MIN_WORDS = 10


class MediaDownloadError(RuntimeError):
    pass


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
        help="WhisperX device (default: cuda). Use --allow-cpu to permit cpu fallback.",
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
        "--allow-cpu",
        action="store_true",
        help="Allow CPU execution for WhisperX generation (default: disabled; generation requires CUDA).",
    )

    # Spot-check: keep a short MP3 for occasional manual review (generation only).
    p.add_argument("--spot-check-every", type=int, default=0, help="Keep ~1 in N generated MP3 spot-checks (default: 0 disables).")
    p.add_argument("--spot-check-seconds", type=int, default=600, help="Spot-check MP3 length in seconds (default: 600 = 10 minutes).")
    p.add_argument("--spot-check-bitrate", default="96k", help="Spot-check MP3 bitrate (default: 96k).")

    # Acceptance heuristics for provided transcripts
    p.add_argument("--min-text-chars", type=int, default=200, help="Minimum extracted text chars to accept (default: 200).")
    p.add_argument("--min-words", type=int, default=30, help="Minimum extracted word count to accept (default: 30).")
    return p.parse_args()


def _norm(s: str) -> str:
    return str(s or "").strip()


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


_SRT_TS_RE = re.compile(r"^\d{2}:\d{2}:\d{2}[,.]\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}[,.]\d{3}")
_VTT_TS_RE = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}\.\d{3}")


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
        if _VTT_TS_RE.match(line) or _SRT_TS_RE.match(line):
            continue
        if "-->" in line and re.search(r"\d{2}:\d{2}:\d{2}[\.,]\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}[\.,]\d{3}", line):
            # tolerate non-standard timestamps
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
    """
    lines: list[str] = []
    changed = False
    for raw in (vtt or "").splitlines():
        line = raw.rstrip("\n")
        if "-->" in line and "," in line:
            fixed = re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", line)
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
    return any(_VTT_TS_RE.match(ln.strip()) for ln in s.splitlines()[:200])


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


def _count_srt_timestamps(text: str) -> int:
    return sum(1 for ln in (text or "").splitlines() if _SRT_TS_RE.match(ln.strip()))


def _count_vtt_timestamps(text: str) -> int:
    cnt = 0
    for ln in (text or "").splitlines():
        s = ln.strip()
        if _VTT_TS_RE.match(s):
            cnt += 1
            continue
        if "-->" in s and re.search(r"\d{2}:\d{2}:\d{2}[\.,]\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}[\.,]\d{3}", s):
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
    print(f"[write] {path}")
    if not execute:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _write_bytes(path: Path, data: bytes, *, execute: bool) -> None:
    print(f"[write] {path} ({len(data)} bytes)")
    if not execute:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


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


def _post_json(url: str, payload: dict[str, Any], *, timeout_seconds: int) -> dict[str, Any]:
    raw = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=raw,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=max(1, int(timeout_seconds))) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"worker http {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"worker unavailable: {e}") from e
    try:
        obj = json.loads(body.decode("utf-8", errors="replace"))
    except Exception as e:
        raise RuntimeError(f"worker returned invalid json: {e}") from e
    if not isinstance(obj, dict):
        raise RuntimeError("worker returned non-object json")
    if obj.get("ok") is False:
        raise RuntimeError(str(obj.get("error") or "worker_error"))
    return obj


def _worker_payload_for_options(
    *,
    wav_path: Path,
    whisperx_model: str,
    language: str,
    whisperx_device: str,
    whisperx_compute_type: str,
    options: WorkerWhisperxOptions,
) -> dict[str, Any]:
    payload = options.to_payload()
    payload.update(
        {
            "audio_path": str(wav_path),
            "model": str(whisperx_model or ""),
            "language": str(language or ""),
            "device": str(whisperx_device or ""),
            "compute_type": str(whisperx_compute_type or ""),
            "vad_method": str(options.vad_method or "silero"),
        }
    )
    return payload


def _generate_with_whisperx(
    *,
    media_url: str,
    ffmpeg_cmd: str,
    whisperx_cmd: str,
    whisperx_model: str,
    language: str,
    whisperx_device: str,
    whisperx_compute_type: str,
    whisperx_extra_args: str,
    whisperx_worker_url: str,
    spot_mp3_path: Path | None,
    spot_seconds: int,
    spot_bitrate: str,
    execute: bool,
) -> tuple[str, str]:
    """
    Returns (srt_text, vtt_text).
    """
    if not execute:
        # dry-run placeholder
        return "", ""

    worker_options, worker_unsupported = parse_worker_extra_args(whisperx_extra_args)

    with tempfile.TemporaryDirectory(prefix="vodcasts.whisperx.") as td:
        tmp = Path(td)
        wav_path = tmp / "audio.wav"
        out_dir = tmp / "out"
        out_dir.mkdir(parents=True, exist_ok=True)

        media_input: str = media_url
        u = media_url.lower()
        should_prefetch = u.startswith(("http://", "https://")) and ".m3u8" not in u and any(
            ext in u for ext in (".mp3", ".m4a", ".wav", ".mp4", ".m4v", ".mov", ".webm")
        )
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
                            media_url,
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
                            media_url,
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
            print(f"[media] bytes={sz} url={media_url}")
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

        worker_url = str(whisperx_worker_url or "").strip().rstrip("/")
        if worker_url:
            if worker_unsupported:
                unsupported = " ".join(worker_unsupported)
                print(f"[warn] worker unsupported extra args ({unsupported}); falling back to whisperx CLI")
            else:
                payload = _worker_payload_for_options(
                    wav_path=wav_path,
                    whisperx_model=whisperx_model,
                    language=language,
                    whisperx_device=whisperx_device,
                    whisperx_compute_type=whisperx_compute_type,
                    options=worker_options,
                )
                with _timed("whisperx_worker"):
                    res = _post_json(f"{worker_url}/transcribe", payload, timeout_seconds=max(600, int(30 + spot_seconds)))
                srt_text = str(res.get("srt_text") or "")
                vtt_text = str(res.get("vtt_text") or "")
                if srt_text or vtt_text:
                    return srt_text, vtt_text

        cmd = [
            whisperx_cmd,
            str(wav_path),
            "--model",
            whisperx_model,
            "--language",
            language,
            "--device",
            whisperx_device,
            "--compute_type",
            whisperx_compute_type,
            "--output_dir",
            str(out_dir),
            "--output_format",
            "srt",
            "--verbose",
            "False",
        ]
        extra = (whisperx_extra_args or "").strip()
        if not extra:
            # Avoid pyannote/torchcodec dependency issues (and speed up) unless explicitly overridden.
            extra = "--vad_method silero"
        cmd += shlex.split(extra)
        with _timed("whisperx"):
            _run(cmd, execute=True)

        # WhisperX typically writes <stem>.srt (and often json/txt) into output_dir.
        base = wav_path.stem
        srt_path = out_dir / f"{base}.srt"
        vtt_path = out_dir / f"{base}.vtt"
        if srt_path.exists():
            srt_text = srt_path.read_text(encoding="utf-8", errors="replace")
            return srt_text, _srt_to_vtt(srt_text)
        if vtt_path.exists():
            vtt_text = vtt_path.read_text(encoding="utf-8", errors="replace")
            # best-effort: also return an SRT-ish variant
            return "", vtt_text

        # Fallback: take any .srt produced.
        any_srt = next(iter(out_dir.glob("*.srt")), None)
        if any_srt and any_srt.exists():
            srt_text = any_srt.read_text(encoding="utf-8", errors="replace")
            return srt_text, _srt_to_vtt(srt_text)

        raise ValueError(f"whisperx produced no .srt/.vtt in {out_dir}")


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
    cache_dir = Path(args.cache) if not cache_defaulted else (VODCASTS_ROOT / "cache" / env_name)
    feeds_cache_dir = cache_dir / "feeds"
    out_dir = Path(args.out) if args.out else (cache_dir / "transcripts")

    cfg = load_sources_config(feeds_path)
    sources = list(cfg.sources)

    tag = _norm(args.tag)
    only_source_id = _norm(args.source_id or "")
    if only_source_id:
        sources = [s for s in sources if s.id == only_source_id]
    elif not args.all_sources and tag:
        sources = [s for s in sources if _matches_any_tag(s, tag)]

    # Focus tagged sources first without excluding others when --all-sources is set.
    if args.all_sources and tag:
        sources.sort(key=lambda s: (not _matches_any_tag(s, tag), s.id))
    else:
        sources.sort(key=lambda s: s.id)

    only_episode_slug = _norm(args.episode_slug or "")

    env_part = f" env={env_name}" if (feeds_defaulted or cache_defaulted) else ""
    print(f"[plan]{env_part} feeds={feeds_path} cache={cache_dir} out={out_dir}")
    print(
        "[plan] "
        + f"sources={len(sources)} download_provided={bool(args.download_provided)} "
        + f"generate_missing={bool(args.generate_missing)} execute={bool(args.execute)}"
    )
    if only_source_id:
        print(f"[plan] filter: source_id={only_source_id}")
    if only_episode_slug:
        print(f"[plan] filter: episode_slug={only_episode_slug}")

    require_cuda = bool(args.generate_missing) and not bool(args.allow_cpu)
    whisperx_device = _norm(args.whisperx_device or "cuda").lower()
    if require_cuda and whisperx_device != "cuda":
        raise ValueError("CUDA is required (generation is enabled and --allow-cpu is not set), but --whisperx-device is not 'cuda'.")

    # Note: we only enforce CUDA availability after planning, and only if we actually need generation.

    @dataclass(frozen=True)
    class WorkItem:
        src: Source
        channel_title: str
        ep: dict[str, Any]
        action: str  # download|generate

    def _fnv1a32(s: str) -> int:
        h = 0x811C9DC5
        for ch in str(s or ""):
            h ^= ord(ch)
            h = (h * 0x01000193) & 0xFFFFFFFF
        return h

    def _should_spot_check(src_id: str, ep_slug: str) -> bool:
        every = int(args.spot_check_every or 0)
        if every <= 0:
            return False
        return (_fnv1a32(f"{src_id}/{ep_slug}") % every) == 0

    max_total = int(args.max_episodes_total or 0)

    missing_feed = 0
    skipped_existing = 0
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
        if args.max_episodes_per_feed and int(args.max_episodes_per_feed) > 0:
            eps = eps[: int(args.max_episodes_per_feed)]
        if only_episode_slug:
            eps = [e for e in eps if isinstance(e, dict) and _norm(e.get("slug") or "") == only_episode_slug]

        feed_out = out_dir / src.id
        for ep in eps:
            ep_slug = _norm(ep.get("slug") or "")
            if not ep_slug:
                continue

            final_vtt = feed_out / f"{ep_slug}.vtt"

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
                action = "generate"
                required = [final_vtt]
            else:
                planned_missed += 1
                continue

            if not bool(args.refresh) and required and all(p.exists() for p in required):
                # Restartable runs: treat an existing valid VTT as complete and never regenerate it.
                if _vtt_file_seems_complete(final_vtt, min_chars=_EXISTING_VTT_MIN_CHARS, min_words=_EXISTING_VTT_MIN_WORDS):
                    _maybe_normalize_existing_vtt(final_vtt, execute=bool(args.execute))
                    skipped_existing += 1
                    continue

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

    print(
        "[plan] "
        + f"episodes_to_process={len(work)} download={planned_download} generate={planned_generate} "
        + f"skipped_existing={skipped_existing} missing_feed={missing_feed} missed_no_action={planned_missed}"
    )

    # Generation can also happen as a fallback when a provided transcript is rejected,
    # so require CUDA when generation is enabled and could plausibly occur.
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

    interrupted = False
    try:
        for item in work:
            ep = item.ep
            ep_slug = _norm(ep.get("slug") or "")
            media_url = _norm((ep.get("media") or {}).get("url") if isinstance(ep.get("media"), dict) else "")

            if item.src.id in dead_media_feeds:
                _advance(f"skip: {item.src.id}/{ep_slug}")
                skipped_dead_media += 1
                print(f"[skip] {item.src.id}/{ep_slug}: skipped (media dead earlier in this feed)")
                processed += 1
                continue

            feed_out = out_dir / item.src.id
            final_vtt = feed_out / f"{ep_slug}.vtt"

            if not bool(args.refresh) and final_vtt.exists():
                if _vtt_file_seems_complete(final_vtt, min_chars=_EXISTING_VTT_MIN_CHARS, min_words=_EXISTING_VTT_MIN_WORDS):
                    _maybe_normalize_existing_vtt(final_vtt, execute=bool(args.execute))
                    skipped_existing += 1
                    chosen = "skipped_existing"
                    print(f"[skip] {item.src.id}/{ep_slug}: already have valid vtt")
                    print(f"[ok] {item.src.id}/{ep_slug}: {chosen}")
                    processed += 1
                    continue

            cand = _pick_best_transcript_candidate(ep)
            _advance(f"{item.action}: {item.src.id}/{ep_slug}")

            if bool(args.execute):
                feed_out.mkdir(parents=True, exist_ok=True)

            chosen = ""
            spot_mp3: Path | None = None

            try:
                if item.action == "download":
                    if cand is None:
                        raise ValueError("planned download but no transcript candidate exists")
                    print(f"[want] {item.src.id}/{ep_slug}: provided transcript ({cand.typ}, {cand.lang}) {cand.url}")
                    b = _download_bytes(
                        cand.url,
                        timeout_seconds=int(args.timeout_seconds),
                        user_agent=str(args.user_agent),
                        execute=bool(args.execute),
                        label=f"download_provided {item.src.id}/{ep_slug}",
                    )
                    if b is None and not bool(args.execute):
                        chosen = "provided"
                    else:
                        assert b is not None
                        text = b.decode("utf-8", errors="replace")
                        with _timed("validate_provided"):
                            _provided_kind, vtt = _normalize_provided_subtitles_to_vtt(
                                text, min_chars=int(args.min_text_chars), min_words=int(args.min_words)
                            )
                        with _timed("write_vtt"):
                            _write_text(final_vtt, vtt, execute=bool(args.execute))
                        chosen = "provided"
                        provided_count += 1

                elif item.action == "generate":
                    if not media_url:
                        raise ValueError("planned generate but missing media url")
                    if require_cuda and not bool(args.execute):
                        chosen = "generated"
                    else:
                        if require_cuda:
                            print("[gpu] require_cuda=1 device=cuda (no cpu fallback)")
                        print(f"[gen] {item.src.id}/{ep_slug}: whisperx from media {media_url}")

                        if bool(args.execute) and _should_spot_check(item.src.id, ep_slug):
                            spot_mp3 = feed_out / f"{ep_slug}.spotcheck.mp3"

                        srt_text, vtt_text = _generate_with_whisperx(
                            media_url=media_url,
                            ffmpeg_cmd=str(args.ffmpeg),
                            whisperx_cmd=str(args.whisperx),
                            whisperx_model=str(args.whisperx_model),
                            language=str(args.language),
                            whisperx_device=str(args.whisperx_device),
                            whisperx_compute_type=str(args.whisperx_compute_type),
                            whisperx_extra_args=str(args.whisperx_extra_args),
                            whisperx_worker_url=str(args.whisperx_worker_url),
                            spot_mp3_path=spot_mp3 if bool(args.execute) else None,
                            spot_seconds=int(args.spot_check_seconds or 600),
                            spot_bitrate=str(args.spot_check_bitrate or "96k"),
                            execute=bool(args.execute),
                        )

                        if spot_mp3 is not None:
                            spotcheck_count += 1

                        vtt_out = vtt_text or (_srt_to_vtt(srt_text) if srt_text else "")
                        vtt_out = _normalize_vtt_timestamp_commas(vtt_out)
                        if not _vtt_seems_complete(vtt_out, min_chars=_EXISTING_VTT_MIN_CHARS, min_words=_EXISTING_VTT_MIN_WORDS):
                            raise RuntimeError("generated subtitles failed transcript sanity")
                        with _timed("write_vtt"):
                            _write_text(final_vtt, vtt_out, execute=bool(args.execute))
                        chosen = "generated"
                        generated_count += 1
                else:
                    raise ValueError(f"unknown action: {item.action}")

            except MediaDownloadError as e:
                dead_media_feeds.add(item.src.id)
                errors += 1
                chosen = "error"
                print(f"[dead] {item.src.id}/{ep_slug}: media unreachable; skipping rest of feed this run: {e}")

            except Exception as e:
                is_reject = isinstance(e, ProvidedTranscriptRejected)
                if is_reject:
                    rejected_provided += 1
                    print(f"[reject] {item.src.id}/{ep_slug}: {e}")
                    chosen = "rejected"
                else:
                    errors += 1
                    print(f"[error] {item.src.id}/{ep_slug}: {e}")
                    chosen = "error"

                # If a provided transcript existed but was unusable / failed, allow generation as a fallback.
                if item.action == "download" and bool(args.generate_missing) and media_url:
                    if require_cuda and not bool(args.execute):
                        pass
                    else:
                        why = "rejected" if is_reject else "download failed"
                        print(f"[fallback] {item.src.id}/{ep_slug}: generating because provided transcript {why}")
                        try:
                            if bool(args.execute) and _should_spot_check(item.src.id, ep_slug):
                                spot_mp3 = feed_out / f"{ep_slug}.spotcheck.mp3"
                            srt_text, vtt_text = _generate_with_whisperx(
                                media_url=media_url,
                                ffmpeg_cmd=str(args.ffmpeg),
                                whisperx_cmd=str(args.whisperx),
                                whisperx_model=str(args.whisperx_model),
                                language=str(args.language),
                                whisperx_device=str(args.whisperx_device),
                                whisperx_compute_type=str(args.whisperx_compute_type),
                                whisperx_extra_args=str(args.whisperx_extra_args),
                                whisperx_worker_url=str(args.whisperx_worker_url),
                                spot_mp3_path=spot_mp3 if bool(args.execute) else None,
                                spot_seconds=int(args.spot_check_seconds or 600),
                                spot_bitrate=str(args.spot_check_bitrate or "96k"),
                                execute=bool(args.execute),
                            )
                            if spot_mp3 is not None:
                                spotcheck_count += 1
                            vtt_out = vtt_text or (_srt_to_vtt(srt_text) if srt_text else "")
                            vtt_out = _normalize_vtt_timestamp_commas(vtt_out)
                            if not _vtt_seems_complete(vtt_out, min_chars=_EXISTING_VTT_MIN_CHARS, min_words=_EXISTING_VTT_MIN_WORDS):
                                raise RuntimeError("fallback generated subtitles failed transcript sanity")
                            with _timed("write_vtt"):
                                _write_text(final_vtt, vtt_out, execute=bool(args.execute))
                            chosen = "generated"
                            generated_count += 1
                        except MediaDownloadError as e2:
                            dead_media_feeds.add(item.src.id)
                            errors += 1
                            chosen = "error"
                            print(f"[dead] {item.src.id}/{ep_slug}: media unreachable; skipping rest of feed this run: {e2}")
                        except Exception as e2:
                            errors += 1
                            chosen = "error"
                            print(f"[error] {item.src.id}/{ep_slug}: fallback generation failed: {e2}")

            print(f"[ok] {item.src.id}/{ep_slug}: {chosen}")
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
