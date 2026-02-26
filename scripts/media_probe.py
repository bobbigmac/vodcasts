from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_MP4_EXT_RE = re.compile(r"\.(mp4|m4v|mov)(\?|$)", re.IGNORECASE)
_HLS_RE = re.compile(r"\.m3u8(\?|$)", re.IGNORECASE)


@dataclass(frozen=True)
class MediaMeta:
    bytes: int | None = None
    duration_sec: int | None = None


def _curl_bytes(args: list[str], *, timeout_seconds: int) -> bytes:
    p = subprocess.run(
        ["curl", "-sS", "-L", "--max-time", str(int(timeout_seconds)), *args],
        capture_output=True,
    )
    if p.returncode != 0:
        raise RuntimeError((p.stderr or b"").decode("utf-8", errors="replace").strip() or f"curl failed ({p.returncode})")
    return p.stdout or b""


def _curl_text(args: list[str], *, timeout_seconds: int) -> str:
    return _curl_bytes(args, timeout_seconds=timeout_seconds).decode("utf-8", errors="replace")


def head_content_length(url: str, *, timeout_seconds: int, user_agent: str) -> int | None:
    """
    Best-effort Content-Length via HEAD. Avoids downloading bodies.
    """
    try:
        hdrs = _curl_text(["-I", "-A", user_agent, url], timeout_seconds=timeout_seconds)
    except Exception:
        return None
    # curl -L -I will print multiple header blocks; take the last content-length.
    clen = None
    for line in hdrs.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        if k.strip().lower() == "content-length":
            try:
                clen = int(v.strip())
            except Exception:
                pass
    return clen if (isinstance(clen, int) and clen > 0) else None


def _supports_range(url: str, *, timeout_seconds: int, user_agent: str) -> bool:
    """
    Probe for byte-range support with a 1-byte range request.
    """
    try:
        # We only need headers; use -D - with /dev/null output.
        p = subprocess.run(
            [
                "curl",
                "-sS",
                "-L",
                "--max-time",
                str(int(timeout_seconds)),
                "-A",
                user_agent,
                "-r",
                "0-0",
                "-o",
                "/dev/null",
                "-D",
                "-",
                url,
            ],
            capture_output=True,
            text=True,
        )
        if p.returncode != 0:
            return False
        # 206 Partial Content indicates range support.
        return " 206 " in (p.stdout or "") or p.stdout.startswith("HTTP/") and "206" in (p.stdout.splitlines()[0] or "")
    except Exception:
        return False


def _mp4_duration_from_mvhd(blob: bytes) -> int | None:
    """
    Parse an MP4 'mvhd' box from a byte blob.
    Returns duration in whole seconds when possible.
    """
    if not blob or b"mvhd" not in blob:
        return None

    def be_u32(off: int) -> int:
        return int.from_bytes(blob[off : off + 4], "big", signed=False)

    def be_u64(off: int) -> int:
        return int.from_bytes(blob[off : off + 8], "big", signed=False)

    hits = []
    start = 0
    while True:
        i = blob.find(b"mvhd", start)
        if i < 0:
            break
        hits.append(i)
        start = i + 4

    for i in hits:
        box_start = i - 4
        if box_start < 0:
            continue
        if box_start + 8 >= len(blob):
            continue
        size = be_u32(box_start)
        if size < 32 or box_start + size > len(blob):
            continue
        ver_flags_off = i + 4
        if ver_flags_off + 4 > len(blob):
            continue
        version = blob[ver_flags_off]
        if version == 0:
            timescale_off = ver_flags_off + 12
            duration_off = ver_flags_off + 16
            if duration_off + 4 > len(blob):
                continue
            timescale = be_u32(timescale_off)
            duration = be_u32(duration_off)
        elif version == 1:
            timescale_off = ver_flags_off + 20
            duration_off = ver_flags_off + 24
            if duration_off + 8 > len(blob):
                continue
            timescale = be_u32(timescale_off)
            duration = be_u64(duration_off)
        else:
            continue

        if timescale <= 0:
            continue
        dur_sec = duration / float(timescale)
        if not (0 < dur_sec < 24 * 3600):
            continue
        return int(round(dur_sec))

    return None


