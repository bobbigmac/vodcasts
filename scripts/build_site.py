from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from scripts.feed_manifest import parse_feed_for_manifest, short_description
from scripts.media_probe import (
    MediaMeta,
    get_cached_meta,
    head_content_length,
    hls_duration_seconds,
    load_media_meta_cache,
    mp4_duration_seconds,
    put_cached_meta,
    save_media_meta_cache,
)
from scripts.shared import VODCASTS_ROOT, fetch_url, read_feeds_config, read_json, write_json
from scripts.sources import Source, load_sources_config


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build the static vodcasts site.")
    p.add_argument("--feeds", default=str(VODCASTS_ROOT / "feeds" / "dev.md"), help="Feeds config (.md or .json).")
    p.add_argument("--cache", default=str(VODCASTS_ROOT / "cache" / "dev"), help="Cache directory.")
    p.add_argument("--out", default=str(VODCASTS_ROOT / "dist"), help="Output directory.")
    p.add_argument("--base-path", default="/", help="Base path the site is hosted under (e.g. /vodcasts/).")
    g = p.add_mutually_exclusive_group()
    g.add_argument(
        "--fetch-missing-feeds",
        dest="fetch_missing_feeds",
        action="store_true",
        help="Fetch feeds missing from cache_dir/feeds/ during build (default).",
    )
    g.add_argument(
        "--no-fetch-missing-feeds",
        dest="fetch_missing_feeds",
        action="store_false",
        help="Do not fetch missing feeds during build (may leave feeds empty in the guide due to CORS).",
    )
    p.set_defaults(fetch_missing_feeds=True)
    p.add_argument(
        "--enrich-media",
        action="store_true",
        help="Best-effort duration/bytes enrichment (HEAD + small range probes; never downloads full videos).",
    )
    p.add_argument(
        "--enrich-items-per-feed",
        type=int,
        default=25,
        help="Max episodes per feed to enrich when --enrich-media is enabled (default: 25).",
    )
    return p.parse_args()


def _norm_base_path(base_path: str) -> str:
    b = str(base_path or "/").strip() or "/"
    if not b.startswith("/"):
        b = "/" + b
    if not b.endswith("/"):
        b = b + "/"
    return b


def _template_sub(template: str, values: dict[str, str]) -> str:
    out = template
    for k, v in values.items():
        out = out.replace("{{" + k + "}}", v)
    return out


def _load_cached_feed_path(cache_dir: Path, source_id: str) -> Path:
    return cache_dir / "feeds" / f"{source_id}.xml"


def _source_to_public(source: Source, *, cache_dir: Path, base_path: str) -> dict[str, Any]:
    cached = _load_cached_feed_path(cache_dir, source.id)
    # Must be root-relative because the app uses client-side routing (e.g. /feed/episode/),
    # and relative URLs would otherwise resolve under that path.
    local_url = f"{base_path}data/feeds/{source.id}.xml"
    use_local = cached.exists()
    features = {}
    if use_local:
        try:
            xml = cached.read_text(encoding="utf-8", errors="replace")
            f, _, _ = parse_feed_for_manifest(xml, source_id=source.id, source_title=source.title)
            features = {
                "hasTranscript": f.has_transcript,
                "hasPlayableTranscript": f.has_playable_transcript,
                "hasChapters": f.has_chapters,
                "hasVideo": f.has_video,
            }
        except Exception:
            pass
    out: dict[str, Any] = {
        "id": source.id,
        "title": source.title,
        "category": source.category,
        "feed_url": local_url if use_local else source.feed_url,
        "feed_url_remote": source.feed_url,
        "has_cached_xml": bool(use_local),
        "features": features,
    }
    if source.tags:
        out["tags"] = list(source.tags)
    return out


def _log(msg: str) -> None:
    print(f"[build] {msg}", file=sys.stderr)


def _looks_like_feed_xml(text: str) -> bool:
    s = (text or "").lstrip().lower()
    if not s:
        return False
    # Common failure mode: HTML 200/404 pages cached as “XML”.
    if s.startswith("<!doctype html") or s.startswith("<html"):
        return False
    # Cheap RSS/Atom markers.
    if "<rss" in s or "<feed" in s or "<rdf:rdf" in s:
        return True
    if "<channel" in s and ("<item" in s or "<enclosure" in s):
        return True
    return False


