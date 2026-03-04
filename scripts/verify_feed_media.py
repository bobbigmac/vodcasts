from __future__ import annotations

"""
Dev-only helper: verify that a feed's enclosure URLs actually serve playable media.

This is intentionally *not* used by the build (it may hit many media URLs and can be slow).
It samples a few enclosure URLs per feed, downloads a small byte-range to confirm bytes exist,
and writes `- disabled: <reason>` into the feeds markdown for failures.
"""

import argparse
import json
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from scripts.feed_manifest import parse_feed_for_manifest
from scripts.feeds_md import parse_feeds_markdown
from scripts.shared import fetch_url


VODCASTS_ROOT = Path(__file__).resolve().parents[1]


def _now() -> float:
    return time.time()


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _day_stamp() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _domain(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower()
    except Exception:
        return ""


class DomainThrottle:
    def __init__(self, min_delay_seconds: float):
        self._min_delay = float(min_delay_seconds)
        self._next_at: dict[str, float] = {}
        self._lock = None

        try:
            import threading

            self._lock = threading.Lock()
        except Exception:
            self._lock = None

    def wait(self, url: str) -> None:
        dom = _domain(url)
        if not dom or self._min_delay <= 0:
            return
        if self._lock is None:
            return
        with self._lock:
            t = _now()
            nxt = self._next_at.get(dom, 0.0)
            if t < nxt:
                time.sleep(max(0.0, nxt - t))
            self._next_at[dom] = _now() + self._min_delay


@dataclass(frozen=True)
class FeedDef:
    file: Path
    slug: str
    url: str
    user_agent: str
    timeout_seconds: int
    disabled: str | None


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    reason: str
    sample_url: str | None = None


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_json(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cache_key(feed: FeedDef) -> str:
    return f"{feed.slug}::{feed.url.strip()}"


def is_recent(cache_doc: dict[str, Any], key: str, *, max_age_seconds: int) -> bool:
    ent = (cache_doc.get("by_feed") or {}).get(key)
    if not isinstance(ent, dict):
        return False
    checked = ent.get("checked_at_unix")
    try:
        checked = int(checked)
    except Exception:
        checked = 0
    return bool(checked and (_now() - checked) < max_age_seconds)


def mark_checked(cache_doc: dict[str, Any], key: str, res: ProbeResult) -> None:
    cache_doc.setdefault("by_feed", {})
    by = cache_doc["by_feed"]
    if not isinstance(by, dict):
        cache_doc["by_feed"] = {}
        by = cache_doc["by_feed"]
    by[key] = {
        "checked_at_unix": int(_now()),
        "ok": bool(res.ok),
        "reason": str(res.reason),
        "sample_url": res.sample_url,
    }


def looks_supported_media_url(url: str, typ: str) -> bool:
    u = (url or "").lower()
    t = (typ or "").lower()
    if not u:
        return False
    if t.startswith("video/") or t.startswith("audio/"):
        return True
    if "mpegurl" in t or u.endswith(".m3u8") or ".m3u8?" in u:
        return True
    if re.search(r"\.(mp4|m4v|mov|webm)(\?|$)", u):
        return True
    if re.search(r"\.(mp3|m4a|aac|ogg|opus|wav)(\?|$)", u):
        return True
    return False


def _curl_headers(
    url: str,
    *,
    user_agent: str,
    timeout_seconds: int,
    use_head: bool,
    limit_rate_kbps: int = 0,
) -> tuple[int | None, str | None, str | None, str | None]:
    """
    Return (status, content_type, content_length, effective_url)
    """
    args = [
        "curl",
        "-sS",
        "-L",
        "--max-time",
        str(int(timeout_seconds)),
        "--connect-timeout",
        str(min(10, int(timeout_seconds))),
        "-A",
        user_agent,
        "-o",
        "/dev/null",
        "-D",
        "-",
        "-w",
        "%{http_code}\n%{content_type}\n%{size_download}\n%{url_effective}\n",
    ]
    if limit_rate_kbps and int(limit_rate_kbps) > 0:
        args += ["--limit-rate", f"{int(limit_rate_kbps)}k"]
    if use_head:
        args.append("-I")
    else:
        # Range GET to avoid full downloads; many hosts don't support HEAD reliably.
        args += ["-r", "0-1023"]
    args.append(url)

    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode != 0:
        return None, None, None, None

    out_lines = (p.stdout or "").splitlines()
    if len(out_lines) < 4:
        return None, None, None, None
    try:
        status = int(out_lines[-4].strip() or "0")
    except Exception:
        status = None
    content_type = out_lines[-3].strip() or None
    size_dl = out_lines[-2].strip() or None
    eff = out_lines[-1].strip() or None

    clen = None
    # Parse headers to find Content-Length (best-effort).
    try:
        for line in out_lines[:-4]:
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            if k.strip().lower() == "content-length":
                clen = v.strip()
    except Exception:
        pass

    return status, content_type, clen or size_dl, eff


def _curl_range_head_bytes(
    url: str, *, user_agent: str, timeout_seconds: int, nbytes: int = 1024, limit_rate_kbps: int = 0
) -> bytes | None:
    try:
        args = [
            "curl",
            "-sS",
            "-L",
            "--max-time",
            str(int(timeout_seconds)),
            "--connect-timeout",
            str(min(10, int(timeout_seconds))),
            "-A",
            user_agent,
        ]
        if limit_rate_kbps and int(limit_rate_kbps) > 0:
            args += ["--limit-rate", f"{int(limit_rate_kbps)}k"]
        args += ["-r", f"0-{max(0, int(nbytes) - 1)}", url]
        p = subprocess.run(args, capture_output=True)
        if p.returncode != 0:
            return None
        return p.stdout or b""
    except Exception:
        return None


def probe_media_url(
    url: str,
    *,
    user_agent: str,
    timeout_seconds: int,
    throttle: DomainThrottle,
    probe_bytes: int,
    limit_rate_kbps: int,
) -> tuple[bool, str]:
    """
    Minimal probe: ensure we can get headers/body that look like playable audio/video (or HLS playlist).
    """
    if not url:
        return False, "empty media url"

    throttle.wait(url)
    # Try HEAD first, then a tiny range GET.
    #
    # Some hosts respond to HEAD with misleading content-types (e.g. text/plain),
    # even though a GET returns real media. Treat non-media HEAD content-types as
    # "unknown" and fall back to a range GET before rejecting.
    status, ctype, _clen, _eff = _curl_headers(
        url,
        user_agent=user_agent,
        timeout_seconds=timeout_seconds,
        use_head=True,
        limit_rate_kbps=int(limit_rate_kbps),
    )
    need_range = False
    ct0 = (ctype or "").lower()
    if status is None or status < 200 or status >= 400:
        need_range = True
    elif ct0.startswith("text/html") or ct0.startswith("application/xhtml"):
        return False, f"unexpected content-type {ctype or 'text/html'}"
    elif ct0:
        # Accept obvious media-ish HEAD results; otherwise re-check via GET.
        if not (
            ct0.startswith("audio/")
            or ct0.startswith("video/")
            or "mpegurl" in ct0
            or ct0 in ("application/mp4", "application/x-mp4", "application/x-m4v", "application/x-m4a")
            or ct0 in ("application/octet-stream", "binary/octet-stream")
        ):
            need_range = True

    if need_range:
        throttle.wait(url)
        status, ctype, _clen, _eff = _curl_headers(
            url,
            user_agent=user_agent,
            timeout_seconds=timeout_seconds,
            use_head=False,
            limit_rate_kbps=int(limit_rate_kbps),
        )

    if status is None:
        return False, "curl failed"
    if status < 200 or status >= 400:
        return False, f"http {status}"

    ct = (ctype or "").lower()
    if ct.startswith("text/html") or ct.startswith("application/xhtml"):
        return False, f"unexpected content-type {ctype or 'text/html'}"

    # HLS: accept playlist-ish content-types too.
    if "mpegurl" in ct or url.lower().endswith(".m3u8") or ".m3u8?" in url.lower():
        throttle.wait(url)
        try:
            args = [
                "curl",
                "-sS",
                "-L",
                "--max-time",
                str(int(timeout_seconds)),
                "--connect-timeout",
                str(min(10, int(timeout_seconds))),
                "-A",
                user_agent,
            ]
            if limit_rate_kbps and int(limit_rate_kbps) > 0:
                args += ["--limit-rate", f"{int(limit_rate_kbps)}k"]
            p = subprocess.run(
                [*args, "--range", "0-65535", url],
                capture_output=True,
            )
            if p.returncode != 0:
                return False, "hls fetch failed"
            body = (p.stdout or b"")[:65535]
            if b"#EXTM3U" not in body[:2048]:
                return False, "not an m3u8 playlist"
            return True, "ok"
        except Exception:
            return False, "hls fetch failed"

    # For non-HLS, content-type should indicate media (or be generic).
    if not (
        ct.startswith("audio/")
        or ct.startswith("video/")
        or ct in ("application/mp4", "application/x-mp4", "application/x-m4v", "application/x-m4a")
        or ct in ("application/octet-stream", "binary/octet-stream", "")
    ):
        return False, f"unexpected content-type {ctype or '(none)'}"

    # Confirm we can actually download some bytes (without trusting HEAD).
    n = int(max(256, min(64 * 1024, int(probe_bytes) if int(probe_bytes) > 0 else 4096)))
    throttle.wait(url)
    blob = _curl_range_head_bytes(
        url,
        user_agent=user_agent,
        timeout_seconds=timeout_seconds,
        nbytes=n,
        limit_rate_kbps=int(limit_rate_kbps),
    )
    if not blob:
        return False, "no bytes"
    head = blob[:512].lstrip().lower()
    if head.startswith(b"<!doctype html") or head.startswith(b"<html"):
        return False, "html body"
    return True, "ok"


def load_feed_xml(feed: FeedDef, *, cache_dir: Path | None, throttle: DomainThrottle) -> tuple[str | None, str]:
    """
    Return (xml_text, reason). Uses cached XML when present; otherwise fetches the feed URL.
    """
    if cache_dir:
        p = cache_dir / "feeds" / f"{feed.slug}.xml"
        if p.exists() and p.stat().st_size > 200:
            try:
                return p.read_text(encoding="utf-8", errors="replace"), "cache"
            except Exception:
                pass

    throttle.wait(feed.url)
    try:
        r = fetch_url(feed.url, timeout_seconds=feed.timeout_seconds, user_agent=feed.user_agent)
    except Exception as e:
        return None, f"feed fetch failed: {_norm_ws(str(e))}"
    if r.status != 200 or not r.content:
        return None, f"feed http {r.status}"
    try:
        return r.content.decode("utf-8", errors="replace"), "fetched"
    except Exception:
        return None, "feed decode failed"


def probe_feed(
    feed: FeedDef,
    *,
    cache_dir: Path | None,
    throttle: DomainThrottle,
    media_timeout_seconds: int,
    sample_episodes: int,
    probe_bytes: int,
    limit_rate_kbps: int,
) -> ProbeResult:
    xml_text, how = load_feed_xml(feed, cache_dir=cache_dir, throttle=throttle)
    if not xml_text:
        return ProbeResult(ok=False, reason=f"media_probe: {how}")

    try:
        _features, _channel_title, episodes, _img = parse_feed_for_manifest(xml_text, source_id=feed.slug, source_title=feed.slug)
    except Exception:
        episodes = []

    media_eps = []
    for ep in episodes or []:
        media = ep.get("media") if isinstance(ep, dict) else None
        if not isinstance(media, dict):
            continue
        url = str(media.get("url") or "").strip()
        typ = str(media.get("type") or "").strip()
        if not url:
            continue
        # Don't filter too early: some feeds use signed URLs w/out extensions, but return usable content-types.
        media_eps.append((url, typ))

    if not media_eps:
        return ProbeResult(ok=False, reason=f"media_probe: no enclosures found in feed ({how})")

    # Sample a few distinct URLs.
    seen = set()
    samples = []
    for url, typ in media_eps:
        if url in seen:
            continue
        seen.add(url)
        samples.append((url, typ))
        if len(samples) >= max(1, int(sample_episodes)):
            break

    for url, typ in samples:
        ok, msg = probe_media_url(
            url,
            user_agent=feed.user_agent,
            timeout_seconds=media_timeout_seconds,
            throttle=throttle,
            probe_bytes=int(probe_bytes),
            limit_rate_kbps=int(limit_rate_kbps),
        )
        if ok:
            return ProbeResult(ok=True, reason="ok", sample_url=url)

    return ProbeResult(ok=False, reason=f"media_probe: enclosure probe failed ({len(samples)} sampled) ({how})")


def set_disabled_in_md(md_text: str, *, slug: str, disabled_reason: str) -> str:
    lines = md_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    # Locate the Feeds section.
    feeds_start = None
    for i, line in enumerate(lines):
        if re.match(r"^\s*#\s+feeds\b", line, flags=re.IGNORECASE):
            feeds_start = i
            break
    if feeds_start is None:
        return md_text

    # Find feed block.
    start = None
    for i in range(feeds_start, len(lines)):
        if re.match(rf"^\s*##\s+{re.escape(slug)}\s*$", lines[i]):
            start = i
            break
    if start is None:
        return md_text

    end = len(lines)
    for i in range(start + 1, len(lines)):
        if re.match(r"^\s*##\s+", lines[i]) or re.match(r"^\s*#\s+", lines[i]):
            end = i
            break

    # Update existing disabled line if present.
    for i in range(start + 1, end):
        if re.match(r"^\s*-\s*disabled\s*:\s*", lines[i], flags=re.IGNORECASE):
            lines[i] = f"- disabled: {disabled_reason}"
            return "\n".join(lines) + "\n"

    # Insert after url line if present, else after heading.
    insert_at = start + 1
    for i in range(start + 1, end):
        if re.match(r"^\s*-\s*url\s*:\s*", lines[i], flags=re.IGNORECASE):
            insert_at = i + 1
            break
    lines.insert(insert_at, f"- disabled: {disabled_reason}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Dev-only: verify feed enclosures actually serve playable media, then mark failing feeds as disabled.")
    ap.add_argument("--feeds", nargs="+", required=True, help="Feed markdown file(s), e.g. feeds/tech.md")
    ap.add_argument("--with-includes", action="store_true", help="Also load and test feeds from defaults.include files")
    ap.add_argument("--cache", default=None, help="Cache dir (expects <cache>/feeds/<slug>.xml). Default: cache/<feeds-stem>")
    ap.add_argument("--media-cache", default="cache/media-validate.json", help="Where to store probe results (24h skip)")
    ap.add_argument("--max-age-hours", type=int, default=24, help="Skip retesting feeds checked within this window")
    ap.add_argument("--max-workers", type=int, default=10, help="Concurrent feed probes")
    ap.add_argument("--domain-delay-sec", type=float, default=1.4, help="Min delay between requests to the same domain")
    ap.add_argument("--media-timeout-sec", type=int, default=20, help="Per-media request timeout")
    ap.add_argument(
        "--probe-bytes",
        type=int,
        default=4096,
        help="How many bytes to download from a media URL to confirm it serves real media (bounded range)",
    )
    ap.add_argument(
        "--limit-rate-kbps",
        type=int,
        default=300,
        help="Rate limit for media probes (helps prevent huge accidental downloads if a server ignores Range)",
    )
    ap.add_argument("--sample-episodes", type=int, default=3, help="How many enclosure URLs to sample per feed")
    ap.add_argument("--max-feeds", type=int, default=0, help="Limit probes to N feeds (0 = no limit)")
    ap.add_argument("--write", action="store_true", help="Write disabled reasons into feeds markdown")
    ap.add_argument("--report", default="tmp/media_validate_report.md", help="Write a markdown report here")
    args = ap.parse_args()

    feed_files = [Path(p).resolve() for p in args.feeds]
    for p in feed_files:
        if not p.exists():
            raise SystemExit(f"Missing feeds file: {p}")

    feeds_dir = VODCASTS_ROOT / "feeds"
    cfgs: dict[Path, dict[str, Any]] = {}
    all_files: set[Path] = set()
    for p in feed_files:
        txt = p.read_text(encoding="utf-8", errors="replace")
        cfg = parse_feeds_markdown(txt)
        cfgs[p] = cfg
        all_files.add(p)

    if args.with_includes:
        # Resolve includes recursively (within feeds/ only).
        pending = list(all_files)
        while pending:
            p = pending.pop()
            defaults = cfgs[p].get("defaults") if isinstance(cfgs[p].get("defaults"), dict) else {}
            inc = defaults.get("include")
            incs = []
            if isinstance(inc, str):
                incs = [inc]
            elif isinstance(inc, list):
                incs = [str(x) for x in inc if str(x).strip()]
            for name in incs:
                pn = (feeds_dir / Path(name).name).resolve()
                if pn.exists() and pn not in all_files:
                    txt = pn.read_text(encoding="utf-8", errors="replace")
                    cfgs[pn] = parse_feeds_markdown(txt)
                    all_files.add(pn)
                    pending.append(pn)

    # Build feed defs.
    feed_defs: list[FeedDef] = []
    for p in sorted(all_files, key=lambda x: x.name):
        cfg = cfgs[p]
        defaults = cfg.get("defaults") if isinstance(cfg.get("defaults"), dict) else {}
        ua = str(defaults.get("user_agent") or "actual-plays/vodcasts (+https://github.com/)").strip() or "actual-plays/vodcasts (+https://github.com/)"
        timeout = int(defaults.get("request_timeout_seconds") or 25)
        for f in cfg.get("feeds") or []:
            if not isinstance(f, dict):
                continue
            slug = str(f.get("slug") or "").strip()
            url = str(f.get("url") or "").strip()
            disabled = f.get("disabled")
            disabled_s = str(disabled).strip() if disabled not in (None, False, "") else None
            if not slug or not url:
                continue
            feed_defs.append(FeedDef(file=p, slug=slug, url=url, user_agent=ua, timeout_seconds=timeout, disabled=disabled_s))

    cache_doc = load_json(Path(args.media_cache))
    cache_doc.setdefault("version", 1)
    cache_doc.setdefault("by_feed", {})

    throttle = DomainThrottle(min_delay_seconds=float(args.domain_delay_sec))

    # Decide which feeds to test (skip disabled + recently checked).
    candidates: list[FeedDef] = []
    max_age_sec = int(max(0, int(args.max_age_hours)) * 3600)
    for fd in feed_defs:
        if fd.disabled:
            continue
        if max_age_sec > 0 and is_recent(cache_doc, cache_key(fd), max_age_seconds=max_age_sec):
            continue
        candidates.append(fd)

    if args.max_feeds and int(args.max_feeds) > 0:
        candidates = candidates[: int(args.max_feeds)]

    if not candidates:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text("# Media validation report\n\n- No feeds needed testing.\n", encoding="utf-8")
        return 0

    # Default cache dir for a single feed file run.
    cache_dir: Path | None
    if args.cache:
        cache_dir = Path(args.cache).resolve()
    else:
        # If exactly one root file was passed, assume cache/<stem>.
        if len(feed_files) == 1:
            stem = feed_files[0].stem
            cache_dir = (VODCASTS_ROOT / "cache" / stem).resolve()
        else:
            cache_dir = None
    if cache_dir and not cache_dir.exists():
        cache_dir = None

    print(f"[media] probing {len(candidates)} feeds (workers={args.max_workers}, domain_delay={args.domain_delay_sec:.1f}s)")

    results: dict[tuple[Path, str], ProbeResult] = {}
    with ThreadPoolExecutor(max_workers=max(1, int(args.max_workers))) as ex:
        futs = {}
        for fd in candidates:
            fut = ex.submit(
                probe_feed,
                fd,
                cache_dir=cache_dir,
                throttle=throttle,
                media_timeout_seconds=int(args.media_timeout_sec),
                sample_episodes=int(args.sample_episodes),
                probe_bytes=int(args.probe_bytes),
                limit_rate_kbps=int(args.limit_rate_kbps),
            )
            futs[fut] = fd
        for fut in as_completed(futs):
            fd = futs[fut]
            try:
                res = fut.result()
            except Exception as e:
                res = ProbeResult(ok=False, reason=f"media_probe: exception: {_norm_ws(str(e))}")
            results[(fd.file, fd.slug)] = res
            mark_checked(cache_doc, cache_key(fd), res)
            if res.ok:
                print(f"[media] ok  {fd.slug} ({fd.file.name})")
            else:
                print(f"[media] BAD {fd.slug} ({fd.file.name}) — {res.reason}")

    save_json(Path(args.media_cache), cache_doc)

    # Write report.
    bad = [(k, v) for k, v in results.items() if not v.ok]
    okc = len(results) - len(bad)
    lines = []
    lines.append("# Media validation report")
    lines.append("")
    lines.append(f"- checked: {len(results)}")
    lines.append(f"- ok: {okc}")
    lines.append(f"- bad: {len(bad)}")
    lines.append(f"- stamp: {_day_stamp()}")
    lines.append("")
    if bad:
        lines.append("## Disabled candidates")
        for (file, slug), res in sorted(bad, key=lambda x: (x[0][0].name, x[0][1])):
            lines.append(f"- {file.name}: `{slug}` — {res.reason}")
        lines.append("")
    else:
        lines.append("- No failures detected.")
        lines.append("")

    rep = Path(args.report)
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    if args.write and bad:
        # Group updates per file.
        per_file: dict[Path, list[tuple[str, str]]] = {}
        for (file, slug), res in bad:
            # Keep disabled reason short + stable.
            reason = f"{res.reason} (checked {_day_stamp()})"
            per_file.setdefault(file, []).append((slug, reason))

        for file, items in per_file.items():
            before = file.read_text(encoding="utf-8", errors="replace")
            after = before
            for slug, reason in items:
                after = set_disabled_in_md(after, slug=slug, disabled_reason=reason)
            if after != before:
                file.write_text(after, encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
