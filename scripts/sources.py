from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.shared import read_feeds_config, read_json


@dataclass(frozen=True)
class SiteConfig:
    id: str
    title: str
    subtitle: str
    description: str
    base_path: str
    url: str = ""


@dataclass(frozen=True)
class Source:
    id: str
    title: str
    category: str
    feed_url: str
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourcesConfig:
    site: SiteConfig
    sources: list[Source]


def _norm_site_from_md(site: dict[str, Any]) -> SiteConfig:
    return SiteConfig(
        id=str(site.get("id") or "vodcasts").strip() or "vodcasts",
        title=str(site.get("title") or "VODcasts").strip() or "VODcasts",
        subtitle=str(site.get("subtitle") or "").strip(),
        description=str(site.get("description") or "").strip(),
        base_path=str(site.get("base_path") or "/").strip() or "/",
        url=str(site.get("url") or site.get("site_url") or "").strip(),
    )


def _norm_site_from_json(site: dict[str, Any] | None) -> SiteConfig:
    site = site or {}
    return SiteConfig(
        id=str(site.get("id") or "vodcasts").strip() or "vodcasts",
        title=str(site.get("title") or "VODcasts").strip() or "VODcasts",
        subtitle=str(site.get("subtitle") or "").strip(),
        description=str(site.get("description") or "").strip(),
        base_path=str(site.get("base_path") or "/").strip() or "/",
        url=str(site.get("url") or site.get("site_url") or "").strip(),
    )


def load_sources_config(path: Path) -> SourcesConfig:
    suffix = path.suffix.lower()
    if suffix == ".json":
        doc = read_json(path)
        sources = []
        for s in (doc.get("sources") or []):
            if not isinstance(s, dict):
                continue
            sid = str(s.get("id") or "").strip()
            if not sid:
                continue
            tags = s.get("tags")
            tags_tup = tuple(t for t in tags) if isinstance(tags, list) else ()
            sources.append(
                Source(
                    id=sid,
                    title=str(s.get("title") or sid).strip() or sid,
                    category=str(s.get("category") or "other").strip() or "other",
                    feed_url=str(s.get("feed_url") or s.get("url") or "").strip(),
                    tags=tags_tup,
                )
            )
        return SourcesConfig(site=_norm_site_from_json(doc.get("site")), sources=sources)

    if suffix == ".md":
        cfg = read_feeds_config(path)
        site = _norm_site_from_md(cfg.get("site") or {})
        sources = []
        for f in (cfg.get("feeds") or []):
            if not isinstance(f, dict):
                continue
            disabled = f.get("disabled")
            if disabled not in (None, False, "", "false", "False", 0):
                # Disabled feeds remain in config for audit/notes, but are not built into sources.
                continue
            slug = str(f.get("slug") or "").strip()
            if not slug:
                continue
            url = str(f.get("url") or "").strip()
            if not url:
                continue
            title = str(f.get("title_override") or f.get("title") or slug).strip() or slug
            category = str(f.get("category") or "").strip()
            if not category:
                cats = f.get("categories")
                if isinstance(cats, list) and cats:
                    category = str(cats[0] or "").strip()
            category = category or "other"
            tags_raw = f.get("tags")
            tags = tuple(t for t in tags_raw) if isinstance(tags_raw, list) else ()
            sources.append(
                Source(
                    id=slug,
                    title=title,
                    category=category,
                    feed_url=url,
                    tags=tags,
                )
            )
        return SourcesConfig(site=site, sources=sources)

    raise ValueError(f"Unsupported feeds config format: {path} (expected .md or .json)")