def _read_defaults_from_feeds_md(feeds_path: Path) -> dict[str, Any]:
    if feeds_path.suffix.lower() != ".md":
        return {}
    try:
        cfg = read_feeds_config(feeds_path)
        d = cfg.get("defaults") or {}
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _read_ga_measurement_id_from_feeds_md(feeds_path: Path) -> str:
    if feeds_path.suffix.lower() != ".md":
        return ""
    try:
        cfg = read_feeds_config(feeds_path)
        site = cfg.get("site") if isinstance(cfg.get("site"), dict) else {}
        defaults = cfg.get("defaults") if isinstance(cfg.get("defaults"), dict) else {}
        v = site.get("ga_measurement_id") or defaults.get("ga_measurement_id") or ""
        return str(v or "").strip()
    except Exception:
        return ""


def _read_favicons_path_from_feeds_md(feeds_path: Path) -> str:
    if feeds_path.suffix.lower() != ".md":
        return ""
    try:
        cfg = read_feeds_config(feeds_path)
        site = cfg.get("site") if isinstance(cfg.get("site"), dict) else {}
        v = site.get("favicons_path") or site.get("favicon_path") or site.get("favicons") or ""
        return str(v or "").strip()
    except Exception:
        return ""


def _norm_rel_web_path(path: str) -> str:
    s = str(path or "").strip()
    if not s:
        return ""
    s = s.replace("\\", "/").strip()
    s = re.sub(r"/+", "/", s)
    return s.strip("/")


def _url_join(base_path: str, rel: str) -> str:
    r = _norm_rel_web_path(rel)
    if not r:
        return base_path
    return f"{base_path}{r}"


def _build_favicon_head_html(*, base_path: str, feeds_path: Path) -> str:
    favicons_path = _norm_rel_web_path(_read_favicons_path_from_feeds_md(feeds_path))

    lines: list[str] = []
    lines.append(f'<link rel="manifest" href="{base_path}manifest.webmanifest" />')

    if not favicons_path:
        # Legacy default (keeps existing deployments unchanged).
        lines.append(f'<link rel="icon" href="{base_path}assets/icon-192.png" />')
        lines.append(f'<link rel="apple-touch-icon" href="{base_path}assets/apple-touch-icon.png" />')
        return "\n  ".join(lines)

    # Prefer “favicon generator” style outputs when present.
    fs_dir = VODCASTS_ROOT / "site" / favicons_path
    url_dir = _url_join(base_path, favicons_path) + "/"

    if (fs_dir / "favicon.ico").exists():
        lines.append(f'<link rel="icon" href="{url_dir}favicon.ico" sizes="any" />')
        lines.append(f'<link rel="shortcut icon" href="{url_dir}favicon.ico" />')
    if (fs_dir / "favicon.svg").exists():
        lines.append(f'<link rel="icon" href="{url_dir}favicon.svg" type="image/svg+xml" />')
    if (fs_dir / "favicon-96x96.png").exists():
        lines.append(f'<link rel="icon" type="image/png" sizes="96x96" href="{url_dir}favicon-96x96.png" />')
    if (fs_dir / "apple-touch-icon.png").exists():
        lines.append(f'<link rel="apple-touch-icon" href="{url_dir}apple-touch-icon.png" />')

    # If the folder exists but we didn't recognize files, fall back to the legacy defaults.
    if len(lines) <= 1:
        lines.append(f'<link rel="icon" href="{base_path}assets/icon-192.png" />')
        lines.append(f'<link rel="apple-touch-icon" href="{base_path}assets/apple-touch-icon.png" />')

    return "\n  ".join(lines)


def _pwa_icons_for_manifest(*, base_path: str, feeds_path: Path) -> list[dict[str, str]]:
    favicons_path = _norm_rel_web_path(_read_favicons_path_from_feeds_md(feeds_path))
    if favicons_path:
        fs_dir = VODCASTS_ROOT / "site" / favicons_path
        url_dir = _url_join(base_path, favicons_path) + "/"
        p192 = fs_dir / "web-app-manifest-192x192.png"
        p512 = fs_dir / "web-app-manifest-512x512.png"
        if p192.exists() and p512.exists():
            return [
                {
                    "src": f"{url_dir}web-app-manifest-192x192.png",
                    "sizes": "192x192",
                    "type": "image/png",
                    "purpose": "any maskable",
                },
                {
                    "src": f"{url_dir}web-app-manifest-512x512.png",
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "any maskable",
                },
            ]

    return [
        {
            "src": f"{base_path}assets/icon-192.png",
            "sizes": "192x192",
            "type": "image/png",
            "purpose": "any maskable",
        },
        {
            "src": f"{base_path}assets/icon-512.png",
            "sizes": "512x512",
            "type": "image/png",
            "purpose": "any maskable",
        },
    ]


