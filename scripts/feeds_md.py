from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


_HEADING_RE = re.compile(r"^(?P<level>#{1,6})\s+(?P<title>.+?)\s*$")
_KV_RE = re.compile(r"^(?:[-*+]\s*)?(?P<key>[A-Za-z0-9_./-]+)\s*(?P<sep>[:=])\s*(?P<val>.*)\s*$")


def _slugify(text: str) -> str:
    s = str(text or "").strip().lower()
    s = re.sub(r"[’']", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "unknown"


def _is_slug(s: str) -> bool:
    # Vodcasts ids often come from existing JSON configs and may include underscores.
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,80}", str(s or "").strip()))


def _infer_slug(feed: dict[str, Any]) -> str:
    t = str(feed.get("title_override") or feed.get("title") or "").strip()
    if t:
        return _slugify(t)
    u = str(feed.get("url") or "").strip()
    if u:
        # best-effort: last path segment or hostname-ish
        u2 = re.sub(r"^https?://", "", u, flags=re.IGNORECASE)
        u2 = u2.split("?", 1)[0].split("#", 1)[0]
        parts = [p for p in re.split(r"[\\/]", u2) if p]
        if parts:
            return _slugify(parts[-1])
    return ""


def _norm_key(key: str) -> str:
    return str(key or "").strip()


def _strip_comment(line: str) -> str:
    # Allow Markdown comments anywhere.
    if "<!--" in line:
        return line.split("<!--", 1)[0].rstrip()
    return line


def _split_list(value: str, *, seps: str = ",;") -> list[str]:
    """
    Split a 1-line list.

    By default, accepts both commas and semicolons as separators so humans/LLMs
    can use either (or mix them).
    """
    s = str(value or "").strip()
    if not s:
        return []
    if not seps:
        return [s]
    rx = "[" + re.escape(seps) + "]"
    parts = [p.strip() for p in re.split(rx, s)]
    return [p for p in parts if p]


def _parse_scalar(value: str) -> Any:
    s = str(value or "").strip()
    if s == "":
        return ""
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    if re.fullmatch(r"-?\d+", s):
        try:
            return int(s)
        except Exception:
            return s
    if re.fullmatch(r"-?\d+\.\d+", s):
        try:
            return float(s)
        except Exception:
            return s
    return s


@dataclass
class _Section:
    name: str
    level: int


