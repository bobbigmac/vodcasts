from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from scripts.feed_meta import parse_feed_features_and_episodes
from scripts.shared import VODCASTS_ROOT, read_json, write_json
from scripts.sources import Source, load_sources_config


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build the static vodcasts site.")
    p.add_argument("--feeds", default=str(VODCASTS_ROOT / "feeds" / "dev.md"), help="Feeds config (.md or .json).")
    p.add_argument("--cache", default=str(VODCASTS_ROOT / "cache" / "dev"), help="Cache directory.")
    p.add_argument("--out", default=str(VODCASTS_ROOT / "dist"), help="Output directory.")
    p.add_argument("--base-path", default="/", help="Base path the site is hosted under (e.g. /vodcasts/).")
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
            f, _ = parse_feed_features_and_episodes(xml)
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


def main() -> None:
    t0 = time.perf_counter()
    args = _parse_args()
    feeds_path = Path(args.feeds)
    cache_dir = Path(args.cache)
    out_dir = Path(args.out)
    base_path = _norm_base_path(args.base_path)

    _log("load config…")
    cfg = load_sources_config(feeds_path)
    _log(f"  {len(cfg.sources)} sources ({time.perf_counter() - t0:.1f}s)")

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

    # feed-manifest.json: all feeds + brief episode list (populate channels without external fetches).
    _log("build feed-manifest…")
    t = time.perf_counter()
    feeds_cache_dir = cache_dir / "feeds"
    manifest_feeds = []
    for src in public_sources:
        cached = _load_cached_feed_path(cache_dir, src["id"])
        episodes_brief = []
        feats = src.get("features") or {}
        if cached.exists():
            try:
                xml = cached.read_text(encoding="utf-8", errors="replace")
                _, episodes = parse_feed_features_and_episodes(xml)
                episodes_brief = [{"id": e.id, "title": e.title, "date": e.date} for e in episodes[:200]]
            except Exception:
                pass
        manifest_feeds.append({
            "id": src["id"],
            "title": src["title"],
            "url": src.get("feed_url") or src.get("feed_url_remote", ""),
            "features": feats,
            "episodes": episodes_brief,
        })
    write_json(out_dir / "feed-manifest.json", {"version": 1, "base_path": base_path, "feeds": manifest_feeds})
    _log(f"  done ({time.perf_counter() - t:.1f}s)")

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
