from __future__ import annotations

import argparse
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from scripts.feeds_md import parse_feeds_markdown
from scripts.shared import fetch_url


VODCASTS_ROOT = Path(__file__).resolve().parents[1]


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def normalize_url_strict(url: str) -> str:
    """
    Normalize URL for *exact* duplicate detection.

    Conservative: lower scheme/host, strip fragment, strip trailing slash.
    Keep query as-is (except stable sort), since some feed URLs are query-based.
    """
    u = str(url or "").strip()
    if not u:
        return ""
    p = urlparse(u)
    scheme = (p.scheme or "").lower()
    netloc = (p.netloc or "").lower()
    path = p.path or ""
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    # Stable query ordering so equivalent URLs match.
    q = ""
    if p.query:
        q = urlencode(sorted(parse_qsl(p.query, keep_blank_values=True)))
    return urlunparse((scheme, netloc, path, p.params or "", q, ""))  # drop fragment


def normalize_url_loose(url: str) -> str:
    """
    Looser normalization for "maybe duplicate" reporting: drop query entirely.
    """
    u = str(url or "").strip()
    if not u:
        return ""
    p = urlparse(u)
    scheme = (p.scheme or "").lower()
    netloc = (p.netloc or "").lower()
    path = p.path or ""
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return urlunparse((scheme, netloc, path, p.params or "", "", ""))  # drop query+fragment


def looks_like_feed_xml(content: bytes | None) -> bool:
    if not content:
        return False
    head = content[:2000].lstrip()
    if not head:
        return False
    # If it starts with HTML, it's almost certainly not a feed.
    head_l = head[:600].lower()
    if head_l.startswith(b"<!doctype html") or head_l.startswith(b"<html"):
        return False
    # Common RSS/Atom roots.
    return (
        b"<rss" in head_l
        or b"<feed" in head_l
        or b"<rdf:rdf" in head_l
        or b"<channel" in head_l
        or head_l.startswith(b"<?xml")
    )


@dataclass(frozen=True)
class FeedRef:
    file: Path
    slug: str
    url: str
    title: str


@dataclass
class FetchInfo:
    ok: bool
    status: int | None
    effective_url: str | None
    content_len: int | None
    looks_like_feed: bool
    error: str | None