def parse_feeds_markdown(text: str) -> dict[str, Any]:
    """
    Parse a feeds config written in conventional Markdown.

    Structure:

    # Site
    - title: ...
    - subtitle: ...
    - description: ...
    - base_path: /
    - footer_links: GitHub=https://github.com/; Docs=https://example.com/
    ## Home Intro
    (markdown body captured as site.home_intro_md)

    # Defaults
    - min_hours_between_checks: 2
    - max_episodes_per_feed: 1000
    ...

    # Feeds
    ## off-menu
    - url: https://...
    - title_override: ...
    - owners: A; B
    - common_speakers: ...
    - categories: comedy/british, interviews
    - notes: ...
    - editors_note: ...
    """
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")

    cfg: dict[str, Any] = {"site": {}, "defaults": {}, "feeds": []}
    site: dict[str, Any] = cfg["site"]
    defaults: dict[str, Any] = cfg["defaults"]

    current_top: str | None = None  # site/defaults/feeds
    current_feed: dict[str, Any] | None = None
    in_site_intro = False
    intro_lines: list[str] = []

    def flush_intro() -> None:
        nonlocal intro_lines
        if intro_lines:
            body = "\n".join(intro_lines).strip()
            if body:
                site["home_intro_md"] = body
        intro_lines = []

    for raw in lines:
        line = _strip_comment(raw).rstrip("\n")
        m = _HEADING_RE.match(line.strip())
        if m:
            flush_intro()
            in_site_intro = False
            level = len(m.group("level"))
            title = m.group("title").strip()
            title_l = title.lower()
            # Allow flexible heading levels (LLM edits may drift).
            if title_l in ("site", "site config", "config/site"):
                current_top = "site"
                current_feed = None
                continue
            if title_l in ("defaults", "default", "settings", "config/defaults"):
                current_top = "defaults"
                current_feed = None
                continue
            if title_l in ("feeds", "podcasts", "subscriptions"):
                current_top = "feeds"
                current_feed = None
                continue

            if current_top == "site" and title_l in ("home intro", "home_intro", "intro", "welcome"):
                in_site_intro = True
                current_feed = None
                continue

            if current_top == "feeds" and level >= 2:
                s = title.strip()
                # Strip common prefixes.
                s = re.sub(r"^(feed|podcast|slug)\s*[:\-]\s*", "", s, flags=re.IGNORECASE).strip()
                # Take the LHS of separators if present.
                for sep in (" — ", " - ", " – ", " | "):
                    if sep in s:
                        s = s.split(sep, 1)[0].strip()
                        break
                # If it's already slug-shaped, keep as-is; otherwise slugify.
                slug = s if _is_slug(s) else _slugify(s)
                current_feed = {"slug": slug}
                cfg["feeds"].append(current_feed)
            continue

        if in_site_intro:
            intro_lines.append(raw)
            continue

        if line.strip() == "":
            continue

        km = _KV_RE.match(line)
        if not km:
            # Ignore free-form content for now (keeps config predictable).
            continue

        key = _norm_key(km.group("key"))
        val_raw = km.group("val")

        target: dict[str, Any] | None
        if current_top == "site":
            target = site
        elif current_top == "defaults":
            target = defaults
        elif current_top == "feeds" and current_feed is not None:
            target = current_feed
        else:
            target = None

        if target is None:
            continue

        key_l = key.lower()

    # Key aliases / normalization.
        if current_top == "feeds" and key_l == "title":
            key_l = "title_override"
            key = "title_override"
        if key_l in ("xmlurl", "xml_url", "feed", "feed_url", "feedurl"):
            key_l = "url"
            key = "url"
        if key_l in ("editorsnote", "editor_note"):
            key_l = "editors_note"
            key = "editors_note"
        if key_l == "commonspeakers":
            key_l = "common_speakers"
            key = "common_speakers"
        if key_l in ("supplemental_podcast", "supplementalfeed", "supplemental_feed", "hidden_from_browse"):
            key_l = "supplemental"
            key = "supplemental"

        if key_l == "further_search_names":
            items = _split_list(val_raw, seps=",;")
            if current_top == "site":
                site["further_search_names"] = items
            continue

        if key_l == "include":
            items = _split_list(val_raw, seps=",;")
            if current_top == "defaults" and target is not None:
                target["include"] = items
            continue

        if key_l in ("owners", "owner", "common_speakers", "exclude_speakers", "categories", "category", "tags"):
            items = _split_list(val_raw, seps=",;")
            if key_l in ("owner",):
                key = "owners"
            if key_l in ("category",):
                key = "categories"
            target[key] = items
            continue

        if key_l in ("footer_links", "footer_link"):
            # footer_links: Label=https://...; Label2=https://...
            # Use semicolons only (URLs can legally contain commas).
            pairs = _split_list(val_raw, seps=";")
            links: list[dict[str, str]] = []
            for p in pairs:
                if "=" not in p:
                    continue
                label, href = p.split("=", 1)
                label = label.strip()
                href = href.strip()
                if not label or not href:
                    continue
                links.append({"label": label, "href": href})
            # footer_link is additive; footer_links replaces.
            if key_l == "footer_link":
                existing = target.get("footer_links")
                if not isinstance(existing, list):
                    existing = []
                target["footer_links"] = list(existing) + links
            else:
                target["footer_links"] = links
            continue

        target[key] = _parse_scalar(val_raw)

    flush_intro()

    # Post-parse validation + inference.
    site = cfg.get("site") if isinstance(cfg.get("site"), dict) else {}
    defaults = cfg.get("defaults") if isinstance(cfg.get("defaults"), dict) else {}
    feeds = cfg.get("feeds") if isinstance(cfg.get("feeds"), list) else []

    # If the file is basically empty/nonsense, fail fast (but allow legitimately empty feeds).
    if not site and not defaults and not feeds:
        raise ValueError(
            "No config content found. Expected headings like `# Site`, `# Defaults`, and `# Feeds`."
        )

    # Fill missing slug/url using best-effort inference; validate minimally.
    errors: list[str] = []
    seen: set[str] = set()
    for i, feed in enumerate(feeds):
        if not isinstance(feed, dict):
            errors.append(f"Feed entry #{i+1}: not a mapping/object.")
            continue
        slug = str(feed.get("slug") or "").strip()
        if not slug:
            inferred = _infer_slug(feed)
            if inferred:
                feed["slug"] = inferred
                slug = inferred
        if not slug:
            errors.append(f"Feed entry #{i+1}: missing slug (use a `## <slug>` heading or `slug: ...`).")
        else:
            if slug in seen:
                errors.append(f"Feed entry #{i+1}: duplicate slug `{slug}`.")
            seen.add(slug)

        url = str(feed.get("url") or "").strip()
        if not url:
            errors.append(f"Feed `{slug or ('#'+str(i+1))}`: missing url (use `url: https://...`).")

    if errors:
        raise ValueError("Invalid feeds config:\n- " + "\n- ".join(errors))

    # Normalize: drop empty site/defaults if not provided.
    if not isinstance(cfg.get("feeds"), list):
        cfg["feeds"] = []
    if not isinstance(cfg.get("defaults"), dict):
        cfg["defaults"] = {}
    if not isinstance(cfg.get("site"), dict):
        cfg["site"] = {}
    return cfg


