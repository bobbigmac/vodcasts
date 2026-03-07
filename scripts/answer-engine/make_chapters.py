from __future__ import annotations

import argparse
from pathlib import Path

from answer_engine_lib import (
    _chapters_needs_update,
    _chapters_output_path,
    parse_common_args,
    resolve_paths,
    write_chapters_from_analysis,
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate chapters JSON from cached analyzed segments.")
    parse_common_args(p)
    p.add_argument(
        "--transcript",
        default="",
        help="Transcript path (absolute, or relative to site/assets/transcripts/). If omitted, writes all chapters from analysis cache.",
    )
    p.add_argument("--mode", default="hybrid", help="Chapter generation mode. `hybrid` uses semantic candidates plus local LLM refinement; `semantic` skips the LLM pass.")
    p.add_argument("--llm-url", default="", help="Optional local LLM endpoint, e.g. http://127.0.0.1:8765. Avoids reloading the model for each process.")
    p.add_argument(
        "--out",
        default="",
        help="Directory to write chapters into (default: site/assets/chapters/<feed>/<episode>.chapters.json).",
    )
    p.add_argument("--adjacent", action="store_true", help="Write chapters next to the transcript as *.chapters.json.")
    p.add_argument("--force", action="store_true", help="Rewrite even if the chapters file looks up-to-date.")
    p.add_argument("--print", action="store_true", help="Print the resulting chapter list.")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    if str(args.llm_url or "").strip():
        import os

        os.environ["VOD_ANSWER_LLM_URL"] = str(args.llm_url).strip()
    _cache_dir, transcripts_root, db_path = resolve_paths(args)

    t_arg = str(args.transcript or "").strip()
    transcript_rel = ""
    target = None
    if not t_arg:
        if bool(args.print):
            raise SystemExit("--print requires --transcript")
    else:
        p = Path(t_arg)
        if not p.is_absolute():
            p = transcripts_root / t_arg
        p = p.resolve()
        if not p.exists():
            raise SystemExit(f"Transcript not found: {p}")
        try:
            transcript_rel = str(p.relative_to(Path(transcripts_root).resolve())).replace("\\", "/")
        except Exception:
            raise SystemExit(f"Transcript is not under transcripts root: {p}")

    out_dir = None if bool(args.adjacent) else (Path(args.out).resolve() if args.out else (transcripts_root.parent / "chapters"))

    if transcript_rel:
        p = (transcripts_root / transcript_rel).resolve()
        target = _chapters_output_path(transcript_path=p, out_dir=out_dir, adjacent=bool(args.adjacent))
        if target and not args.force and target.exists() and not _chapters_needs_update(target, mode=str(args.mode or "semantic")):
            print(f"[answer-engine] chapters up-to-date: {target}", flush=True)
            return

    write_chapters_from_analysis(
        db_path=db_path,
        transcripts_root=transcripts_root,
        chapters_out=out_dir,
        chapters_adjacent=bool(args.adjacent),
        mode=str(args.mode or "semantic"),
        force=bool(args.force),
        limit_files=1 if transcript_rel else 0,
        transcript_rel=(str(Path("site/assets/transcripts") / transcript_rel).replace("\\", "/") if transcript_rel else ""),
        quiet=False,
    )

    if args.print and target and target.exists():
        import json

        raw = json.loads(target.read_text(encoding="utf-8", errors="replace"))
        chs = raw.get("chapters") if isinstance(raw, dict) else None
        for c in chs or []:
            t = float(c.get("startTime") or 0.0)
            title = str(c.get("title") or "")
            kind = str(c.get("kind") or "")
            extra = f" [{kind}]" if kind else ""
            print(f"{t:8.1f}{extra}  {title}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[answer-engine] interrupted (Ctrl+C).", flush=True)
        raise SystemExit(130)
