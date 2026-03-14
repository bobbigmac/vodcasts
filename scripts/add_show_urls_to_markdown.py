from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse


SHOW_HREF_RE = re.compile(r'href="(/feed/([^/]+)/shows/([^/]+)/\?ep=([^"#]+))"')
PRAYS_URL_RE = re.compile(r"^https://prays\.be(?P<path>/\S+)$")


@dataclass(frozen=True)
class EpisodeRef:
    feed: str
    episode_slug: str
    fragment: str
    is_show_url: bool
    show_slug: str | None


def build_show_map(site_feed_dir: Path) -> dict[tuple[str, str], str]:
    show_map: dict[tuple[str, str], str] = {}
    for index_path in sorted(site_feed_dir.glob("*/shows/*/index.html")):
        text = index_path.read_text(encoding="utf-8", errors="replace")
        for href, feed, _show, episode_slug in SHOW_HREF_RE.findall(text):
            show_map.setdefault((feed, episode_slug), href)
    return show_map


def parse_episode_ref(url: str) -> EpisodeRef | None:
    match = PRAYS_URL_RE.match(url.strip())
    if not match:
        return None

    parsed = urlparse(url.strip())
    path = parsed.path or ""
    query = parse_qs(parsed.query)
    fragment = f"#{parsed.fragment}" if parsed.fragment else ""
    parts = [p for p in path.split("/") if p]

    if len(parts) >= 2 and parts[0] == "feed":
        feed = parts[1]
        episode_slug = str((query.get("ep") or [""])[0]).strip()
        is_show_url = len(parts) >= 4 and parts[2] == "shows"
        show_slug = parts[3] if is_show_url else None
        if episode_slug:
            return EpisodeRef(
                feed=feed,
                episode_slug=episode_slug,
                fragment=fragment,
                is_show_url=is_show_url,
                show_slug=show_slug,
            )
        # Plain feed landing URL is not useful for tweet rewriting.
        return None

    # Legacy/direct episode route: /<feed>/<episode-slug>/[#t=...]
    if len(parts) >= 2:
        feed = parts[0]
        if len(parts) >= 3 and parts[1] == "shows":
            show_slug = parts[2]
            episode_slug = str((query.get("ep") or [""])[0]).strip()
            if not episode_slug:
                return None
            return EpisodeRef(
                feed=feed,
                episode_slug=episode_slug,
                fragment=fragment,
                is_show_url=True,
                show_slug=show_slug,
            )
        return EpisodeRef(feed=feed, episode_slug=parts[1], fragment=fragment, is_show_url=False, show_slug=None)

    return None


def build_modern_episode_url(ref: EpisodeRef) -> str:
    return f"https://prays.be/{ref.feed}/{ref.episode_slug}/{ref.fragment}"


def build_modern_show_url(ref: EpisodeRef, show_map: dict[tuple[str, str], str]) -> str | None:
    base_show_path = show_map.get((ref.feed, ref.episode_slug))
    if not base_show_path:
        return None
    modern_path = re.sub(r"^/feed/", "/", base_show_path, count=1)
    return f"https://prays.be{modern_path}{ref.fragment}"


def rewrite_markdown(text: str, show_map: dict[tuple[str, str], str]) -> tuple[str, int]:
    lines = text.splitlines()
    out: list[str] = []
    changes = 0
    i = 0

    while i < len(lines):
        line = lines[i]
        out.append(line)

        current_url = line.strip()
        line_prefix = ""
        if current_url.startswith("Show URL: "):
            line_prefix = "Show URL: "
            current_url = current_url[len(line_prefix) :].strip()
        ref = parse_episode_ref(current_url)
        if not ref:
            i += 1
            continue

        desired_main_url = current_url
        desired_show_line = None

        if ref.is_show_url:
            resolved_show_url = build_modern_show_url(ref, show_map)
            if resolved_show_url:
                desired_main_url = resolved_show_url
        else:
            desired_main_url = build_modern_episode_url(ref)
            resolved_show_url = build_modern_show_url(ref, show_map)
            if resolved_show_url:
                desired_show_line = f"Show URL: {resolved_show_url}"

        if desired_main_url != current_url:
            out[-1] = f"{line_prefix}{desired_main_url}"
            changes += 1

        next_line = lines[i + 1] if i + 1 < len(lines) else None
        has_show_line = next_line is not None and next_line.startswith("Show URL: ")

        if desired_show_line:
            if has_show_line:
                if next_line != desired_show_line:
                    out.append(desired_show_line)
                    changes += 1
                else:
                    out.append(next_line)
                i += 2
                continue

            out.append(desired_show_line)
            changes += 1
            i += 1
            continue

        if has_show_line:
            changes += 1
            i += 2
            continue

        i += 1

    rewritten = "\n".join(out)
    if text.endswith("\n"):
        rewritten += "\n"
    return rewritten, changes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Add Show URL lines to markdown files by resolving built /feed/<id>/shows/<show> routes."
    )
    parser.add_argument("markdown_files", nargs="+", help="Markdown files to inspect/update.")
    parser.add_argument(
        "--site-feed-dir",
        default="dist/feed",
        help="Built feed directory containing */shows/*/index.html pages (default: dist/feed).",
    )
    parser.add_argument("--write", action="store_true", help="Write changes in place.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    site_feed_dir = Path(args.site_feed_dir)
    if not site_feed_dir.exists():
        raise SystemExit(f"site feed dir not found: {site_feed_dir}")

    show_map = build_show_map(site_feed_dir)
    if not show_map:
        raise SystemExit(f"no show routes found under: {site_feed_dir}")

    touched = 0
    for name in args.markdown_files:
        path = Path(name)
        original = path.read_text(encoding="utf-8", errors="replace")
        rewritten, changes = rewrite_markdown(original, show_map)
        if args.write and rewritten != original:
            path.write_text(rewritten, encoding="utf-8")
            touched += 1
        status = "updated" if args.write and rewritten != original else "checked"
        print(f"{status}: {path} (changes={changes})")
        if not args.write:
            print(rewritten)
    if args.write:
        print(f"files_updated={touched}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
