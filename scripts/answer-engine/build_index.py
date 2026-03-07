from __future__ import annotations

import argparse

from answer_engine_lib import parse_common_args, rebuild_search_index, resolve_paths


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build/update the SQLite FTS index from cached analyzed segments.")
    parse_common_args(p)
    p.add_argument("--quiet", action="store_true", help="Less logging.")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    _cache_dir, _transcripts_root, db_path = resolve_paths(args)

    try:
        rebuild_search_index(db_path=db_path, quiet=bool(args.quiet))
    except KeyboardInterrupt:
        print("\n[answer-engine] interrupted (Ctrl+C).")
        raise SystemExit(130)


if __name__ == "__main__":
    main()