def _maybe_fetch_missing_feed(
    src: Source,
    *,
    cache_dir: Path,
    timeout_seconds: int,
    user_agent: str,
) -> bool:
    cached = _load_cached_feed_path(cache_dir, src.id)
    if cached.exists():
        return True
    try:
        res = fetch_url(src.feed_url, timeout_seconds=timeout_seconds, user_agent=user_agent)
        if res.status < 200 or res.status >= 300 or not res.content:
            return False
        text = res.content.decode("utf-8", errors="replace")
        if not _looks_like_feed_xml(text):
            return False
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(res.content)
        return True
    except Exception:
        return False


def _enrich_episode_media(
    ep: dict[str, Any],
    *,
    media_meta_doc: dict[str, Any],
    timeout_seconds: int,
    user_agent: str,
) -> dict[str, Any]:
    media = ep.get("media") if isinstance(ep, dict) else None
    if not isinstance(media, dict):
        return ep
    url = str(media.get("url") or "").strip()
    if not url:
        return ep

    cached = get_cached_meta(media_meta_doc, url)
    bytes0 = media.get("bytes") if isinstance(media.get("bytes"), int) and media.get("bytes") > 0 else None
    dur0 = ep.get("durationSec") if isinstance(ep.get("durationSec"), int) and ep.get("durationSec") > 0 else None

    out_bytes = bytes0 or (cached.bytes if cached else None)
    out_dur = dur0 or (cached.duration_sec if cached else None)

    changed = False
    if out_bytes is None:
        clen = head_content_length(url, timeout_seconds=timeout_seconds, user_agent=user_agent)
        if isinstance(clen, int) and clen > 0:
            out_bytes = clen
            changed = True

    if out_dur is None:
        d = hls_duration_seconds(url, timeout_seconds=timeout_seconds, user_agent=user_agent)
        if not d:
            d = mp4_duration_seconds(url, timeout_seconds=timeout_seconds, user_agent=user_agent)
        if isinstance(d, int) and d > 0:
            out_dur = d
            changed = True

    if changed:
        put_cached_meta(media_meta_doc, url, MediaMeta(bytes=out_bytes, duration_sec=out_dur))

    if out_bytes is not None:
        media["bytes"] = int(out_bytes)
    if out_dur is not None:
        ep["durationSec"] = int(out_dur)
    return ep


def _episode_min_for_manifest(ep: dict[str, Any], *, short_desc_chars: int = 150) -> dict[str, Any]:
    media = ep.get("media") if isinstance(ep, dict) else None
    desc_html = ep.get("descriptionHtml") or ""
    out = {
        "id": ep.get("id"),
        "slug": ep.get("slug"),
        "title": ep.get("title"),
        "link": ep.get("link") or "",
        "dateText": ep.get("dateText") or "",
        "channelTitle": ep.get("channelTitle") or "",
        "durationSec": ep.get("durationSec"),
        "media": media if isinstance(media, dict) else None,
        # Keep a small subset of enrichments the client can use without re-fetching feed XML.
        "chaptersExternal": ep.get("chaptersExternal"),
        "transcripts": ep.get("transcripts") or [],
        "transcriptsAll": ep.get("transcriptsAll") or [],
    }
    if desc_html:
        out["descriptionShort"] = short_description(desc_html, max_chars=short_desc_chars)
    return out