def read_cfg(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return parse_feeds_markdown(text)


def collect_feed_refs(cfg: dict[str, Any], file: Path) -> list[FeedRef]:
    out: list[FeedRef] = []
    for f in cfg.get("feeds") or []:
        if not isinstance(f, dict):
            continue
        slug = str(f.get("slug") or "").strip()
        url = str(f.get("url") or "").strip()
        title = str(f.get("title_override") or f.get("title") or slug).strip()
        if slug and url:
            out.append(FeedRef(file=file, slug=slug, url=url, title=title))
    return out


def cfg_includes(cfg: dict[str, Any]) -> list[str]:
    defaults = cfg.get("defaults") if isinstance(cfg.get("defaults"), dict) else {}
    inc = defaults.get("include")
    if isinstance(inc, str):
        inc = [inc]
    if isinstance(inc, list):
        return [str(x).strip() for x in inc if str(x).strip()]
    return []


def resolve_includes(files: list[Path], cfgs: dict[Path, dict[str, Any]]) -> dict[Path, set[Path]]:
    """
    Return transitive includes per file.
    """
    by_name = {p.name: p for p in files}
    inc_map: dict[Path, set[Path]] = {}
    for f in files:
        incs = set()
        for name in cfg_includes(cfgs[f]):
            # include paths are relative to feeds/ in this repo.
            pn = Path(name).name
            if pn in by_name:
                incs.add(by_name[pn])
        inc_map[f] = incs

    # Transitive closure.
    changed = True
    while changed:
        changed = False
        for f in files:
            cur = set(inc_map.get(f) or set())
            for g in list(cur):
                cur |= inc_map.get(g) or set()
            if cur != inc_map.get(f):
                inc_map[f] = cur
                changed = True
    return inc_map


def fetch_one(url: str, user_agent: str, timeout: int) -> FetchInfo:
    try:
        r = fetch_url(url, timeout_seconds=int(timeout), user_agent=user_agent)
        content = r.content
        looks = looks_like_feed_xml(content)
        ok = (r.status == 200) and looks and (content is not None) and (len(content) > 200)
        return FetchInfo(
            ok=ok,
            status=r.status,
            effective_url=r.url,
            content_len=len(content) if content is not None else None,
            looks_like_feed=looks,
            error=None,
        )
    except Exception as e:
        return FetchInfo(
            ok=False,
            status=None,
            effective_url=None,
            content_len=None,
            looks_like_feed=False,
            error=_norm_ws(str(e)),
        )


def fetch_with_retry(
    url: str,
    *,
    user_agent: str,
    timeouts: tuple[int, int],
) -> FetchInfo:
    a = fetch_one(url, user_agent, timeouts[0])
    if a.ok:
        return a

    # If it's a hard 404/410, don't bother retrying.
    if a.status in (404, 410):
        return a

    b = fetch_one(url, user_agent, timeouts[1])
    # Prefer the "best" info for reporting.
    if b.ok:
        return b
    if b.status is not None:
        return b
    return a


def remove_feed_blocks(md: str, *, slugs_to_remove: set[str]) -> str:
    if not slugs_to_remove:
        return md

    lines = md.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    # Only operate within the Feeds section to avoid clobbering other `##` headings.
    feeds_start = None
    for i, line in enumerate(lines):
        if re.match(r"^\s*#\s+feeds\b", line, flags=re.IGNORECASE):
            feeds_start = i
            break
    if feeds_start is None:
        return md

    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if i >= feeds_start:
            m = re.match(r"^\s*##\s+(.+?)\s*$", line)
            if m:
                heading = m.group(1).strip()
                if heading in slugs_to_remove:
                    # Skip this block until the next heading of same/higher level.
                    i += 1
                    while i < len(lines) and not re.match(r"^\s*##\s+", lines[i]) and not re.match(
                        r"^\s*#\s+", lines[i]
                    ):
                        i += 1
                    # Also skip any immediate blank lines to avoid extra whitespace.
                    while i < len(lines) and lines[i].strip() == "":
                        i += 1
                    # Ensure there's a single blank line between sections/feeds.
                    if out and out[-1].strip() != "":
                        out.append("")
                    continue

        out.append(line)
        i += 1

    # Trim excessive blank lines at end.
    while out and out[-1].strip() == "":
        out.pop()
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Remove dead feed URLs and report duplicates across feeds/*.md")
    ap.add_argument(
        "--feeds",
        nargs="*",
        default=None,
        help="Feeds markdown files (default: all feeds/*.md)",
    )
    ap.add_argument("--apply", action="store_true", help="Write changes back to files")
    ap.add_argument("--report", default="tmp/clean_feeds_report.md", help="Write markdown report here")
    ap.add_argument("--max-workers", type=int, default=12, help="Concurrent fetch workers")
    ap.add_argument("--timeout1", type=int, default=12, help="First attempt timeout (seconds)")
    ap.add_argument("--timeout2", type=int, default=25, help="Retry timeout (seconds)")
    ap.add_argument("--user-agent", default="actual-plays/vodcasts (+https://github.com/)", help="HTTP user agent")
    args = ap.parse_args()

    feeds_dir = VODCASTS_ROOT / "feeds"
    if args.feeds:
        files = [Path(p).resolve() for p in args.feeds]
    else:
        files = sorted(feeds_dir.glob("*.md"))
    files = [p for p in files if p.exists()]
    if not files:
        raise SystemExit("No feeds files found.")

    cfgs: dict[Path, dict[str, Any]] = {p: read_cfg(p) for p in files}
    includes = resolve_includes(files, cfgs)

    # Collect all feed refs.
    refs: list[FeedRef] = []
    refs_by_file: dict[Path, list[FeedRef]] = {}
    for f in files:
        r = collect_feed_refs(cfgs[f], f)
        refs.extend(r)
        refs_by_file[f] = r

    # Determine per-file UA/timeout defaults (if present).
    per_file_ua: dict[Path, str] = {}
    for f in files:
        d = cfgs[f].get("defaults") if isinstance(cfgs[f].get("defaults"), dict) else {}
        ua = str(d.get("user_agent") or args.user_agent).strip() or args.user_agent
        per_file_ua[f] = ua

    # Fetch URLs once per distinct URL to keep this fast.
    uniq_urls = sorted({r.url for r in refs})
    fetch_results: dict[str, FetchInfo] = {}
    timeouts = (int(args.timeout1), int(args.timeout2))

    with ThreadPoolExecutor(max_workers=max(1, int(args.max_workers))) as ex:
        futs = {}
        for url in uniq_urls:
            # Use generic UA; most feeds don't care. We'll still use per-file UA for reporting below.
            fut = ex.submit(fetch_with_retry, url, user_agent=args.user_agent, timeouts=timeouts)
            futs[fut] = url
        for fut in as_completed(futs):
            url = futs[fut]
            fetch_results[url] = fut.result()

    # Evaluate dead feeds and duplicates.
    dead_by_file: dict[Path, list[tuple[FeedRef, FetchInfo]]] = {f: [] for f in files}
    live_refs_by_file: dict[Path, list[FeedRef]] = {f: [] for f in files}
    effective_url_by_ref: dict[tuple[Path, str], str] = {}

    for r in refs:
        info = fetch_results.get(r.url) or FetchInfo(
            ok=False, status=None, effective_url=None, content_len=None, looks_like_feed=False, error="missing fetch result"
        )
        # Re-try with per-file UA if the generic UA got blocked (rare, but cheap insurance).
        if not info.ok and (info.status in (401, 403) or info.status is None):
            info2 = fetch_with_retry(r.url, user_agent=per_file_ua[r.file], timeouts=timeouts)
            # Prefer a successful per-file result.
            if info2.ok:
                info = info2

        eff = info.effective_url or r.url
        effective_url_by_ref[(r.file, r.slug)] = eff

        if info.ok:
            live_refs_by_file[r.file].append(r)
        else:
            dead_by_file[r.file].append((r, info))

    removals_by_file: dict[Path, set[str]] = {f: set() for f in files}

    # Remove dead feeds everywhere.
    for f, items in dead_by_file.items():
        for r, _info in items:
            removals_by_file[f].add(r.slug)

    # Remove within-file exact duplicates (by effective URL), except dev.md.
    for f in files:
        if f.name == "dev.md":
            continue
        seen: set[str] = set()
        for r in live_refs_by_file[f]:
            eff = effective_url_by_ref.get((f, r.slug)) or r.url
            k = normalize_url_strict(eff)
            if not k:
                continue
            if k in seen:
                removals_by_file[f].add(r.slug)
            else:
                seen.add(k)

    # Remove redundant duplicates where file includes another file that already defines the same feed.
    # Safe because the including file will still get the feed via include.
    by_effective_url: dict[str, list[FeedRef]] = {}
    for r in refs:
        if r.slug in removals_by_file[r.file]:
            continue
        eff = effective_url_by_ref.get((r.file, r.slug)) or r.url
        k = normalize_url_strict(eff)
        if not k:
            continue
        by_effective_url.setdefault(k, []).append(r)

    for k, items in by_effective_url.items():
        if len(items) < 2:
            continue
        # If A includes B, remove from A.
        for a in items:
            for b in items:
                if a.file == b.file:
                    continue
                if b.file in (includes.get(a.file) or set()):
                    # a includes b; keep b's definition, remove a.
                    if a.file.name != "dev.md":
                        removals_by_file[a.file].add(a.slug)

    # Enforce: only dev.md may have cross-file duplicates.
    # For exact duplicates (by strict effective URL), keep one canonical definition and remove the rest.
    file_priority = [
        "church.md",
        "church-audio-only.md",
        "news.md",
        "tech.md",
        "bonus.md",
        "complete.md",
    ]
    prio_idx = {name: i for i, name in enumerate(file_priority)}

    def prio(path: Path) -> int:
        return prio_idx.get(path.name, 10_000)

    for k, items in by_effective_url.items():
        keepers = [it for it in items if it.slug not in removals_by_file[it.file]]
        if len(keepers) < 2:
            continue
        # If any non-dev files share a URL, they are duplicates.
        non_dev = [it for it in keepers if it.file.name != "dev.md"]
        if len({it.file for it in non_dev}) < 2:
            continue
        # Pick the canonical non-dev entry; if all are dev (shouldn't happen here), skip.
        canonical = sorted(non_dev, key=lambda it: (prio(it.file), it.file.name, it.slug))[0]
        for it in non_dev:
            if it.file == canonical.file and it.slug == canonical.slug:
                continue
            removals_by_file[it.file].add(it.slug)

    # Deduplicate complete.md vs any other file (complete is reference-only).
    other_urls: set[str] = set()
    other_slugs: set[str] = set()
    for r in refs:
        if r.file.name == "complete.md":
            continue
        if r.slug in removals_by_file[r.file]:
            continue
        other_slugs.add(r.slug)
        eff = effective_url_by_ref.get((r.file, r.slug)) or r.url
        other_urls.add(normalize_url_strict(eff))

    complete_path = next((p for p in files if p.name == "complete.md"), None)
    if complete_path:
        for r in refs_by_file[complete_path]:
            if r.slug in removals_by_file[complete_path]:
                continue
            eff = effective_url_by_ref.get((complete_path, r.slug)) or r.url
            if r.slug in other_slugs or normalize_url_strict(eff) in other_urls:
                removals_by_file[complete_path].add(r.slug)

    # Report: potential cross-file duplicates (exact effective URL).
    cross_file_dupes: list[tuple[str, list[FeedRef]]] = []
    for k, items in by_effective_url.items():
        files_set = {x.file for x in items if x.slug not in removals_by_file[x.file]}
        if len(files_set) >= 2:
            cross_file_dupes.append((k, [x for x in items if x.slug not in removals_by_file[x.file]]))
    cross_file_dupes.sort(key=lambda x: (-len(x[1]), x[0]))

    # Report: "maybe dupes" by loose URL (same path, different query) across files.
    by_loose: dict[str, list[FeedRef]] = {}
    for r in refs:
        if r.slug in removals_by_file[r.file]:
            continue
        eff = effective_url_by_ref.get((r.file, r.slug)) or r.url
        k = normalize_url_loose(eff)
        if not k:
            continue
        by_loose.setdefault(k, []).append(r)
    loose_maybe = [(k, v) for k, v in by_loose.items() if len({x.file for x in v}) >= 2 and len(v) >= 2]
    loose_maybe.sort(key=lambda x: (-len(x[1]), x[0]))

    report_lines: list[str] = []
    report_lines.append("# Feeds cleanup report")
    report_lines.append("")
    report_lines.append(f"- files: {', '.join([p.name for p in files])}")
    report_lines.append(f"- apply: {'yes' if args.apply else 'no (dry-run)'}")
    report_lines.append(f"- timeouts: {timeouts[0]}s then {timeouts[1]}s")
    report_lines.append("")

    total_removed = sum(len(v) for v in removals_by_file.values())
    report_lines.append("## Summary")
    report_lines.append(f"- removals (planned): {total_removed}")
    report_lines.append("")

    report_lines.append("## Dead / non-feed URLs removed")
    any_dead = False
    for f in files:
        items = dead_by_file.get(f) or []
        items = [(r, info) for (r, info) in items if r.slug in removals_by_file[f]]
        if not items:
            continue
        any_dead = True
        report_lines.append(f"### {f.name}")
        for r, info in sorted(items, key=lambda x: x[0].slug):
            status = info.status if info.status is not None else "ERR"
            why = info.error or ("not a feed" if not info.looks_like_feed else "unknown")
            report_lines.append(f"- `{r.slug}` — {status} — {r.url} — {why}")
        report_lines.append("")
    if not any_dead:
        report_lines.append("- (none)")
        report_lines.append("")

    report_lines.append("## Duplicates removed safely (includes/within-file/complete)")
    any_dupes_removed = False
    for f in files:
        if not removals_by_file[f]:
            continue
        # Skip dead-only; we want to highlight duplicates separately if possible.
        # We'll approximate: entries removed that were not dead in fetch results.
        live_removed = []
        for r in refs_by_file[f]:
            if r.slug not in removals_by_file[f]:
                continue
            info = fetch_results.get(r.url)
            if info and info.ok:
                live_removed.append(r)
        if not live_removed:
            continue
        any_dupes_removed = True
        report_lines.append(f"### {f.name}")
        for r in sorted(live_removed, key=lambda x: x.slug):
            report_lines.append(f"- `{r.slug}` — {r.url}")
        report_lines.append("")
    if not any_dupes_removed:
        report_lines.append("- (none)")
        report_lines.append("")

    report_lines.append("## Remaining exact cross-file duplicates (needs review)")
    if cross_file_dupes:
        for k, items in cross_file_dupes:
            report_lines.append(f"- `{k}`")
            for it in sorted(items, key=lambda x: (x.file.name, x.slug)):
                report_lines.append(f"  - {it.file.name}: `{it.slug}` — {it.url}")
    else:
        report_lines.append("- (none)")
    report_lines.append("")

    report_lines.append("## Possible duplicates (same base URL, different query) (needs review)")
    if loose_maybe:
        for k, items in loose_maybe:
            # Only show if strict URLs differ.
            stricts = {normalize_url_strict((effective_url_by_ref.get((it.file, it.slug)) or it.url)) for it in items}
            if len(stricts) <= 1:
                continue
            report_lines.append(f"- `{k}`")
            for it in sorted(items, key=lambda x: (x.file.name, x.slug)):
                report_lines.append(f"  - {it.file.name}: `{it.slug}` — {it.url}")
    else:
        report_lines.append("- (none)")
    report_lines.append("")

    rep_path = Path(args.report)
    rep_path.parent.mkdir(parents=True, exist_ok=True)
    rep_path.write_text("\n".join(report_lines).rstrip() + "\n", encoding="utf-8")

    if args.apply:
        for f in files:
            slugs = removals_by_file.get(f) or set()
            if not slugs:
                continue
            before = f.read_text(encoding="utf-8", errors="replace")
            after = remove_feed_blocks(before, slugs_to_remove=slugs)
            if after != before:
                f.write_text(after, encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
