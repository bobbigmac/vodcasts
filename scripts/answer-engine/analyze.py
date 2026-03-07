from __future__ import annotations

import argparse
from pathlib import Path

from answer_engine_lib import analyze_transcripts, parse_common_args, resolve_paths


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Parse transcripts into cached segments for answer search and chapters.")
    parse_common_args(p)
    p.add_argument(
        "--transcript",
        action="append",
        default=[],
        help="Transcript path to analyze (absolute, or relative to site/assets/transcripts/). Repeat to analyze a small explicit set.",
    )
    p.add_argument("--force", action="store_true", help="Re-analyze all files (ignore incremental signatures).")
    p.add_argument("--no-incremental", action="store_true", help="Disable incremental mode.")
    p.add_argument("--limit-files", type=int, default=0, help="Analyze only the first N transcript files (debug).")
    p.add_argument("--quiet", action="store_true", help="Less logging.")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    cache_dir, transcripts_root, db_path = resolve_paths(args)
    transcript_paths: list[Path] = []
    for raw in list(getattr(args, "transcript", []) or []):
        p = Path(str(raw or "").strip())
        if not str(p):
            continue
        if not p.is_absolute():
            p = transcripts_root / p
        p = p.resolve()
        if not p.exists():
            raise SystemExit(f"Transcript not found: {p}")
        try:
            p.relative_to(Path(transcripts_root).resolve())
        except Exception:
            raise SystemExit(f"Transcript is not under transcripts root: {p}")
        transcript_paths.append(p)

    try:
        analyze_transcripts(
            db_path=db_path,
            transcripts_root=transcripts_root,
            cache_dir=cache_dir,
            incremental=not bool(args.no_incremental),
            force=bool(args.force),
            limit_files=int(args.limit_files or 0),
            transcript_paths=transcript_paths,
            quiet=bool(args.quiet),
        )
    except KeyboardInterrupt:
        print("\n[answer-engine] interrupted (Ctrl+C). You can re-run; incremental mode will resume.")
        raise SystemExit(130)


if __name__ == "__main__":
    main()