def mp4_duration_seconds(url: str, *, timeout_seconds: int, user_agent: str, max_probe_bytes: int = 1024 * 1024) -> int | None:
    """
    Best-effort MP4 duration using *bounded* range requests (never full download).

    We fetch up to `max_probe_bytes` from the start and end of the file and try
    to locate an 'mvhd' box.
    """
    if not _MP4_EXT_RE.search(url or ""):
        return None
    if not _supports_range(url, timeout_seconds=timeout_seconds, user_agent=user_agent):
        return None

    total = head_content_length(url, timeout_seconds=timeout_seconds, user_agent=user_agent)
    if not total or total <= 0:
        return None

    n = int(max(64 * 1024, min(int(max_probe_bytes), total)))
    head_end = min(total - 1, n - 1)
    tail_start = max(0, total - n)

    try:
        head = _curl_bytes(["-A", user_agent, "-r", f"0-{head_end}", url], timeout_seconds=timeout_seconds)
        tail = _curl_bytes(["-A", user_agent, "-r", f"{tail_start}-{total - 1}", url], timeout_seconds=timeout_seconds)
    except Exception:
        return None

    # Try head first, then tail, then combined (for boxes straddling).
    for blob in (head, tail, (head[-64 * 1024 :] + tail[:64 * 1024 :]) if head and tail else b""):
        d = _mp4_duration_from_mvhd(blob)
        if d:
            return d
    return None


def hls_duration_seconds(url: str, *, timeout_seconds: int, user_agent: str) -> int | None:
    """
    Best-effort HLS duration by summing EXTINF in a VOD playlist.
    Only works for VOD (requires EXT-X-ENDLIST).
    """
    if not _HLS_RE.search(url or ""):
        return None
    try:
        text = _curl_text(["-A", user_agent, url], timeout_seconds=timeout_seconds)
    except Exception:
        return None
    if "#EXTM3U" not in text:
        return None
    if "#EXT-X-ENDLIST" not in text:
        return None
    total = 0.0
    for m in re.finditer(r"^#EXTINF:([0-9]+(?:\\.[0-9]+)?)", text, re.MULTILINE):
        try:
            total += float(m.group(1))
        except Exception:
            pass
    if total <= 0:
        return None
    if total > 24 * 3600:
        return None
    return int(round(total))


def load_media_meta_cache(cache_dir: Path) -> dict[str, Any]:
    p = cache_dir / "media-meta.json"
    if not p.exists():
        return {"version": 1, "updated_at_unix": 0, "by_url": {}}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            raise ValueError("invalid")
        doc.setdefault("version", 1)
        doc.setdefault("updated_at_unix", 0)
        doc.setdefault("by_url", {})
        if not isinstance(doc["by_url"], dict):
            doc["by_url"] = {}
        return doc
    except Exception:
        return {"version": 1, "updated_at_unix": 0, "by_url": {}}


def save_media_meta_cache(cache_dir: Path, doc: dict[str, Any]) -> None:
    p = cache_dir / "media-meta.json"
    doc = dict(doc or {})
    doc["version"] = 1
    doc["updated_at_unix"] = int(time.time())
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def get_cached_meta(doc: dict[str, Any], url: str, *, max_age_days: int = 30) -> MediaMeta | None:
    by = (doc or {}).get("by_url") or {}
    if not isinstance(by, dict):
        return None
    ent = by.get(url)
    if not isinstance(ent, dict):
        return None
    checked = int(ent.get("checked_at_unix") or 0)
    if checked and (time.time() - checked) > max_age_days * 86400:
        return None
    b = ent.get("bytes")
    d = ent.get("duration_sec")
    return MediaMeta(bytes=int(b) if isinstance(b, int) and b > 0 else None, duration_sec=int(d) if isinstance(d, int) and d > 0 else None)


def put_cached_meta(doc: dict[str, Any], url: str, meta: MediaMeta) -> None:
    doc.setdefault("by_url", {})
    by = doc["by_url"]
    if not isinstance(by, dict):
        doc["by_url"] = {}
        by = doc["by_url"]
    by[url] = {
        "checked_at_unix": int(time.time()),
        "bytes": int(meta.bytes) if (isinstance(meta.bytes, int) and meta.bytes > 0) else None,
        "duration_sec": int(meta.duration_sec) if (isinstance(meta.duration_sec, int) and meta.duration_sec > 0) else None,
    }

