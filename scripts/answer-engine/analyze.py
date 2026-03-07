from __future__ import annotations

import argparse

from answer_engine_lib import analyze_transcripts, parse_common_args, resolve_paths


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Parse transcripts into cached segments for answer search and chapters.")
    parse_common_args(p)
    p.add_argument("--force", action="store_true", help="Re-analyze all files (ignore incremental signatures).")
    p.add_argument("--no-incremental", action="store_true", help="Disable incremental mode.")
    p.add_argument("--limit-files", type=int, default=0, help="Analyze only the first N transcript files (debug).")
    p.add_argument("--quiet", action="store_true", help="Less logging.")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    cache_dir, transcripts_root, db_path = resolve_paths(args)
    try:
        analyze_transcripts(
            db_path=db_path,
            transcripts_root=transcripts_root,
            cache_dir=cache_dir,
            incremental=not bool(args.no_incremental),
            force=bool(args.force),
            limit_files=int(args.limit_files or 0),
            quiet=bool(args.quiet),
        )
    except KeyboardInterrupt:
        print("\n[answer-engine] interrupted (Ctrl+C). You can re-run; incremental mode will resume.")
        raise SystemExit(130)


if __name__ == "__main__":
    main()
