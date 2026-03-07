from __future__ import annotations

import argparse
import shlex
from dataclasses import asdict, dataclass
from typing import Any


def _parse_bool(v: str | bool | None) -> bool:
    if isinstance(v, bool):
        return v
    raw = str(v or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {v!r}")


@dataclass(frozen=True)
class WorkerWhisperxOptions:
    batch_size: int | None = None
    chunk_size: int = 30
    vad_method: str = "silero"
    vad_onset: float | None = None
    vad_offset: float | None = None
    no_align: bool = False
    align_model: str = ""
    interpolate_method: str = "nearest"
    return_char_alignments: bool = False
    threads: int = 4
    verbose: bool = False
    print_progress: bool = False
    highlight_words: bool = False
    max_line_count: int | None = None
    max_line_width: int | None = None

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


def parse_worker_extra_args(extra_args: str) -> tuple[WorkerWhisperxOptions, list[str]]:
    tokens = shlex.split((extra_args or "").strip())
    if not tokens:
        tokens = ["--vad_method", "silero"]

    p = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    p.add_argument("--batch_size", type=int, default=None)
    p.add_argument("--chunk_size", type=int, default=30)
    p.add_argument("--vad_method", default="silero")
    p.add_argument("--vad_onset", type=float, default=None)
    p.add_argument("--vad_offset", type=float, default=None)
    p.add_argument("--no_align", action="store_true")
    p.add_argument("--align_model", default="")
    p.add_argument("--interpolate_method", default="nearest")
    p.add_argument("--return_char_alignments", action="store_true")
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--verbose", default="False")
    p.add_argument("--print_progress", action="store_true")
    p.add_argument("--highlight_words", action="store_true")
    p.add_argument("--max_line_count", type=int, default=None)
    p.add_argument("--max_line_width", type=int, default=None)
    p.add_argument("--output_format", default="srt")

    ns, unknown = p.parse_known_args(tokens)
    unsupported = list(unknown)
    output_format = str(getattr(ns, "output_format", "srt") or "srt").strip().lower()
    if output_format not in {"srt", "vtt", "all"}:
        unsupported.extend(["--output_format", output_format])

    opts = WorkerWhisperxOptions(
        batch_size=getattr(ns, "batch_size", None),
        chunk_size=max(1, int(getattr(ns, "chunk_size", 30) or 30)),
        vad_method=str(getattr(ns, "vad_method", "silero") or "silero").strip().lower() or "silero",
        vad_onset=getattr(ns, "vad_onset", None),
        vad_offset=getattr(ns, "vad_offset", None),
        no_align=bool(getattr(ns, "no_align", False)),
        align_model=str(getattr(ns, "align_model", "") or "").strip(),
        interpolate_method=str(getattr(ns, "interpolate_method", "nearest") or "nearest").strip() or "nearest",
        return_char_alignments=bool(getattr(ns, "return_char_alignments", False)),
        threads=max(1, int(getattr(ns, "threads", 4) or 4)),
        verbose=_parse_bool(getattr(ns, "verbose", "False")),
        print_progress=bool(getattr(ns, "print_progress", False)),
        highlight_words=bool(getattr(ns, "highlight_words", False)),
        max_line_count=getattr(ns, "max_line_count", None),
        max_line_width=getattr(ns, "max_line_width", None),
    )
    return opts, unsupported
