from __future__ import annotations

import argparse
import json
from pathlib import Path

from chapter_generation_lib import (
    _chapters_needs_update,
    _chapters_output_path,
    _iter_transcript_files,
    _write_chapters_for_transcript,
    chapters_from_segments,
    cues_to_segments,
    default_transcripts_root,
    parse_transcript_file,
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate chapters JSON directly from transcript files.")
    p.add_argument("--transcripts", default="", help="Transcripts root (default: site/assets/transcripts/).")
    p.add_argument(
        "--transcript",
        default="",
        help="Transcript path (absolute, or relative to site/assets/transcripts/). If omitted, processes all transcripts.",
    )
    p.add_argument(
        "--mode",
        default="hybrid",
        help="Chapter generation mode. `hybrid` uses semantic candidates plus local LLM refinement; `semantic` skips the LLM pass.",
    )
    p.add_argument("--llm-url", default="", help="Optional local LLM endpoint, e.g. http://127.0.0.1:8765.")
    p.add_argument(
        "--out",
        default="",
        help="Directory to write chapters into (default: site/assets/chapters/<feed>/<episode>.chapters.json).",
    )
    p.add_argument("--adjacent", action="store_true", help="Write chapters next to the transcript as *.chapters.json.")
    p.add_argument("--force", action="store_true", help="Rewrite even if the chapters file looks up-to-date.")
    p.add_argument("--print", action="store_true", help="Print the resulting chapter list.")
    return p.parse_args()


def _resolve_transcripts_root(raw: str) -> Path:
    return Path(raw).resolve() if raw else default_transcripts_root()


def _resolve_transcript_arg(raw: str, transcripts_root: Path) -> Path:
    p = Path(raw)
    if not p.is_absolute():
        p = transcripts_root / p
    p = p.resolve()
    if not p.exists():
        raise SystemExit(f"Transcript not found: {p}")
    try:
        p.relative_to(transcripts_root.resolve())
    except Exception:
        raise SystemExit(f"Transcript is not under transcripts root: {p}")
    return p


def _iter_targets(transcripts_root: Path, transcript_arg: str) -> list[Path]:
    if transcript_arg:
        return [_resolve_transcript_arg(transcript_arg, transcripts_root)]
    return sorted(Path(p).resolve() for p in _iter_transcript_files(transcripts_root))


def _print_chapters(path: Path) -> None:
    raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    chs = raw.get("chapters") if isinstance(raw, dict) else None
    for c in chs or []:
        t = float(c.get("startTime") or 0.0)
        title = str(c.get("title") or "")
        kind = str(c.get("kind") or "")
        extra = f" [{kind}]" if kind else ""
        print(f"{t:8.1f}{extra}  {title}")


def main() -> None:
    args = _parse_args()
    if str(args.llm_url or "").strip():
        import os

        os.environ["VOD_CHAPTER_LLM_URL"] = str(args.llm_url).strip()

    transcripts_root = _resolve_transcripts_root(str(args.transcripts or "").strip())
    if not transcripts_root.exists():
        raise SystemExit(f"Transcripts root not found: {transcripts_root}")

    targets = _iter_targets(transcripts_root, str(args.transcript or "").strip())
    if not targets:
        print(f"[chapter-generation] no transcript files found under {transcripts_root}", flush=True)
        return
    if bool(args.print) and len(targets) != 1:
        raise SystemExit("--print requires --transcript")

    out_dir = None if bool(args.adjacent) else (Path(args.out).resolve() if args.out else (transcripts_root.parent / "chapters"))
    mode = str(args.mode or "semantic")

    wrote = 0
    skipped = 0
    for idx, transcript_path in enumerate(targets, 1):
        target = _chapters_output_path(transcript_path=transcript_path, out_dir=out_dir, adjacent=bool(args.adjacent))
        rel = str(transcript_path.relative_to(transcripts_root.resolve())).replace("\\", "/")
        if target and not args.force and target.exists() and not _chapters_needs_update(target, mode=mode):
            skipped += 1
            print(f"[chapter-generation] [{idx}/{len(targets)}] skip  {rel}", flush=True)
            continue

        cues = parse_transcript_file(transcript_path)
        segments = cues_to_segments(cues)
        chapters = chapters_from_segments(
            feed=transcript_path.parent.name,
            episode_slug=transcript_path.stem,
            segments=segments,
            mode=mode,
        )
        _write_chapters_for_transcript(
            transcript_path=transcript_path,
            chapters=chapters,
            out_dir=out_dir,
            adjacent=bool(args.adjacent),
        )
        wrote += 1
        print(
            f"[chapter-generation] [{idx}/{len(targets)}] write {rel} chapters={len(chapters.get('chapters') or [])}",
            flush=True,
        )

    print(f"[chapter-generation] done: wrote={wrote} skipped={skipped}", flush=True)

    if args.print and target and target.exists():
        _print_chapters(target)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[chapter-generation] interrupted (Ctrl+C).", flush=True)
        raise SystemExit(130)
