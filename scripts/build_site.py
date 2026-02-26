from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from scripts.feed_manifest import parse_feed_for_manifest
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
    p.add_argument("--fetch-missing-feeds", action="store_true", help="Fetch feeds missing from cache_dir/feeds/ during build.")
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
    return {
        "id": source.id,
        "title": source.title,
        "category": source.category,
        "feed_url": local_url if use_local else source.feed_url,
        "feed_url_remote": source.feed_url,
        "fetch_via": source.fetch_via,
        "has_cached_xml": bool(use_local),
        "features": features,
    }


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


def _episode_min_for_manifest(ep: dict[str, Any]) -> dict[str, Any]:
    media = ep.get("media") if isinstance(ep, dict) else None
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

    _log("load config…")
    cfg = load_sources_config(feeds_path)
    _log(f"  {len(cfg.sources)} sources ({time.perf_counter() - t0:.1f}s)")

    if args.fetch_missing_feeds:
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
    }
    write_json(out_dir / "site.json", site_json)

    # video-sources.json (client consumption).
    _log("build video-sources…")
    t = time.perf_counter()
    public_sources = [_source_to_public(s, cache_dir=cache_dir, base_path=base_path) for s in cfg.sources]
    write_json(out_dir / "video-sources.json", {"version": 1, "site": site_json, "sources": public_sources})
    _log(f"  done ({time.perf_counter() - t:.1f}s)")

    # feed-manifest.json: all feeds + episode list (client bootstrap; avoids per-feed fetches).
    _log("build feed-manifest…")
    t = time.perf_counter()
    manifest_feeds = []
    media_meta_doc = load_media_meta_cache(cache_dir) if args.enrich_media else {"version": 1, "updated_at_unix": 0, "by_url": {}}
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
    write_json(out_dir / "feed-manifest.json", {"version": 2, "base_path": base_path, "feeds": manifest_feeds})
    _log(f"  done ({time.perf_counter() - t:.1f}s)")
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
