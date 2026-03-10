#!/usr/bin/env python3
"""
Generate a bonus feeds config from feeds/complete.md by selecting feeds that are
not present in other feed configs (by id or URL).

Intended workflow:
- Keep feeds/church.md + feeds/tech.md + feeds/news.md + feeds/dev.md as primary.
- Collect "extras" from feeds/complete.md into feeds/bonus.md for later review.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from scripts.shared import VODCASTS_ROOT
from scripts.sources import Source, load_sources_config


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate feeds/bonus.md from feeds/complete.md.")
    p.add_argument("--complete", default=str(VODCASTS_ROOT / "feeds" / "complete.md"), help="Complete feeds config (.md).")
    p.add_argument(
        "--exclude",
        action="append",
        default=[
            str(VODCASTS_ROOT / "feeds" / "church.md"),
            str(VODCASTS_ROOT / "feeds" / "tech.md"),
            str(VODCASTS_ROOT / "feeds" / "news.md"),
            str(VODCASTS_ROOT / "feeds" / "dev.md"),
        ],
        help="Exclude feeds present in this config (repeatable).",
    )
    p.add_argument("--out", default=str(VODCASTS_ROOT / "feeds" / "bonus.md"), help="Output feeds config (.md).")
    p.add_argument(
        "--skip-category",
        action="append",
        default=["needs-rss"],
        help="Skip sources with this category (repeatable). Default: needs-rss",
    )
    p.add_argument(
        "--exclude-suffix-2",
        action="store_true",
        default=True,
        help="Exclude ids that end in '-2' when the base id exists elsewhere (default true).",
    )
    return p.parse_args()


def _norm_url(url: str) -> str:
    u = str(url or "").strip()
    if not u:
        return ""
    try:
        sp = urlsplit(u)
    except Exception:
        return u.lower().rstrip("/")
    scheme = (sp.scheme or "http").lower()
    netloc = (sp.netloc or "").lower()
    path = (sp.path or "").rstrip("/")
    return urlunsplit((scheme, netloc, path, "", ""))


@dataclass(frozen=True)
class BonusSelection:
    selected: list[Source]
    skipped: dict[str, int]


def _select_bonus(complete: list[Source], excludes: list[list[Source]], *, skip_categories: set[str], exclude_suffix_2: bool) -> BonusSelection:
    excluded_ids = set()
    excluded_urls = set()
    for group in excludes:
        for s in group:
            excluded_ids.add(s.id)
            excluded_urls.add(_norm_url(s.feed_url))

    complete_ids = {s.id for s in complete}

    skipped: dict[str, int] = {
        "excluded_by_id": 0,
        "excluded_by_url": 0,
        "skipped_category": 0,
        "excluded_suffix_2": 0,
        "selected": 0,
    }

    out: list[Source] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    for s in complete:
        if s.id in excluded_ids:
            skipped["excluded_by_id"] += 1
            continue
        nu = _norm_url(s.feed_url)
        if nu in excluded_urls:
            skipped["excluded_by_url"] += 1
            continue
        cat = str(s.category or "").strip()
        if cat in skip_categories:
            skipped["skipped_category"] += 1
            continue
        if exclude_suffix_2 and s.id.endswith("-2"):
            base = s.id[:-2]
            if base in excluded_ids or base in complete_ids:
                skipped["excluded_suffix_2"] += 1
                continue
        if s.id in seen_ids:
            skipped["excluded_by_id"] += 1
            continue
        if nu in seen_urls:
            skipped["excluded_by_url"] += 1
            continue
        seen_ids.add(s.id)
        seen_urls.add(nu)
        out.append(s)

    skipped["selected"] = len(out)
    return BonusSelection(selected=out, skipped=skipped)


def _fmt_md(sources: list[Source]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines: list[str] = []
    lines.append("# Site")
    lines.append("- id: vodcasts-bonus")
    lines.append("- title: VODcasts (Bonus)")
    lines.append("- subtitle: Static vodcast browser")
    lines.append(f"- description: Feeds ported from complete.md that aren’t in the main sets. Generated {now} UTC.")
    lines.append("- base_path: /")
    lines.append("")
    lines.append("# Defaults")
    lines.append("- min_hours_between_checks: 2")
    lines.append("- request_timeout_seconds: 25")
    lines.append("- user_agent: actual-plays/vodcasts (+https://github.com/)")
    lines.append("")
    lines.append("# Feeds")
    lines.append("")

    def sort_key(s: Source) -> tuple[str, str]:
        return (str(s.category or "").strip() or "other", s.id)

    for s in sorted(sources, key=sort_key):
        lines.append(f"## {s.id}")
        lines.append(f"- url: {s.feed_url}")
        lines.append(f"- title: {s.title}")
        lines.append(f"- category: {s.category}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    args = _parse_args()
    complete_cfg = load_sources_config(Path(args.complete))
    exclude_cfgs = [load_sources_config(Path(p)).sources for p in (args.exclude or [])]
    skip_cats = {str(x).strip() for x in (args.skip_category or []) if str(x).strip()}

    sel = _select_bonus(complete_cfg.sources, exclude_cfgs, skip_categories=skip_cats, exclude_suffix_2=bool(args.exclude_suffix_2))
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_fmt_md(sel.selected), encoding="utf-8")

    skipped_bits = ", ".join(f"{k}={v}" for k, v in sel.skipped.items())
    print(f"[bonus] wrote {out_path} ({len(sel.selected)} feeds) [{skipped_bits}]")


if __name__ == "__main__":
    main()