def dumps_feeds_markdown(cfg: dict[str, Any]) -> str:
    """
    Convert the JSON-style feeds config into a conventional Markdown config.
    """
    cfg = cfg or {}
    site = cfg.get("site") if isinstance(cfg.get("site"), dict) else {}
    defaults = cfg.get("defaults") if isinstance(cfg.get("defaults"), dict) else {}
    feeds = cfg.get("feeds") if isinstance(cfg.get("feeds"), list) else []

    def kv(key: str, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            v = "true" if value else "false"
        else:
            v = str(value)
        return f"- {key}: {v}"

    def fmt_list(values: Any, *, sep: str) -> str:
        if not values:
            return ""
        if isinstance(values, str):
            return values.strip()
        if isinstance(values, list):
            return sep.join([str(v).strip() for v in values if str(v).strip()])
        return str(values).strip()

    out: list[str] = []

    out.append("# Site")
    for k in ("title", "subtitle", "description", "base_path", "further_search", "further_search_batch_size"):
        v = site.get(k)
        if v is None or str(v).strip() == "":
            continue
        out.append(kv(k, v))
    # Optional site-level exclusions (speaker extraction can be noisy).
    ex = site.get("exclude_speakers")
    if isinstance(ex, list) and ex:
        out.append(kv("exclude_speakers", fmt_list(ex, sep=", ")))

    further_names = site.get("further_search_names")
    if isinstance(further_names, list) and further_names:
        out.append(kv("further_search_names", fmt_list(further_names, sep="; ")))

    footer_links = site.get("footer_links") or []
    if isinstance(footer_links, list) and footer_links:
        parts: list[str] = []
        for link in footer_links:
            if not isinstance(link, dict):
                continue
            label = str(link.get("label") or "").strip()
            href = str(link.get("href") or "").strip()
            if label and href:
                parts.append(f"{label}={href}")
        if parts:
            out.append(kv("footer_links", "; ".join(parts)))

    home_intro_md = str(site.get("home_intro_md") or "").strip()
    if home_intro_md:
        out.append("")
        out.append("## Home Intro")
        out.append(home_intro_md)

    out.append("")
    out.append("# Defaults")
    for k in sorted(defaults.keys()):
        out.append(kv(k, defaults.get(k)))

    out.append("")
    out.append("# Feeds")

    # Stable per-feed key ordering: the known keys first, then the rest alphabetically.
    known = [
        "url",
        "title_override",
        "supplemental",
        "owners",
        "common_speakers",
        "exclude_speakers",
        "categories",
        "tags",
        "notes",
        "editors_note",
    ]
    for feed in feeds:
        if not isinstance(feed, dict):
            continue
        slug = str(feed.get("slug") or "").strip()
        if not slug:
            continue
        out.append("")
        out.append(f"## {slug}")

        keys = [k for k in known if k in feed]
        extras = sorted([k for k in feed.keys() if k not in keys and k != "slug"])
        for k in keys + extras:
            v = feed.get(k)
            if v is None or (isinstance(v, str) and v.strip() == ""):
                continue
            if k in ("owners", "common_speakers"):
                out.append(kv(k, fmt_list(v, sep="; ")))
            elif k == "exclude_speakers":
                out.append(kv(k, fmt_list(v, sep=", ")))
            elif k in ("categories", "tags"):
                out.append(kv(k, fmt_list(v, sep=", ")))
            else:
                out.append(kv(k, v))

    return "\n".join(out).rstrip() + "\n"