def main() -> None:
    t0 = time.perf_counter()
    args = _parse_args()
    feeds_path = Path(args.feeds)
    cache_dir = Path(args.cache)
    out_dir = Path(args.out)
    base_path = _norm_base_path(args.base_path)
    defaults = _read_defaults_from_feeds_md(feeds_path)
    timeout_seconds = int(defaults.get("request_timeout_seconds") or 25)
    user_agent = str(defaults.get("user_agent") or "actual-plays/vodcasts")
    enrich_items_per_feed = max(0, int(args.enrich_items_per_feed or 0))
    ga_measurement_id = (os.getenv("VOD_GA_MEASUREMENT_ID", "") or "").strip() or _read_ga_measurement_id_from_feeds_md(feeds_path)
    if ga_measurement_id and not re.fullmatch(r"G-[A-Z0-9]+", ga_measurement_id, flags=re.IGNORECASE):
        _log("warning: VOD_GA_MEASUREMENT_ID does not look like a GA4 measurement id (expected G-XXXX)")

    _log("load config…")
    cfg = load_sources_config(feeds_path)
    _log(f"  {len(cfg.sources)} sources ({time.perf_counter() - t0:.1f}s)")

    # Cache coverage diagnostics.
    wanted_ids = [s.id for s in cfg.sources]
    cache_feeds_dir = cache_dir / "feeds"
    cached_ids = {p.stem for p in cache_feeds_dir.glob("*.xml")} if cache_feeds_dir.exists() else set()
    missing_ids = [sid for sid in wanted_ids if sid not in cached_ids]
    extra_ids = sorted([sid for sid in cached_ids if sid not in set(wanted_ids)])
    if missing_ids:
        _log(f"warning: cache missing {len(missing_ids)}/{len(wanted_ids)} feeds ({cache_feeds_dir})")
        _log(f"  e.g. {', '.join(missing_ids[:6])}{'…' if len(missing_ids) > 6 else ''}")
    if extra_ids:
        _log(f"note: cache has {len(extra_ids)} extra feeds not in config (likely old slugs)")

    if args.fetch_missing_feeds and missing_ids:
        _log("fetch missing feeds (cache warm)…")
        t = time.perf_counter()
        had = 0
        fetched = 0
        for s in cfg.sources:
            cached = _load_cached_feed_path(cache_dir, s.id)
            if cached.exists():
                had += 1
                continue
            if _maybe_fetch_missing_feed(s, cache_dir=cache_dir, timeout_seconds=timeout_seconds, user_agent=user_agent):
                fetched += 1
        _log(f"  had {had}, fetched {fetched} ({time.perf_counter() - t:.1f}s)")
        cached_ids = {p.stem for p in cache_feeds_dir.glob("*.xml")} if cache_feeds_dir.exists() else set()
        still_missing = [sid for sid in wanted_ids if sid not in cached_ids]
        if still_missing:
            _log(f"warning: still missing {len(still_missing)}/{len(wanted_ids)} feeds after fetch")
            _log(f"  e.g. {', '.join(still_missing[:6])}{'…' if len(still_missing) > 6 else ''}")
    elif (not args.fetch_missing_feeds) and missing_ids:
        _log("hint: pass --fetch-missing-feeds (or run scripts.update_feeds) to avoid empty channels in the guide")

    supabase_url = os.getenv("VOD_SUPABASE_URL", "").strip()
    supabase_anon_key = os.getenv("VOD_SUPABASE_ANON_KEY", "").strip()
    hcaptcha_sitekey = os.getenv("VOD_HCAPTCHA_SITEKEY", "").strip()

    # Clean output.
    _log("clean output…")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Copy assets.
    _log("copy assets…")
    t = time.perf_counter()
    assets_src = VODCASTS_ROOT / "site" / "assets"
    assets_out = out_dir / "assets"
    shutil.copytree(assets_src, assets_out, dirs_exist_ok=True)
    _log(f"  done ({time.perf_counter() - t:.1f}s)")

    # Copy cached feeds (if any) so the client can fetch same-origin XML.
    feeds_cache_dir = cache_dir / "feeds"
    if feeds_cache_dir.exists():
        _log("copy cached feeds…")
        t = time.perf_counter()
        out_feeds_dir = out_dir / "data" / "feeds"
        shutil.copytree(feeds_cache_dir, out_feeds_dir, dirs_exist_ok=True)
        n = len(list(out_feeds_dir.glob("*.xml")))
        _log(f"  {n} feeds ({time.perf_counter() - t:.1f}s)")

    # site.json for the app env.
    site_json = {
        "id": cfg.site.id,
        "title": cfg.site.title,
        "subtitle": cfg.site.subtitle,
        "description": cfg.site.description,
        "base_path": base_path,
        "comments": {
            "provider": "supabase" if (supabase_url and supabase_anon_key) else "",
            "supabaseUrl": supabase_url,
            "supabaseAnonKey": supabase_anon_key,
            "hcaptchaSitekey": hcaptcha_sitekey,
        },
        "analytics": {
            "provider": "ga4" if ga_measurement_id else "",
            "measurementId": ga_measurement_id,
        },
    }
    write_json(out_dir / "site.json", site_json)

    # PWA: manifest + service worker.
    manifest = {
        "name": cfg.site.title,
        "short_name": cfg.site.title,
        "description": cfg.site.description or cfg.site.subtitle or "",
        "start_url": base_path,
        "scope": base_path,
        "display": "standalone",
        "background_color": "#0b0c10",
        "theme_color": "#0b0c10",
        "icons": _pwa_icons_for_manifest(base_path=base_path, feeds_path=feeds_path),
    }
    write_json(out_dir / "manifest.webmanifest", manifest)

    sw_src = VODCASTS_ROOT / "site" / "pwa" / "sw.js"
    if sw_src.exists():
        shutil.copy2(sw_src, out_dir / "sw.js")

    # video-sources.json (client consumption).
    _log("build video-sources…")
    t = time.perf_counter()
    public_sources = [_source_to_public(s, cache_dir=cache_dir, base_path=base_path) for s in cfg.sources]
    write_json(out_dir / "video-sources.json", {"version": 1, "site": site_json, "sources": public_sources})
    _log(f"  done ({time.perf_counter() - t:.1f}s)")

    # feed-manifest: chunked by date-window for cacheability; short descriptions; full text at display-time.
    _log("build feed-manifest…")
    t = time.perf_counter()
    MANIFEST_CHUNK_BYTES_CAP = 400_000  # ~400KB; split further if exceeded
    manifest_feeds = []
    media_meta_doc = load_media_meta_cache(cache_dir) if args.enrich_media else {"version": 1, "updated_at_unix": 0, "by_url": {}}
    from datetime import datetime
    now_year = datetime.now().year

    def _year_quarter_from_date_text(dt: str) -> tuple[int, int]:
        """(year, quarter 1-4). No date -> current year."""
        if not dt or not isinstance(dt, str):
            return now_year, 1
        try:
            y = int(dt[:4])
            if len(dt) >= 7:
                m = int(dt[5:7])
                q = (m - 1) // 3 + 1
                return y, q
            return y, 1
        except (ValueError, IndexError):
            return now_year, 1

    def _year_month_from_date_text(dt: str) -> tuple[int, int]:
        """(year, month 1-12). No date -> current year, month 1."""
        if not dt or not isinstance(dt, str):
            return now_year, 1
        try:
            y = int(dt[:4])
            m = int(dt[5:7]) if len(dt) >= 7 else 1
            return y, max(1, min(12, m))
        except (ValueError, IndexError):
            return now_year, 1

    for src in public_sources:
        cached = _load_cached_feed_path(cache_dir, src["id"])
        episodes = []
        feats = src.get("features") or {}
        if cached.exists():
            try:
                xml = cached.read_text(encoding="utf-8", errors="replace")
                f, _, eps = parse_feed_for_manifest(xml, source_id=src["id"], source_title=src.get("title") or src["id"])
                feats = {
                    "hasTranscript": f.has_transcript,
                    "hasPlayableTranscript": f.has_playable_transcript,
                    "hasChapters": f.has_chapters,
                    "hasVideo": f.has_video,
                }
                if args.enrich_media and enrich_items_per_feed > 0:
                    for ep in eps[:enrich_items_per_feed]:
                        _enrich_episode_media(ep, media_meta_doc=media_meta_doc, timeout_seconds=timeout_seconds, user_agent=user_agent)
                episodes = [_episode_min_for_manifest(ep) for ep in eps[:200]]
            except Exception:
                pass
        manifest_feeds.append({
            "id": src["id"],
            "title": src["title"],
            "url": src.get("feed_url") or src.get("feed_url_remote", ""),
            "features": feats,
            "episodes": episodes,
        })

    # Chunk by date-window (year, or year-quarter if over cap).
    def _chunk_key(y: int, q: int | None) -> str:
        return f"{y}-q{q}" if q else str(y)

    # Group episodes by feed id -> list of (ep, year, quarter, month)
    episodes_by_feed: dict[str, list[tuple[dict, int, int, int]]] = {}
    for mf in manifest_feeds:
        fid = mf["id"]
        eps = mf.get("episodes") or []
        episodes_by_feed[fid] = []
        for ep in eps:
            y, q = _year_quarter_from_date_text(ep.get("dateText") or "")
            ym, mm = _year_month_from_date_text(ep.get("dateText") or "")
            episodes_by_feed[fid].append((ep, y, q, mm))

    def _size_of_chunk(chunk_eps: dict[str, list[dict]]) -> int:
        c = {fid: eps for fid, eps in chunk_eps.items() if eps}
        s = json.dumps({"feeds": [{"id": fid, "episodes": eps} for fid, eps in c.items()]}, ensure_ascii=False, indent=2)
        return len((s + "\n").encode("utf-8"))

    def _emit_chunk(filename: str, chunk_eps: dict[str, list[dict]]) -> None:
        c = {fid: eps for fid, eps in chunk_eps.items() if eps}
        if c:
            write_json(out_dir / filename, {"feeds": [{"id": fid, "episodes": eps} for fid, eps in c.items()]})
            chunk_specs.append(filename)

    chunk_specs: list[str] = []
    years = sorted({y for lst in episodes_by_feed.values() for _, y, _, _ in lst}, reverse=True)
    if not years:
        years = [now_year]

    for y in years:
        # Try full year first
        chunk_eps = {fid: [ep for ep, ey, _, _ in lst if ey == y] for fid, lst in episodes_by_feed.items()}
        if _size_of_chunk(chunk_eps) <= MANIFEST_CHUNK_BYTES_CAP:
            _emit_chunk(f"feed-manifest-{y}.json", chunk_eps)
            continue
        # Split by quarter
        for q in range(1, 5):
            q_eps = {fid: [ep for ep, ey, eq, _ in lst if ey == y and eq == q] for fid, lst in episodes_by_feed.items()}
            if not any(q_eps.values()):
                continue
            if _size_of_chunk(q_eps) <= MANIFEST_CHUNK_BYTES_CAP:
                _emit_chunk(f"feed-manifest-{y}-q{q}.json", q_eps)
            else:
                # Split quarter by month
                for m in range(1, 13):
                    m1, m2 = (q - 1) * 3 + 1, q * 3
                    if not (m1 <= m <= m2):
                        continue
                    m_eps = {fid: [ep for ep, ey, eq, em in lst if ey == y and eq == q and em == m] for fid, lst in episodes_by_feed.items()}
                    if any(m_eps.values()):
                        _emit_chunk(f"feed-manifest-{y}-{m:02d}.json", m_eps)

    # Index: feed metadata (no episodes) + chunk list
    feed_meta = [{"id": mf["id"], "title": mf["title"], "url": mf.get("url") or "", "features": mf.get("features") or {}} for mf in manifest_feeds]
    chunks_list = [{"url": base_path + fn} for fn in chunk_specs]
    write_json(out_dir / "feed-manifest.json", {"version": 3, "base_path": base_path, "feeds": feed_meta, "chunks": chunks_list})
    _log(f"  done ({len(chunk_specs)} chunks, {time.perf_counter() - t:.1f}s)")
    if args.enrich_media:
        try:
            save_media_meta_cache(cache_dir, media_meta_doc)
        except Exception:
            pass

    # index.html
    template_path = VODCASTS_ROOT / "site" / "templates" / "index.html"
    template = template_path.read_text(encoding="utf-8", errors="replace")
    html = _template_sub(
        template,
        {
            "base_path": base_path,
            "base_path_json": json.dumps(base_path),
            "site_json": json.dumps(site_json, ensure_ascii=False),
            "page_title": cfg.site.title,
            "favicon_head_html": _build_favicon_head_html(base_path=base_path, feeds_path=feeds_path),
        },
    )
    (out_dir / "index.html").write_text(html, encoding="utf-8")

    # 404.html (GitHub Pages SPA redirect shim)
    template_404_path = VODCASTS_ROOT / "site" / "templates" / "404.html"
    if template_404_path.exists():
        template_404 = template_404_path.read_text(encoding="utf-8", errors="replace")
        html_404 = _template_sub(
            template_404,
            {
                "base_path": base_path,
                "base_path_json": json.dumps(base_path),
                "site_json": json.dumps(site_json, ensure_ascii=False),
                "page_title": cfg.site.title,
            },
        )
        (out_dir / "404.html").write_text(html_404, encoding="utf-8")

    _log(f"build complete ({time.perf_counter() - t0:.1f}s total)")

    # Copy placeholder old JSON config for convenience when diffing/porting.
    src_sources_json = VODCASTS_ROOT / "feeds" / "video-sources.json"
    if src_sources_json.exists():
        shutil.copy2(src_sources_json, out_dir / "video-sources.original.json")


if __name__ == "__main__":
    main()
