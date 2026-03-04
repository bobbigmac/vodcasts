import argparse
import fnmatch
import json
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _iter_show_files(shows_dir: Path) -> list[Path]:
    return sorted([p for p in shows_dir.glob("*.json") if p.is_file()])


def _as_bool(s: str) -> bool:
    v = str(s or "").strip().lower()
    if v in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if v in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise ValueError(f"invalid boolean: {s!r}")


def cmd_list(args: argparse.Namespace) -> int:
    shows_dir = Path(args.shows_dir)
    if not shows_dir.exists():
        raise SystemExit(f"shows dir not found: {shows_dir}")

    rows: list[dict[str, Any]] = []
    for p in _iter_show_files(shows_dir):
        feed_id = p.stem
        if args.feed and feed_id not in args.feed:
            continue
        doc = _read_json(p)
        shows = doc.get("shows") if isinstance(doc, dict) else None
        if not isinstance(shows, list):
            continue
        for s in shows:
            if not isinstance(s, dict):
                continue
            if s.get("featured") is not True:
                continue
            rows.append(
                {
                    "feed": feed_id,
                    "show": str(s.get("id") or ""),
                    "title": str(s.get("title_full") or s.get("title") or s.get("id") or ""),
                    "file": str(p),
                }
            )

    if args.json:
        print(json.dumps({"featured": rows}, ensure_ascii=False, indent=2))
        return 0

    print(f"featured_shows={len(rows)}")
    for r in rows:
        print(f"{r['feed']}\t{r['show']}\t{r['title']}")
    return 0


def _resolve_targets(*, shows_dir: Path, feeds: list[str], feed_glob: str | None) -> list[Path]:
    out: list[Path] = []

    if feed_glob:
        for p in _iter_show_files(shows_dir):
            if p.stem and fnmatch.fnmatchcase(p.stem, feed_glob):
                out.append(p)

    for f in feeds or []:
        f = str(f or "").strip()
        if not f:
            continue
        p = (shows_dir / f"{f}.json").resolve()
        if p.exists():
            out.append(p)
        else:
            raise SystemExit(f"feed shows file not found: {shows_dir / (f + '.json')}")

    # De-dupe, stable order.
    seen = set()
    uniq: list[Path] = []
    for p in out:
        if p in seen:
            continue
        seen.add(p)
        uniq.append(p)
    return uniq


def cmd_set(args: argparse.Namespace) -> int:
    shows_dir = Path(args.shows_dir)
    if not shows_dir.exists():
        raise SystemExit(f"shows dir not found: {shows_dir}")

    featured = _as_bool(args.featured)
    target_files = _resolve_targets(shows_dir=shows_dir, feeds=args.feed or [], feed_glob=args.feed_glob)
    if not target_files:
        raise SystemExit("no targets (pass --feed and/or --feed-glob)")

    want_all = bool(args.all)
    want_shows = [str(s or "").strip() for s in (args.show or []) if str(s or "").strip()]
    if not want_all and not want_shows:
        raise SystemExit("pass at least one --show, or use --all")

    changed = 0
    touched = 0
    for p in target_files:
        doc = _read_json(p)
        shows = doc.get("shows") if isinstance(doc, dict) else None
        if not isinstance(shows, list):
            continue

        file_changed = False
        missing = set(want_shows)
        for s in shows:
            if not isinstance(s, dict):
                continue
            sid = str(s.get("id") or "").strip()
            if want_all or (sid in missing):
                missing.discard(sid)
                if bool(s.get("featured")) != featured:
                    s["featured"] = featured
                    file_changed = True

        if missing and not want_all:
            raise SystemExit(f"shows not found in {p.name}: {', '.join(sorted(missing))}")

        if file_changed:
            touched += 1
            if args.dry_run:
                print(f"[dry-run] would update: {p}")
            else:
                _write_json(p, doc)
                print(f"updated: {p}")
            changed += 1

    if args.dry_run and changed == 0:
        print("[dry-run] no changes")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="List and toggle featured show flags in feeds/shows/*.json.")
    p.add_argument("--shows-dir", default="feeds/shows", help="Directory containing per-feed shows JSON files.")

    sub = p.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List featured shows.")
    p_list.add_argument("--feed", action="append", help="Filter to a specific feed id (repeatable).")
    p_list.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    p_list.set_defaults(fn=cmd_list)

    p_set = sub.add_parser("set", help="Set featured=true/false for one or more shows.")
    p_set.add_argument("--feed", action="append", help="Feed id (file stem) to edit (repeatable).")
    p_set.add_argument("--feed-glob", help="Glob-match feed ids (file stems), e.g. 'cbn-com-*'.")
    p_set.add_argument("--show", action="append", help="Show id to edit (repeatable).")
    p_set.add_argument("--all", action="store_true", help="Apply to all shows in each targeted feed.")
    p_set.add_argument("--featured", required=True, help="true/false")
    p_set.add_argument("--dry-run", action="store_true", help="Print intended changes without writing.")
    p_set.set_defaults(fn=cmd_set)

    return p


def main() -> int:
    args = build_parser().parse_args()
    return int(args.fn(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
