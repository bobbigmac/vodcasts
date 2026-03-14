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

from scripts.build_roku_search import build_roku_search, cleanup_roku_search_outputs
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
from scripts.show_filters import build_shows_for_feed


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build the static vodcasts site.")
    p.add_argument("--feeds", default=str(VODCASTS_ROOT / "feeds" / "dev.md"), help="Feeds config (.md or .json).")
    p.add_argument("--cache", default=str(VODCASTS_ROOT / "cache" / "dev"), help="Cache directory.")
    p.add_argument("--out", default=str(VODCASTS_ROOT / "dist"), help="Output directory.")
    p.add_argument("--base-path", default="/", help="Base path the site is hosted under (e.g. /vodcasts/).")
    clean_g = p.add_mutually_exclusive_group()
    clean_g.add_argument("--clean", dest="clean", action="store_true", help="Delete output dir before building (default).")
    clean_g.add_argument("--no-clean", dest="clean", action="store_false", help="Do not delete output dir before building.")
    p.set_defaults(clean=True)
    assets_g = p.add_mutually_exclusive_group()
    assets_g.add_argument("--copy-assets", dest="copy_assets", action="store_true", help="Copy site/assets into output (default).")
    assets_g.add_argument("--no-copy-assets", dest="copy_assets", action="store_false", help="Do not copy site/assets into output.")
    p.set_defaults(copy_assets=True)
    feeds_g = p.add_mutually_exclusive_group()
    feeds_g.add_argument("--copy-feeds", dest="copy_feeds", action="store_true", help="Copy cache_dir/feeds into output (default).")
    feeds_g.add_argument("--no-copy-feeds", dest="copy_feeds", action="store_false", help="Do not copy cache_dir/feeds into output.")
    p.set_defaults(copy_feeds=True)
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
    roku_g = p.add_mutually_exclusive_group()
    roku_g.add_argument(
        "--build-roku-search",
        dest="build_roku_search",
        action="store_true",
        help="Build a Roku search index under site assets (default).",
    )
    roku_g.add_argument(
        "--no-build-roku-search",
        dest="build_roku_search",
        action="store_false",
        help="Skip the Roku search index step.",
    )
    p.set_defaults(build_roku_search=True)
    p.add_argument(
        "--roku-search-limit-per-feed",
        type=int,
        default=0,
        help="Override per-feed episode cap for Roku search index (default: 50 locally, 100 in GitHub Actions).",
    )
    p.add_argument(
        "--roku-search-exclude-feeds",
        default="",
        help="Comma-separated feed ids to exclude from the Roku search index.",
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


def _escape_attr(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _escape_html(s: str) -> str:
    # For text nodes (quotes are fine but harmless to escape too).
    return _escape_attr(s)


def _build_meta_head_html(
    *,
    base_path: str,
    site_title: str,
    page_title: str,
    page_description: str,
    canonical_path: str,
    og_type: str = "website",
    og_image_path: str | None = None,
    site_origin: str = "",
) -> str:
    """
    Basic SEO/OpenGraph metadata for static pages.

    Facebook and Twitter require absolute URLs for og:image. When site_origin is
    provided (e.g. https://example.com), canonical and og:image use absolute URLs.
    """
    bp = _norm_base_path(base_path)
    canon = canonical_path if canonical_path.startswith("/") else bp + canonical_path.lstrip("/")
    og_image = og_image_path or (bp + "assets/icon-512.png")
    origin = (site_origin or "").strip().rstrip("/")
    if origin:
        canon = origin + canon if canon.startswith("/") else origin + "/" + canon.lstrip("/")
        img = og_image
        og_image = (origin + img) if img.startswith("/") else (origin + "/" + img.lstrip("/"))

    title = _escape_attr(page_title or site_title)
    desc = _escape_attr(page_description or "")
    site = _escape_attr(site_title or "")
    canon_e = _escape_attr(canon)
    og_image_e = _escape_attr(og_image)
    og_type_e = _escape_attr(og_type or "website")

    ld = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": site_title,
        "description": page_description,
        "inLanguage": "en",
    }
    ld_json = _escape_attr(json.dumps(ld, ensure_ascii=False))

    return "\n  ".join(
        [
            '<meta name="description" content="' + desc + '" />',
            '<meta name="robots" content="index,follow" />',
            '<meta name="referrer" content="strict-origin-when-cross-origin" />',
            '<link rel="canonical" href="' + canon_e + '" />',
            '<meta property="og:site_name" content="' + site + '" />',
            '<meta property="og:type" content="' + og_type_e + '" />',
            '<meta property="og:url" content="' + canon_e + '" />',
            '<meta property="og:title" content="' + title + '" />',
            '<meta property="og:description" content="' + desc + '" />',
            '<meta property="og:image" content="' + og_image_e + '" />',
            '<meta name="twitter:card" content="summary_large_image" />',
            '<meta name="twitter:title" content="' + title + '" />',
            '<meta name="twitter:description" content="' + desc + '" />',
            '<meta name="twitter:image" content="' + og_image_e + '" />',
            '<script type="application/ld+json">' + ld_json + "</script>",
        ]
    )


def _norm_site_origin(site_url: str) -> str:
    u = str(site_url or "").strip()
    if not u:
        return ""
    if not re.match(r"^https?://", u, flags=re.IGNORECASE):
        u = "https://" + u
    return u.rstrip("/")


def _sitemap_url_path_for_html(rel_html_path: Path, *, base_path: str) -> str:
    bp = _norm_base_path(base_path)
    rel = rel_html_path.as_posix()
    if rel == "index.html":
        return bp
    if rel.endswith("/index.html"):
        d = rel[: -len("/index.html")]
        return bp + d.strip("/") + "/"
    return bp + rel.lstrip("/")


def _build_sitemap_xml(url_entries: list[tuple[str, str | None]]) -> str:
    # url_entries: [(loc, lastmod_yyyy_mm_dd_or_none)]
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for loc, lastmod in url_entries:
        loc_e = _escape_attr(loc)
        if lastmod:
            lastmod_e = _escape_attr(lastmod)
            lines.append(f"  <url><loc>{loc_e}</loc><lastmod>{lastmod_e}</lastmod></url>")
        else:
            lines.append(f"  <url><loc>{loc_e}</loc></url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def _build_robots_txt(*, base_path: str, sitemap_loc: str | None) -> str:
    bp = _norm_base_path(base_path)
    lines = [
        "User-agent: *",
        f"Disallow: {bp}data/feeds/",
        # Show RSS feeds are XML and intended for humans/tools; keep them out of crawlers.
        # Wildcards are supported by major crawlers (Google/Bing).
        f"Disallow: {bp}feed/*/show/",
    ]
    if sitemap_loc:
        lines.append(f"Sitemap: {sitemap_loc}")
    return "\n".join(lines) + "\n"


def _load_cached_feed_path(cache_dir: Path, source_id: str) -> Path:
    return cache_dir / "feeds" / f"{source_id}.xml"


def _source_to_public(source: Source, *, cache_dir: Path, base_path: str) -> dict[str, Any]:
    cached = _load_cached_feed_path(cache_dir, source.id)
    # Must be root-relative because the app uses client-side routing (e.g. /feed/episode/),
    # and relative URLs would otherwise resolve under that path.
    local_url = f"{base_path}data/feeds/{source.id}.xml"
    use_local = cached.exists()
    # Note: features are populated during feed-manifest build (single parse pass).
    features: dict[str, Any] = {}
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


def _read_browse_logo_path_from_feeds_md(feeds_path: Path) -> str:
    if feeds_path.suffix.lower() != ".md":
        return ""
    try:
        cfg = read_feeds_config(feeds_path)
        site = cfg.get("site") if isinstance(cfg.get("site"), dict) else {}
        v = site.get("browse_logo_path") or site.get("browseLogoPath") or ""
        return str(v or "").strip()
    except Exception:
        return ""


def _read_og_image_path_from_feeds_md(feeds_path: Path) -> str:
    if feeds_path.suffix.lower() != ".md":
        return ""
    try:
        cfg = read_feeds_config(feeds_path)
        site = cfg.get("site") if isinstance(cfg.get("site"), dict) else {}
        v = (
            site.get("og_image_path")
            or site.get("opengraph_image_path")
            or site.get("open_graph_image_path")
            or site.get("ogImagePath")
            or ""
        )
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


def _seo_shell(*, title: str, body_html: str, base_path: str) -> str:
    # Render as a support-like page (only visible when JS is disabled / blocked).
    t = _escape_html(title)
    bp = _norm_base_path(base_path)
    return f"""
<main class="supportPage seoContent">
  <header class="supportHeader">
    <a class="supportBack" href="{bp}" aria-label="Back to home">← Home</a>
    <div class="supportBrand">{t}</div>
  </header>
  <article class="supportContent">
    {body_html}
  </article>
  <footer class="supportFooter">
    <nav class="supportFooterLinks" aria-label="Support">
      <a href="{bp}browse/">Browse</a>
      <a href="{bp}about/">About</a>
      <a href="{bp}for/">Who it’s for</a>
      <a href="{bp}privacy/">Privacy</a>
      <a href="{bp}legal/">Legal</a>
    </nav>
    <div class="supportFooterMeta">Contact: <a href="mailto:admin@prays.be">admin@prays.be</a></div>
  </footer>
</main>
""".strip()


def _seo_home_html(*, cfg_site_title: str, cfg_site_desc: str, base_path: str) -> str:
    bp = _norm_base_path(base_path)
    title = cfg_site_title or "Home"
    body = f"""
<h1><a href="{bp}" style="color:inherit;text-decoration:none">{_escape_html(cfg_site_title)}</a></h1>
<p>{_escape_html(cfg_site_desc)}</p>
<div class="supportCard">
  <h2>Browse</h2>
  <ul>
    <li><a href="{bp}browse/">Browse shows</a> (categories + feeds)</li>
  </ul>
</div>
""".strip()
    return _seo_shell(title=title, body_html=body, base_path=base_path)


def _seo_feed_html(
    *,
    feed_id: str,
    feed_title: str,
    show_configs: list[dict[str, Any]],
    base_path: str,
) -> str:
    bp = _norm_base_path(base_path)
    feed_title_e = _escape_html(feed_title or feed_id)
    feed_url = f"{bp}feed/{_escape_attr(feed_id)}/"
    items = []
    for s in show_configs or []:
        sid = str(s.get("id") or "")
        slug = str(s.get("slug") or "")
        stitle = str(s.get("title") or sid) or sid
        scount = int(s.get("episodeCount") or 0)
        sdesc = str(s.get("description") or "").strip()
        url = f"{bp}feed/{_escape_attr(feed_id)}/shows/{_escape_attr(slug)}/"
        line = f'<li><a href="{url}">{_escape_html(stitle)}</a> <span style="opacity:.75">({scount})</span>'
        if sdesc:
            line += f'<div style="opacity:.88;margin-top:2px">{_escape_html(sdesc)}</div>'
        line += "</li>"
        items.append(line)
    shows_ul = "<ul>" + "\n".join(items) + "</ul>" if items else "<p>Loading shows...</p>"
    body = f"""
<h1><a href="{feed_url}" style="color:inherit;text-decoration:none">{feed_title_e}</a></h1>
<p>Show rows for this feed (same as the in-app Browse view).</p>
<div class="supportCard">
  <h2>Shows</h2>
  {shows_ul}
</div>
""".strip()
    return _seo_shell(title=feed_title, body_html=body, base_path=base_path)


def _seo_show_html(
    *,
    feed_id: str,
    feed_title: str,
    show_title: str,
    show_slug: str,
    show_description: str | None,
    episodes: list[dict[str, Any]],
    base_path: str,
) -> str:
    bp = _norm_base_path(base_path)
    show_url = f"{bp}feed/{_escape_attr(feed_id)}/shows/{_escape_attr(show_slug)}/"
    feed_url = f"{bp}feed/{_escape_attr(feed_id)}/"

    ep_items = []
    for ep in (episodes or [])[:80]:
        ep_seg = ep.get("slug") or ep.get("id")
        if not ep_seg:
            continue
        ep_title = _escape_html(str(ep.get("title") or "Untitled"))
        date = _escape_html(str(ep.get("dateText") or ""))
        ep_url = f"{show_url}?ep={_escape_attr(str(ep_seg))}"
        meta = f' <span style="opacity:.7">{date}</span>' if date else ""
        ep_items.append(f'<li><a href="{ep_url}">{ep_title}</a>{meta}</li>')
    eps_ul = "<ul>" + "\n".join(ep_items) + "</ul>" if ep_items else "<p>No episodes found for this show.</p>"

    desc_html = f"<p>{_escape_html(show_description)}</p>" if show_description else ""
    body = f"""
<h1><a href="{show_url}" style="color:inherit;text-decoration:none">{_escape_html(show_title)}</a></h1>
<p>From <a href="{feed_url}">{_escape_html(feed_title or feed_id)}</a></p>
{desc_html}
<div class="supportCard">
  <h2>Episodes</h2>
  {eps_ul}
</div>
""".strip()
    return _seo_shell(title=show_title, body_html=body, base_path=base_path)


def _seo_browse_all_html(
    *,
    cfg_site_title: str,
    shows_config_all: dict[str, list[dict[str, Any]]],
    feed_titles: dict[str, str],
    base_path: str,
) -> str:
    bp = _norm_base_path(base_path)
    blocks = []
    for fid, shows in sorted((shows_config_all or {}).items(), key=lambda kv: (feed_titles.get(kv[0], kv[0]).lower(), kv[0])):
        ft = feed_titles.get(fid) or fid
        feed_url = f"{bp}feed/{_escape_attr(fid)}/"
        items = []
        for s in shows or []:
            slug = str(s.get("slug") or "")
            title = str(s.get("title") or s.get("id") or slug) or slug
            count = int(s.get("episodeCount") or 0)
            url = f"{bp}feed/{_escape_attr(fid)}/shows/{_escape_attr(slug)}/"
            items.append(f'<li><a href="{url}">{_escape_html(title)}</a> <span style="opacity:.7">({count})</span></li>')
        ul = "<ul>" + "\n".join(items[:80]) + "</ul>" if items else "<p>No shows.</p>"
        blocks.append(
            f"""
<div class="supportCard">
  <h2><a href="{feed_url}" style="color:inherit;text-decoration:none">{_escape_html(ft)}</a></h2>
  {ul}
</div>
""".strip()
        )
    body = f"""
<h1><a href="{bp}browse/" style="color:inherit;text-decoration:none">Browse Shows</a></h1>
<p>{_escape_html(cfg_site_title)} — show rows grouped by feed (static HTML for crawlers; the app view is richer with JavaScript enabled).</p>
{''.join(blocks)}
""".strip()
    return _seo_shell(title="Browse Shows", body_html=body, base_path=base_path)


def _browse_logo_url_for_site(*, base_path: str, feeds_path: Path) -> str:
    """Optional UI logo (e.g. for the Browse button). Distinct from favicons."""
    # Prefer explicit config, but fall back to favicon.svg when present.
    explicit = _norm_rel_web_path(_read_browse_logo_path_from_feeds_md(feeds_path))
    if explicit:
        fs = VODCASTS_ROOT / "site" / explicit
        if fs.exists():
            return _url_join(base_path, explicit)

    favicons_path = _norm_rel_web_path(_read_favicons_path_from_feeds_md(feeds_path))
    if favicons_path:
        fs_dir = VODCASTS_ROOT / "site" / favicons_path
        if (fs_dir / "favicon.svg").exists():
            return _url_join(base_path, favicons_path) + "/favicon.svg"

    return ""


def _og_image_url_for_site(*, base_path: str, feeds_path: Path) -> str:
    """
    Optional OpenGraph promo image. Distinct from favicons.

    Should be a path relative to the `site/` folder (e.g. assets/images/og-promo.jpg).
    """
    explicit = _norm_rel_web_path(_read_og_image_path_from_feeds_md(feeds_path))
    if not explicit:
        return ""
    fs = VODCASTS_ROOT / "site" / explicit
    if not fs.exists():
        return ""
    return _url_join(base_path, explicit)


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
        "imageUrl": ep.get("imageUrl") or None,
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
    if args.clean:
        _log("clean output…")
        if out_dir.exists():
            shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Copy assets.
    if args.copy_assets:
        _log("copy assets…")
        t = time.perf_counter()
        assets_src = VODCASTS_ROOT / "site" / "assets"
        assets_out = out_dir / "assets"
        shutil.copytree(assets_src, assets_out, dirs_exist_ok=True)
        _log(f"  done ({time.perf_counter() - t:.1f}s)")

    # Copy cached feeds (if any) so the client can fetch same-origin XML.
    feeds_cache_dir = cache_dir / "feeds"
    if args.copy_feeds and feeds_cache_dir.exists():
        _log("copy cached feeds…")
        t = time.perf_counter()
        out_feeds_dir = out_dir / "data" / "feeds"
        shutil.copytree(feeds_cache_dir, out_feeds_dir, dirs_exist_ok=True)
        n = len(list(out_feeds_dir.glob("*.xml")))
        _log(f"  {n} feeds ({time.perf_counter() - t:.1f}s)")

    # site.json for the app env.
    og_image_url = _og_image_url_for_site(base_path=base_path, feeds_path=feeds_path) or None
    site_origin = _norm_site_origin(cfg.site.url or os.environ.get("VOD_SITE_URL") or "")
    site_json = {
        "id": cfg.site.id,
        "title": cfg.site.title,
        "subtitle": cfg.site.subtitle,
        "description": cfg.site.description,
        "base_path": base_path,
        "url": cfg.site.url,
        "browseLogoUrl": _browse_logo_url_for_site(base_path=base_path, feeds_path=feeds_path),
        "ogImageUrl": og_image_url or "",
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

    public_sources = [_source_to_public(s, cache_dir=cache_dir, base_path=base_path) for s in cfg.sources]

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
        channel_image_url = None
        if cached.exists():
            try:
                xml = cached.read_text(encoding="utf-8", errors="replace")
                f, _, eps, channel_image_url = parse_feed_for_manifest(xml, source_id=src["id"], source_title=src.get("title") or src["id"])
                feats = {
                    "hasTranscript": f.has_transcript,
                    "hasPlayableTranscript": f.has_playable_transcript,
                    "hasChapters": f.has_chapters,
                    "hasVideo": f.has_video,
                }
                src["features"] = feats
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
            "channelImageUrl": channel_image_url,
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

    # newest.xml — blog-style RSS of 50 most recent episodes; links to site (no source enclosures).
    NEWEST_RSS_LIMIT = 50
    NEWEST_RSS_EXCLUDE_FEEDS: tuple[str, ...] = ()  # Add slugs to exclude from curated newest feed.
    _log("build newest.xml…")
    t_newest = time.perf_counter()
    site_url = (cfg.site.url or os.environ.get("VOD_SITE_URL") or "").strip().rstrip("/")
    if not site_url:
        _log("  skip: no site url (set site.url in feeds or VOD_SITE_URL)")
    else:
        all_eps: list[tuple[dict[str, Any], str, str]] = []
        for mf in manifest_feeds:
            fid = mf["id"]
            if fid in NEWEST_RSS_EXCLUDE_FEEDS:
                continue
            feed_title = mf.get("title") or fid
            for ep in mf.get("episodes") or []:
                ep_slug = ep.get("slug") or ep.get("id")
                if not ep_slug:
                    continue
                all_eps.append((ep, fid, feed_title))
        all_eps.sort(key=lambda x: (x[0].get("dateText") or ""), reverse=True)
        newest_eps = all_eps[:NEWEST_RSS_LIMIT]

        def _date_to_rfc2822(dt: str) -> str:
            if not dt or len(dt) < 10:
                return ""
            try:
                from datetime import datetime

                parsed = datetime.strptime(dt[:10], "%Y-%m-%d")
                return parsed.strftime("%a, %d %b %Y 00:00:00 +0000")
            except Exception:
                return dt

        def _escape_xml_newest(s: str) -> str:
            return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

        items_xml = []
        for ep, fid, feed_title in newest_eps:
            ep_slug = ep.get("slug") or ep.get("id")
            link_path = f"{base_path}feed/{fid}/{ep_slug}/"
            link_url = f"{site_url}{link_path}" if site_url.startswith("http") else f"https://{site_url}{link_path}"
            title = _escape_xml_newest(str(ep.get("title") or "Untitled"))
            desc = _escape_xml_newest(str(ep.get("descriptionShort") or "")[:500])
            pub_date = _date_to_rfc2822(str(ep.get("dateText") or ""))
            guid = _escape_xml_newest(f"{fid}/{ep_slug}")
            items_xml.append(f"""  <item>
    <title>{title}</title>
    <link>{link_url}</link>
    <description>{desc}</description>
    <pubDate>{pub_date}</pubDate>
    <guid isPermaLink="true">{link_url}</guid>
  </item>""")

        channel_title = _escape_xml_newest(cfg.site.title or "VODcasts")
        channel_desc = _escape_xml_newest(cfg.site.description or "Latest video episodes")
        channel_link = f"{site_url}{base_path}" if site_url.startswith("http") else f"https://{site_url}{base_path}"
        rss_body = "\n".join(items_xml)
        newest_rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>{channel_title} — Newest</title>
    <link>{channel_link}</link>
    <description>{channel_desc}</description>
    <language>en</language>
{rss_body}
  </channel>
</rss>
"""
        (out_dir / "newest.xml").write_text(newest_rss, encoding="utf-8")
        _log(f"  done ({len(newest_eps)} items, {time.perf_counter() - t_newest:.1f}s)")

    # video-sources.json (client consumption). Fill features from manifest parse (single pass).
    _log("build video-sources…")
    t = time.perf_counter()
    write_json(out_dir / "video-sources.json", {"version": 1, "site": site_json, "sources": public_sources})
    _log(f"  done ({time.perf_counter() - t:.1f}s)")

    template_path = VODCASTS_ROOT / "site" / "templates" / "index.html"
    template = template_path.read_text(encoding="utf-8", errors="replace")
    support_template_path = VODCASTS_ROOT / "site" / "templates" / "support.html"
    support_template = support_template_path.read_text(encoding="utf-8", errors="replace") if support_template_path.exists() else ""
    vodcasts_config = {"basePath": base_path, "site": site_json}

    # Shows + feed landing pages + show RSS feeds
    _log("build shows + feed landings…")
    t = time.perf_counter()
    raw_cfg = read_feeds_config(feeds_path)
    raw_feeds_by_slug = {str(f.get("slug") or "").strip(): f for f in (raw_cfg.get("feeds") or []) if isinstance(f, dict)}
    feeds_dir = feeds_path.parent
    shows_config_all: dict[str, list[dict[str, Any]]] = {}
    feed_landing_paths: list[str] = []
    feeds_with_custom_shows: list[str] = []
    feeds_missing_shows_cfg: list[str] = []
    feeds_empty_shows_cfg: list[str] = []

    def _get_shows_for_feed(feed_id: str) -> tuple[dict[str, Any], bool]:
        raw = raw_feeds_by_slug.get(feed_id, {})
        shows = raw.get("shows")
        if isinstance(shows, list):
            return {"shows": shows}, True
        path_val = str(raw.get("shows_path") or "").strip()
        candidates: list[Path] = []
        if path_val:
            candidates.append(feeds_dir / path_val)
        candidates.append(feeds_dir / "shows" / f"{feed_id}.json")
        for p in candidates:
            p = p.resolve()
            if p.exists():
                try:
                    data = read_json(p)
                    if isinstance(data, dict) and "shows" in data:
                        return data, True
                    if isinstance(data, list):
                        return {"shows": data}, True
                except Exception:
                    pass
        return {}, False

    def _ep_to_rss_item(ep: dict[str, Any], *, feed_title: str, base_url: str) -> str:
        title = _escape_xml(str(ep.get("title") or "Untitled"))
        link = _escape_xml(str(ep.get("link") or ""))
        desc = _escape_xml(str(ep.get("descriptionShort") or ep.get("descriptionHtml") or "")[:500])
        date = str(ep.get("dateText") or "")
        media = ep.get("media") or {}
        url = str(media.get("url") or "")
        typ = str(media.get("type") or "video/mp4")
        length = media.get("bytes") or ""
        enc = f'<enclosure url="{_escape_xml(url)}" type="{_escape_xml(typ)}" length="{length}"/>' if url else ""
        return f"""  <item>
    <title>{title}</title>
    <link>{link}</link>
    <description>{desc}</description>
    <pubDate>{date}</pubDate>
    <guid isPermaLink="false">{_escape_xml(str(ep.get("id") or ""))}</guid>
    {enc}
  </item>"""

    def _escape_xml(s: str) -> str:
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    for mf in manifest_feeds:
        fid = mf["id"]
        feed_title = mf.get("title") or fid
        episodes = mf.get("episodes") or []
        raw_cfg, has_custom_shows = _get_shows_for_feed(fid)
        if has_custom_shows:
            feeds_with_custom_shows.append(fid)
        if isinstance(raw_cfg, dict):
            shows_val = raw_cfg.get("shows")
            shows_list = shows_val if isinstance(shows_val, list) else []
            leftovers_title = raw_cfg.get("leftovers_title")
            leftovers_title_full = raw_cfg.get("leftovers_title_full")
            leftovers_description = raw_cfg.get("leftovers_description")
        else:
            shows_list = raw_cfg if isinstance(raw_cfg, list) else []
            leftovers_title = leftovers_title_full = leftovers_description = None

        # Warn on missing/empty show configs. Missing = no file / no inline shows / unreadable JSON.
        # Empty = file exists but no "shows" entries (or inline shows list is empty).
        if not has_custom_shows:
            feeds_missing_shows_cfg.append(fid)
        elif not shows_list:
            feeds_empty_shows_cfg.append(fid)

        shows = build_shows_for_feed(
            episodes,
            shows_list if shows_list else None,
            feed_id=fid,
            feed_title=feed_title,
            leftovers_title=leftovers_title,
            leftovers_title_full=leftovers_title_full,
            leftovers_description=leftovers_description,
        )
        def _ep_min(ep: dict[str, Any]) -> dict[str, Any]:
            m = ep.get("media") or {}
            return {
                "id": ep.get("id"),
                "slug": ep.get("slug"),
                "title": ep.get("title"),
                "dateText": ep.get("dateText"),
                "durationSec": ep.get("durationSec"),
                "media": {"url": m.get("url"), "pickedIsVideo": m.get("pickedIsVideo")} if m else None,
            }

        channel_image_url = mf.get("channelImageUrl") or None

        def _show_artwork(show_eps: list[dict], show_title: str) -> tuple[str | None, str | None]:
            """(artworkUrl, overlayText). Use first image from newest episode; else channel + overlay."""
            for ep in show_eps:
                img = ep.get("imageUrl") if isinstance(ep, dict) else None
                if img and str(img).strip():
                    return (str(img).strip(), None)
            if channel_image_url:
                return (channel_image_url, show_title or None)
            return (None, show_title or None)

        show_configs = []
        for s in shows:
            aw_url, aw_overlay = _show_artwork(s.get("episodes") or [], s.get("title") or "")
            show_configs.append({
                "id": s["id"],
                "slug": s["slug"],
                "title": s["title"],
                "title_full": s.get("title_full") or s["title"],
                "description": s.get("description"),
                "categories": s.get("categories") or [],
                "featured": s.get("featured", False),
                "isLeftovers": s.get("isLeftovers", False),
                "episodeCount": len(s.get("episodes") or []),
                "rssUrl": f"{base_path}feed/{fid}/show/{s['slug']}.xml",
                "episodes": [_ep_min(ep) for ep in (s.get("episodes") or [])[:100]],
                "artworkUrl": aw_url,
                "artworkOverlay": aw_overlay,
            })
        shows_config_all[fid] = show_configs

        # Feed landing page
        feed_dir = out_dir / "feed" / fid
        feed_dir.mkdir(parents=True, exist_ok=True)
        feed_vodcasts = {**vodcasts_config, "initialFeed": fid, "initialView": "browse"}
        feed_desc = f"Browse {feed_title} on {cfg.site.title}. {cfg.site.description}".strip()
        feed_seo_html = _seo_feed_html(
            feed_id=fid,
            feed_title=feed_title,
            show_configs=show_configs,
            base_path=base_path,
        )
        feed_html = _template_sub(
            template,
            {
                "base_path": base_path,
                "base_path_json": json.dumps(base_path),
                "site_json": json.dumps(site_json, ensure_ascii=False),
                "vodcasts_config": json.dumps(feed_vodcasts, ensure_ascii=False),
                "page_title": f"{feed_title} — {cfg.site.title}",
                "site_title": cfg.site.title,
                "site_description": cfg.site.description or "",
                "favicon_head_html": _build_favicon_head_html(base_path=base_path, feeds_path=feeds_path),
                "seo_body_html": feed_seo_html,
                "meta_head_html": _build_meta_head_html(
                    base_path=base_path,
                    site_title=cfg.site.title,
                    page_title=f"{feed_title} — {cfg.site.title}",
                    page_description=feed_desc,
                    canonical_path=f"{base_path}feed/{fid}/",
                    og_type="website",
                    og_image_path=og_image_url,
                    site_origin=site_origin,
                ),
            },
        )
        (feed_dir / "index.html").write_text(feed_html, encoding="utf-8")
        feed_landing_paths.append(f"feed/{fid}/")

        # Show landing pages (HTML): /feed/<fid>/shows/<show-slug>/
        shows_html_dir = feed_dir / "shows"
        shows_html_dir.mkdir(parents=True, exist_ok=True)
        for s in shows:
            eps = s.get("episodes") or []
            if not eps:
                continue
            show_slug = str(s.get("slug") or s.get("id") or "").strip()
            if not show_slug:
                continue
            show_title = str(s.get("title") or show_slug).strip() or show_slug
            show_desc = (str(s.get("description") or "").strip() or None)
            show_page_title = f"{show_title} — {feed_title} — {cfg.site.title}"
            show_path = f"{base_path}feed/{fid}/shows/{show_slug}/"
            show_seo_html = _seo_show_html(
                feed_id=fid,
                feed_title=feed_title,
                show_title=show_title,
                show_slug=show_slug,
                show_description=show_desc,
                episodes=eps,
                base_path=base_path,
            )
            show_vodcasts = {**vodcasts_config, "initialFeed": fid, "initialView": "browse"}
            show_html = _template_sub(
                template,
                {
                    "base_path": base_path,
                    "base_path_json": json.dumps(base_path),
                    "site_json": json.dumps(site_json, ensure_ascii=False),
                    "vodcasts_config": json.dumps(show_vodcasts, ensure_ascii=False),
                    "page_title": show_page_title,
                    "site_title": cfg.site.title,
                    "site_description": cfg.site.description or "",
                    "favicon_head_html": _build_favicon_head_html(base_path=base_path, feeds_path=feeds_path),
                    "seo_body_html": show_seo_html,
                    "meta_head_html": _build_meta_head_html(
                        base_path=base_path,
                        site_title=cfg.site.title,
                        page_title=show_page_title,
                        page_description=(show_desc or f"Browse episodes in {show_title}.").strip(),
                        canonical_path=show_path,
                        og_type="website",
                        og_image_path=og_image_url,
                        site_origin=site_origin,
                    ),
                },
            )
            show_dir = shows_html_dir / show_slug
            show_dir.mkdir(parents=True, exist_ok=True)
            (show_dir / "index.html").write_text(show_html, encoding="utf-8")

        # Show RSS feeds
        show_dir = feed_dir / "show"
        show_dir.mkdir(parents=True, exist_ok=True)
        for s in shows:
            eps = s.get("episodes") or []
            if not eps:
                continue
            rss_items = "\n".join(_ep_to_rss_item(ep, feed_title=feed_title, base_url=base_path) for ep in eps[:100])
            rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>{_escape_xml(s['title'])}</title>
    <link>{base_path}feed/{fid}/</link>
    <description>{_escape_xml(feed_title)} — {_escape_xml(s['title'])}</description>
    <language>en</language>
{rss_items}
  </channel>
</rss>"""
            (show_dir / f"{s['slug']}.xml").write_text(rss, encoding="utf-8")

    feed_titles = {fid: (mf.get("title") or fid) for mf in manifest_feeds for fid in [mf["id"]]}
    write_json(
        out_dir / "shows-config.json",
        {
            "version": 1,
            "base_path": base_path,
            "feeds": shows_config_all,
            "feedTitles": feed_titles,
            "feedLandingPaths": feed_landing_paths,
            "feedsWithCustomShows": feeds_with_custom_shows,
        },
    )
    if feeds_missing_shows_cfg:
        sample = ", ".join(feeds_missing_shows_cfg[:20])
        more = f" (+{len(feeds_missing_shows_cfg) - 20} more)" if len(feeds_missing_shows_cfg) > 20 else ""
        _log(f"[warn] missing show config for {len(feeds_missing_shows_cfg)} feeds (no shows file/inline config): {sample}{more}")
    if feeds_empty_shows_cfg:
        sample = ", ".join(feeds_empty_shows_cfg[:20])
        more = f" (+{len(feeds_empty_shows_cfg) - 20} more)" if len(feeds_empty_shows_cfg) > 20 else ""
        _log(f"[warn] empty shows list for {len(feeds_empty_shows_cfg)} feeds (shows file/inline config has no entries): {sample}{more}")
    _log(f"  {len(feed_landing_paths)} feed landings, {sum(len(s) for s in shows_config_all.values())} shows ({time.perf_counter() - t:.1f}s)")

    # Roku search feed (curated + paginated).
    if args.build_roku_search:
        _log("build roku search…")
        t = time.perf_counter()
        build_roku_search(
            out_dir=out_dir,
            base_path=base_path,
            site_origin=site_origin,
            public_sources=public_sources,
            manifest_feeds=manifest_feeds,
            shows_config_all=shows_config_all,
            args_limit_per_feed=args.roku_search_limit_per_feed,
            args_exclude_feeds=args.roku_search_exclude_feeds,
            log=_log,
        )
        _log(f"  done ({time.perf_counter() - t:.1f}s)")
    else:
        cleanup_roku_search_outputs(out_dir)
        _log("skip roku search (disabled)")

    # index.html
    home_desc = (cfg.site.description or cfg.site.subtitle or "").strip()
    html = _template_sub(
        template,
        {
            "base_path": base_path,
            "base_path_json": json.dumps(base_path),
            "site_json": json.dumps(site_json, ensure_ascii=False),
            "vodcasts_config": json.dumps(vodcasts_config, ensure_ascii=False),
            "page_title": cfg.site.title,
            "site_title": cfg.site.title,
            "site_description": cfg.site.description or "",
            "favicon_head_html": _build_favicon_head_html(base_path=base_path, feeds_path=feeds_path),
            "seo_body_html": _seo_home_html(cfg_site_title=cfg.site.title, cfg_site_desc=cfg.site.description or "", base_path=base_path),
            "meta_head_html": _build_meta_head_html(
                base_path=base_path,
                site_title=cfg.site.title,
                page_title=cfg.site.title,
                page_description=home_desc,
                canonical_path=base_path,
                og_type="website",
                og_image_path=og_image_url,
                site_origin=site_origin,
            ),
        },
    )
    (out_dir / "index.html").write_text(html, encoding="utf-8")

    # Browse page: /browse/ — same shell, client opens browse panel
    browse_dir = out_dir / "browse"
    browse_dir.mkdir(parents=True, exist_ok=True)
    browse_vodcasts = {**vodcasts_config, "initialView": "browseAll"}
    browse_desc = f"Browse featured shows and categories on {cfg.site.title}.".strip()
    browse_html = _template_sub(
        template,
        {
            "base_path": base_path,
            "base_path_json": json.dumps(base_path),
            "site_json": json.dumps(site_json, ensure_ascii=False),
            "vodcasts_config": json.dumps(browse_vodcasts, ensure_ascii=False),
            "page_title": f"Browse Shows — {cfg.site.title}",
            "site_title": cfg.site.title,
            "site_description": cfg.site.description or "",
            "favicon_head_html": _build_favicon_head_html(base_path=base_path, feeds_path=feeds_path),
            "seo_body_html": _seo_browse_all_html(
                cfg_site_title=cfg.site.title,
                shows_config_all=shows_config_all,
                feed_titles=feed_titles,
                base_path=base_path,
            ),
            "meta_head_html": _build_meta_head_html(
                base_path=base_path,
                site_title=cfg.site.title,
                page_title=f"Browse Shows — {cfg.site.title}",
                page_description=browse_desc,
                canonical_path=f"{base_path}browse/",
                og_type="website",
                og_image_path=og_image_url,
                site_origin=site_origin,
            ),
        },
    )
    (browse_dir / "index.html").write_text(browse_html, encoding="utf-8")

    # Support pages (static HTML, no JS needed)
    if support_template:
        support_pages = [
            (
                "about",
                "About Prays.be",
                "A free, simple way to watch faith-based videos and listen to audio-only feeds — anywhere.",
                """
<h1>About Prays.be</h1>
<p>Prays.be is a free, lightweight way to stream faith-based video and audio content from many different sources in one place.</p>
<p>Our goal is simple: make it easier to find something encouraging, thoughtful, and faith-forward — on any device.</p>
<div class="supportCard">
  <h2>What you can do here</h2>
  <ul>
    <li>Browse shows by category and channel.</li>
    <li>Pick up where you left off (saved on your device).</li>
    <li>Share links to feeds, shows, and episodes.</li>
  </ul>
</div>
<div class="supportCard">
  <h2>About sources</h2>
  <p>We link to third-party feeds. Some sources may be imperfect or controversial; we’re not here to point fingers — we’re here to build a calm, useful way to watch and listen. Over time, we may add clearer source notes and improve curation.</p>
  <p>We may adjust which feeds are included at any time.</p>
</div>
<div class="supportSplit">
  <div class="supportCard">
    <h2>Removal requests</h2>
    <p>If you run a feed and would prefer not to be included, email <a href="mailto:admin@prays.be">admin@prays.be</a> and we’ll remove it.</p>
  </div>
  <aside class="supportAside" aria-label="Reciprocal links">
    <div class="supportAsideTitle">Thanks to</div>
    <ul class="supportAsideLinks">
      <li><a href="https://bonpounou.com/directory/" target="_blank" rel="noopener noreferrer">Bonpounou Directory</a></li>
    </ul>
  </aside>
</div>
""".strip(),
            ),
            (
                "for",
                "Who it’s for",
                "Prays.be is for anyone who wants faith-forward, encouraging content — without drama.",
                """
<h1>Who it’s for</h1>
<p>Prays.be is for people who want a simple, respectful way to watch and listen to faith-based content — whether that’s sermons, Bible teaching, worship, testimony, or thoughtful talks.</p>
<div class="supportCard">
  <h2>Our tone</h2>
  <p>We’re aiming for wholesome, hopeful, and grounded. We don’t want doom-scrolling. We want something you can put on at home, on the train, or on a break — and feel better for it.</p>
</div>
<div class="supportCard">
  <h2>Limitations</h2>
  <p>Because content comes from many third-party feeds, availability and quality can vary. Some items may disappear, change, or fail to play. We’ll keep improving the experience.</p>
</div>
""".strip(),
            ),
            (
                "privacy",
                "Privacy Policy",
                "We use basic analytics to understand aggregate usage. Playback state is stored on your device.",
                """
<h1>Privacy</h1>
<p>We try to keep Prays.be simple and privacy-respecting.</p>
<div class="supportCard">
  <h2>Analytics</h2>
  <p>We use Google Analytics to understand aggregate usage (for example: which pages are visited, rough device/browser breakdowns, and general performance). We don’t use it to identify you, and we don’t sell personal data.</p>
</div>
<div class="supportCard">
  <h2>On-device storage</h2>
  <p>Prays.be stores some settings on your device (via local storage) to make the app work well — things like your last played episode, playback progress, and UI preferences.</p>
</div>
<div class="supportCard">
  <h2>Third-party content</h2>
  <p>When you play a feed item, your device may connect to third-party servers that host the media. Those providers may log requests under their own policies.</p>
</div>
""".strip(),
            ),
            (
                "legal",
                "Legal",
                "Prays.be is a viewer for third-party feeds. Content belongs to its respective owners.",
                """
<h1>Legal</h1>
<div class="supportCard">
  <h2>Third-party content</h2>
  <p>Prays.be links to and plays media from third-party RSS/Atom feeds. We don’t claim ownership of that content. Trademarks and copyrights belong to their respective owners.</p>
</div>
<div class="supportCard">
  <h2>No guarantees</h2>
  <p>We aim to provide a stable, positive experience, but feeds can change without notice. Content may be unavailable, inaccurate, or unsuitable for some audiences. Use your best judgment.</p>
</div>
<div class="supportCard">
  <h2>Changes and contact</h2>
  <p>We may adjust feeds and features at any time. If you believe a feed should be removed, email <a href="mailto:admin@prays.be">admin@prays.be</a>.</p>
</div>
""".strip(),
            ),
        ]

        for slug, title, desc, content_html in support_pages:
            pdir = out_dir / slug
            pdir.mkdir(parents=True, exist_ok=True)
            full_title = f"{title} — {cfg.site.title}"
            page_html = _template_sub(
                support_template,
                {
                    "base_path": base_path,
                    "page_title": full_title,
                    "site_title": cfg.site.title,
                    "favicon_head_html": _build_favicon_head_html(base_path=base_path, feeds_path=feeds_path),
                    "meta_head_html": _build_meta_head_html(
                        base_path=base_path,
                        site_title=cfg.site.title,
                        page_title=full_title,
                        page_description=desc,
                        canonical_path=f"{base_path}{slug}/",
                        og_type="article",
                        og_image_path=og_image_url,
                        site_origin=site_origin,
                    ),
                    "content_html": content_html,
                },
            )
            (pdir / "index.html").write_text(page_html, encoding="utf-8")

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

    # robots.txt + sitemap.xml (HTML pages only; exclude RSS/XML)
    sitemap_path = _norm_base_path(base_path) + "sitemap.xml"
    sitemap_loc = (site_origin + sitemap_path) if site_origin else sitemap_path

    url_entries: list[tuple[str, str | None]] = []
    for html_path in sorted(out_dir.rglob("*.html")):
        rel = html_path.relative_to(out_dir)
        rel_s = rel.as_posix()
        if rel_s == "404.html":
            continue
        if rel_s.startswith("assets/") or rel_s.startswith("data/"):
            continue
        url_path = _sitemap_url_path_for_html(rel, base_path=base_path)
        loc = (site_origin + url_path) if site_origin else url_path
        try:
            lastmod = time.strftime("%Y-%m-%d", time.gmtime(html_path.stat().st_mtime))
        except Exception:
            lastmod = None
        url_entries.append((loc, lastmod))

    (out_dir / "sitemap.xml").write_text(_build_sitemap_xml(url_entries), encoding="utf-8")
    (out_dir / "robots.txt").write_text(_build_robots_txt(base_path=base_path, sitemap_loc=sitemap_loc), encoding="utf-8")

    _log(f"build complete ({time.perf_counter() - t0:.1f}s total)")


if __name__ == "__main__":
    main()
