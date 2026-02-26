from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

from scripts.shared import VODCASTS_ROOT, fetch_url, write_json
from scripts.sources import load_sources_config


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch RSS/Atom feeds for vodcasts and cache raw XML.")
    p.add_argument("--feeds", default=str(VODCASTS_ROOT / "feeds" / "dev.md"), help="Feeds config (.md or .json).")
    p.add_argument("--cache", default=str(VODCASTS_ROOT / "cache" / "dev"), help="Cache directory.")
    p.add_argument("--force", action="store_true", help="Ignore cooldown and refetch all feeds.")
    p.add_argument("--concurrency", type=int, default=3, help="Number of feeds to fetch concurrently (default: 3).")
    p.add_argument("--quiet", action="store_true", help="Less logging (still prints errors).")
    return p.parse_args()


def _log(msg: str, *, quiet: bool) -> None:
    if not quiet:
        print(msg)


def _read_state(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "feeds": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "feeds": {}}

def _looks_like_feed_xml(content: bytes | None) -> bool:
    if not content:
        return False
    s = content[:128 * 1024].decode("utf-8", errors="replace").lstrip().lower()
    if not s:
        return False
    if s.startswith("<!doctype html") or s.startswith("<html"):
        return False
    if "<rss" in s or "<feed" in s or "<rdf:rdf" in s:
        return True
    if "<channel" in s and ("<item" in s or "<enclosure" in s):
        return True
    return False


def main() -> None:
    args = _parse_args()
    feeds_path = Path(args.feeds)
    cache_dir = Path(args.cache)
    state_path = cache_dir / "state.json"
    feeds_out_dir = cache_dir / "feeds"

    cfg = load_sources_config(feeds_path)
    defaults = {}
    if feeds_path.suffix.lower() == ".md":
        # best effort: load min_hours_between_checks from markdown defaults when available
        try:
            from scripts.shared import read_feeds_config

            raw = read_feeds_config(feeds_path)
            defaults = raw.get("defaults") or {}
        except Exception:
            defaults = {}

    min_hours = float(defaults.get("min_hours_between_checks") or 2)
    timeout_seconds = int(defaults.get("request_timeout_seconds") or 25)
    user_agent = str(defaults.get("user_agent") or "actual-plays/vodcasts")

    state = _read_state(state_path)
    feeds_state = state.setdefault("feeds", {})
    now = int(time.time())

    def work(source):
        sid = source.id
        url = source.feed_url
        if not url:
            return sid, {"status": "skip", "reason": "missing url"}

        prev = feeds_state.get(sid) if isinstance(feeds_state.get(sid), dict) else {}
        last_checked = int(prev.get("last_checked_unix") or 0)
        cooldown_ok = (now - last_checked) >= int(min_hours * 3600)
        if not args.force and last_checked and not cooldown_ok:
            return sid, {"status": "skip", "reason": "cooldown"}

        etag = prev.get("etag")
        last_mod = prev.get("last_modified")
        try:
            res = fetch_url(
                url,
                timeout_seconds=timeout_seconds,
                user_agent=user_agent,
                if_none_match=etag,
                if_modified_since=last_mod,
            )
            if res.status == 304:
                return sid, {
                    "status": "not_modified",
                    "url": url,
                    "last_checked_unix": now,
                    "etag": etag,
                    "last_modified": last_mod,
                }
            if not res.content:
                raise ValueError(f"empty response (status {res.status})")
            if res.status < 200 or res.status >= 300:
                raise ValueError(f"http {res.status}")
            if not _looks_like_feed_xml(res.content):
                raise ValueError("not-a-feed-xml (refusing to overwrite cache)")
            feeds_out_dir.mkdir(parents=True, exist_ok=True)
            (feeds_out_dir / f"{sid}.xml").write_bytes(res.content)
            return sid, {
                "status": "ok",
                "url": url,
                "fetched_url": res.url,
                "last_checked_unix": now,
                "last_ok_unix": now,
                "etag": res.etag or etag,
                "last_modified": res.last_modified or last_mod,
                "bytes": len(res.content),
            }
        except Exception as e:
            return sid, {
                "status": "error",
                "url": url,
                "last_checked_unix": now,
                "error": str(getattr(e, "message", None) or e),
            }

    total = len(cfg.sources)
    _log(f"Updating {total} feeds from {feeds_path} -> {feeds_out_dir}", quiet=args.quiet)

    results = {}
    with ThreadPoolExecutor(max_workers=max(1, int(args.concurrency))) as ex:
        futs = [ex.submit(work, s) for s in cfg.sources]
        for fut in as_completed(futs):
            sid, r = fut.result()
            results[sid] = r
            st = r.get("status")
            if st == "ok":
                _log(f"[ok] {sid} ({r.get('bytes')} bytes)", quiet=args.quiet)
            elif st == "not_modified":
                _log(f"[304] {sid}", quiet=args.quiet)
            elif st == "skip":
                _log(f"[skip] {sid} ({r.get('reason')})", quiet=args.quiet)
            else:
                print(f"[error] {sid}: {r.get('error')}")

    for sid, r in results.items():
        feeds_state[sid] = r

    state["version"] = 1
    state["updated_at_unix"] = now
    state["site"] = asdict(cfg.site)
    write_json(state_path, state)


if __name__ == "__main__":
    main()
