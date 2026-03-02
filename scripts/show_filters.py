"""
Smart filters: map feed episodes into Netflix-style "shows".

Each feed can define a list of shows with JSON filters. Episodes matching a show's
filter are assigned to that show (first match wins). Unmatched episodes go to a
channel-named leftovers row automatically.

Filter types:
- all: matches any episode (use ONLY when literally all episodes follow the same pattern with no meaningful series)
- title_contains: substring in episode title (case-insensitive)
- title_contains_any: title contains any of the values (list)
- title_regex: regex on episode title
- description_contains: substring in description (strip HTML)
- title_prefix: episode title starts with string
- title_suffix: episode title ends with string

Multi-feed shows (stub): filter may include "feed_ids": ["id1","id2"] to span feeds.
"""
from __future__ import annotations

import re
from typing import Any

from scripts.shared import strip_html


def _norm(s: str) -> str:
    return (s or "").strip()


def _ep_text(ep: dict[str, Any], key: str) -> str:
    v = ep.get(key)
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    return str(v)


def _ep_desc_plain(ep: dict[str, Any]) -> str:
    html = _ep_text(ep, "descriptionHtml") or _ep_text(ep, "description") or ""
    return strip_html(html)


def _ep_title(ep: dict[str, Any]) -> str:
    return _ep_text(ep, "title")


def _matches_filter(ep: dict[str, Any], f: dict[str, Any], *, feed_id: str = "") -> bool:
    """True if episode matches this filter. Filters are ANDed within a show."""
    # Stub: feed_ids for multi-channel shows (not yet used)
    _ = f.get("feed_ids")
    ftype = str(f.get("type") or "").strip().lower()
    if not ftype:
        return False
    if ftype == "all":
        return True

    title = _ep_title(ep)
    desc = _ep_desc_plain(ep)

    if ftype == "title_contains":
        val = _norm(f.get("value") or f.get("contains") or "")
        if not val:
            return False
        return val.lower() in title.lower()

    if ftype == "title_contains_any":
        vals = f.get("values") or f.get("value") or f.get("contains_any") or []
        if isinstance(vals, str):
            vals = [vals]
        if not vals:
            return False
        tl = title.lower()
        return any(_norm(v).lower() in tl for v in vals if v)

    if ftype == "title_regex":
        pat = _norm(f.get("value") or f.get("pattern") or "")
        if not pat:
            return False
        try:
            return bool(re.search(pat, title, re.IGNORECASE))
        except re.error:
            return False

    if ftype == "title_prefix":
        val = _norm(f.get("value") or f.get("prefix") or "")
        if not val:
            return False
        return title.lower().startswith(val.lower())

    if ftype == "title_suffix":
        val = _norm(f.get("value") or f.get("suffix") or "")
        if not val:
            return False
        return title.lower().endswith(val.lower())

    if ftype == "description_contains":
        val = _norm(f.get("value") or f.get("contains") or "")
        if not val:
            return False
        return val.lower() in desc.lower()

    return False


def _matches_show(ep: dict[str, Any], show: dict[str, Any], *, feed_id: str = "") -> bool:
    """True if episode matches all filters for this show."""
    filters = show.get("filters") or show.get("filter")
    if not filters:
        if isinstance(show.get("filter"), dict):
            return _matches_filter(ep, show["filter"], feed_id=feed_id)
        return False  # No filter = no match (goes to leftovers)
    if isinstance(filters, dict):
        filters = [filters]
    if not isinstance(filters, list):
        return True
    return all(_matches_filter(ep, f, feed_id=feed_id) for f in filters if isinstance(f, dict))


def assign_episodes_to_shows(
    episodes: list[dict[str, Any]],
    shows_config: list[dict[str, Any]],
    *,
    feed_id: str,
    feed_title: str,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """
    Assign episodes to shows. First matching show wins. Unmatched -> leftovers.

    Returns (show_id -> [episodes], leftovers).
    """
    show_eps: dict[str, list[dict[str, Any]]] = {}
    matched_ids: set[str] = set()
    ep_id = lambda e: e.get("id") or e.get("slug") or id(e)

    for show in shows_config or []:
        if not isinstance(show, dict):
            continue
        sid = str(show.get("id") or show.get("slug") or "").strip()
        if not sid:
            continue
        show_eps[sid] = []
        for ep in episodes:
            if ep_id(ep) in matched_ids:
                continue
            if _matches_show(ep, show, feed_id=feed_id):
                show_eps[sid].append(ep)
                matched_ids.add(ep_id(ep))

    leftovers = [ep for ep in episodes if ep_id(ep) not in matched_ids]
    return show_eps, leftovers


def build_shows_for_feed(
    episodes: list[dict[str, Any]],
    shows_config: list[dict[str, Any]] | None,
    *,
    feed_id: str,
    feed_title: str,
    feed_category: str = "other",
    leftovers_title: str | None = None,
    leftovers_title_full: str | None = None,
    leftovers_description: str | None = None,
) -> list[dict[str, Any]]:
    """
    Build the list of shows for a feed. Named shows from filters; unmatched
    episodes go to leftovers (channel-named or custom leftovers_title).

    Returns list of {id, title, slug, episodes, isLeftovers}.
    """
    leftovers_label = (leftovers_title or feed_title).strip() or feed_title
    leftovers_full = (leftovers_title_full or leftovers_label).strip() or leftovers_label
    leftovers_desc = (leftovers_description or "").strip() or None

    def _leftovers_dict(eps: list) -> dict[str, Any]:
        return {
            "id": f"{feed_id}-leftovers",
            "slug": _slugify(f"{feed_id}-leftovers"),
            "title": leftovers_label,
            "title_full": leftovers_full,
            "description": leftovers_desc,
            "categories": [],
            "featured": False,
            "episodes": eps,
            "isLeftovers": True,
        }

    if not shows_config:
        return [_leftovers_dict(list(episodes))]

    show_eps, leftovers = assign_episodes_to_shows(
        episodes, shows_config, feed_id=feed_id, feed_title=feed_title
    )

    out: list[dict[str, Any]] = []
    for show in shows_config:
        if not isinstance(show, dict):
            continue
        sid = str(show.get("id") or show.get("slug") or "").strip()
        if not sid:
            continue
        eps = show_eps.get(sid, [])
        if not eps:
            continue
        title = str(show.get("title") or sid).strip() or sid
        title_full = str(show.get("title_full") or show.get("title_out_of_context") or title).strip() or title
        description = str(show.get("description") or "").strip()
        slug = _slugify(sid)
        raw_cats = show.get("categories")
        categories = [str(c).strip() for c in raw_cats] if isinstance(raw_cats, list) else []
        if not categories:
            categories = [feed_category] if feed_category else []
        featured = bool(show.get("featured"))
        out.append({
            "id": sid,
            "slug": slug,
            "title": title,
            "title_full": title_full,
            "description": description or None,
            "categories": categories,
            "featured": featured,
            "episodes": eps,
            "isLeftovers": False,
        })

    if leftovers:
        out.append(_leftovers_dict(leftovers))

    return out


def _slugify(s: str) -> str:
    s = str(s or "").lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "unknown"
