#!/usr/bin/env python3
"""Benchmark transcript backends on a short clip from a cached episode."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from jiwer import cer, wer

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from scripts.feed_manifest import parse_feed_for_manifest
from scripts.shared import VODCASTS_ROOT
from scripts.sources import Source, load_sources_config
from transcription_backends import get_backend, list_backends
from transcription_backends.subtitle_utils import estimate_audio_duration_seconds, srt_to_vtt


def _canon_env(value: str) -> str:
    value = (value or "").strip()
    if value in {"prod", "main", "full"}:
        return "complete"
    return value or "dev"


def _active_env() -> str:
    env = _canon_env(str(os.environ.get("VOD_ENV") or ""))
    if env:
        return env
    state_file = VODCASTS_ROOT / ".vodcasts-env"
    if state_file.exists():
        return _canon_env(state_file.read_text(encoding="utf-8", errors="replace").strip())
    return "dev"


def _looks_like_direct_media_url(url: str) -> bool:
    lowered = str(url or "").strip().lower()
    if not lowered:
        return False
    if ".m3u8" in lowered:
        return True
    return any(ext in lowered for ext in (".mp3", ".m4a", ".wav", ".mp4", ".m4v", ".mov", ".webm"))


def _resolve_media_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw or not raw.lower().startswith(("http://", "https://")):
        return raw
    if _looks_like_direct_media_url(raw):
        return raw
    result = subprocess.run(
        ["yt-dlp", "--no-warnings", "--no-playlist", "-g", raw],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if line.lower().startswith(("http://", "https://")):
            return line
    return raw


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _extract_text_from_vtt(vtt_text: str) -> str:
    lines: list[str] = []
    for raw in (vtt_text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.upper().startswith("WEBVTT"):
            continue
        if line.isdigit():
            continue
        if "-->" in line:
            continue
        line = re.sub(r"<[^>]+>", "", line).strip()
        if line:
            lines.append(line)
    return " ".join(lines).strip()


def _normalize_metric_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"[^a-zA-Z0-9'\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def _extract_sample_cues(vtt_text: str, *, limit: int = 2) -> list[dict[str, str]]:
    cues: list[dict[str, str]] = []
    current_time = ""
    current_text: list[str] = []

    def flush() -> None:
        nonlocal current_time, current_text
        text = " ".join(part.strip() for part in current_text if part.strip()).strip()
        if current_time and text and len(cues) < limit:
            cues.append({"time": current_time, "text": text})
        current_time = ""
        current_text = []

    for raw in (vtt_text or "").splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        if line.upper().startswith("WEBVTT") or line.isdigit():
            continue
        if "-->" in line:
            flush()
            current_time = line
            continue
        current_text.append(line)
    flush()
    return cues


def _find_source(sources: list[Source], source_id: str) -> Source:
    for source in sources:
        if source.id == source_id:
            return source
    raise ValueError(f"source not found: {source_id}")


def _find_episode(feed_xml_path: Path, *, source_id: str, source_title: str, episode_slug: str) -> dict[str, Any]:
    xml_text = feed_xml_path.read_text(encoding="utf-8", errors="replace")
    _features, _channel_title, episodes, _image = parse_feed_for_manifest(xml_text, source_id=source_id, source_title=source_title)
    for episode in episodes or []:
        if isinstance(episode, dict) and str(episode.get("slug") or "").strip() == episode_slug:
            return episode
    raise ValueError(f"episode not found: {source_id}/{episode_slug}")


def _detect_reference_vtt(source_id: str, episode_slug: str) -> Path | None:
    candidate = VODCASTS_ROOT / "site" / "assets" / "transcripts" / source_id / f"{episode_slug}.vtt"
    return candidate if candidate.exists() else None


def _make_backend(name: str, args: argparse.Namespace) -> Any:
    if name == "whisperx":
        whisperx_cmd = args.whisperx
        if whisperx_cmd == "whisperx":
            venv_cmd = _SCRIPT_DIR / ".venv" / "Scripts" / "whisperx.exe"
            if venv_cmd.exists():
                whisperx_cmd = str(venv_cmd)
        return get_backend(
            "whisperx",
            worker_url=str(args.whisperx_worker_url or ""),
            whisperx_cmd=str(whisperx_cmd),
            model=str(args.whisperx_model),
            device=str(args.device),
            compute_type=str(args.whisperx_compute_type),
            extra_args=str(args.whisperx_extra_args or "--vad_method silero"),
        )
    if name == "parakeet":
        return get_backend("parakeet", device=str(args.device), config=str(args.parakeet_config), model_name=str(args.parakeet_model))
    if name == "moonshine":
        return get_backend("moonshine", language=str(args.language))
    raise ValueError(f"unsupported backend: {name}")


@dataclass
class BackendMetrics:
    backend: str
    runtime_seconds: float
    audio_seconds: float
    realtime_factor: float
    transcript_words: int
    transcript_chars: int
    wer_vs_whisperx: float | None = None
    cer_vs_whisperx: float | None = None
    wer_vs_reference: float | None = None
    cer_vs_reference: float | None = None
    samples: list[dict[str, str]] | None = None


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark whisperx/parakeet/moonshine on a short cached episode clip.")
    parser.add_argument("--source-id", required=True, help="Feed/source id from feeds/*.md")
    parser.add_argument("--episode-slug", required=True, help="Episode slug from cached feed manifest")
    parser.add_argument("--env", default="", help="Feed/cache env name. Defaults to active env.")
    parser.add_argument("--feeds", default="", help="Path to feeds md file.")
    parser.add_argument("--cache", default="", help="Path to cache dir.")
    parser.add_argument("--language", default="en", help="Language code.")
    parser.add_argument("--clip-start", type=int, default=0, help="Start offset in seconds.")
    parser.add_argument("--clip-seconds", type=int, default=300, help="Clip length in seconds.")
    parser.add_argument("--ffmpeg", default="ffmpeg", help="ffmpeg executable.")
    parser.add_argument("--device", default="cuda", help="Backend device where applicable.")
    parser.add_argument("--backends", nargs="+", default=list_backends(), choices=list_backends(), help="Backends to run in order.")
    parser.add_argument("--out-dir", default="", help="Output directory. Defaults to out/transcription-backend-benchmarks/<source>/<episode>.")
    parser.add_argument("--whisperx-worker-url", default="", help="Optional whisperx worker URL.")
    parser.add_argument("--whisperx", default="whisperx", help="whisperx executable.")
    parser.add_argument("--whisperx-model", default="medium", help="WhisperX model name.")
    parser.add_argument("--whisperx-compute-type", default="float16", help="WhisperX compute type.")
    parser.add_argument("--whisperx-extra-args", default="--vad_method silero", help="Extra whisperx args.")
    parser.add_argument("--parakeet-model", default="nvidia/parakeet-tdt-0.6b-v3", help="Parakeet model name.")
    parser.add_argument("--parakeet-config", default="balanced", help="Parakeet audio config preset.")
    args = parser.parse_args()

    env_name = _canon_env(args.env or _active_env())
    feeds_path = Path(args.feeds) if args.feeds else (VODCASTS_ROOT / "feeds" / f"{env_name}.md")
    cache_dir = Path(args.cache) if args.cache else (VODCASTS_ROOT / "cache" / env_name)
    feed_xml_path = cache_dir / "feeds" / f"{args.source_id}.xml"
    if not feed_xml_path.exists():
        raise SystemExit(f"missing cached feed: {feed_xml_path}")

    sources_config = load_sources_config(feeds_path)
    source = _find_source(sources_config.sources, args.source_id)
    episode = _find_episode(feed_xml_path, source_id=source.id, source_title=source.title, episode_slug=args.episode_slug)
    media = episode.get("media") or {}
    media_url = str(media.get("url") or "").strip()
    if not media_url:
        raise SystemExit(f"episode has no media url: {args.source_id}/{args.episode_slug}")

    out_dir = Path(args.out_dir) if args.out_dir else (VODCASTS_ROOT / "out" / "transcription-backend-benchmarks" / args.source_id / args.episode_slug)
    out_dir.mkdir(parents=True, exist_ok=True)

    resolved_media_url = _resolve_media_url(media_url)
    clip_wav = out_dir / "clip.wav"
    clip_mp3 = out_dir / "clip.mp3"
    ffmpeg_base = [
        args.ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        str(max(0, int(args.clip_start))),
        "-i",
        resolved_media_url,
        "-t",
        str(max(1, int(args.clip_seconds))),
    ]
    _run(ffmpeg_base + ["-vn", "-ac", "1", "-ar", "16000", str(clip_wav)])
    _run(ffmpeg_base + ["-vn", "-acodec", "libmp3lame", "-b:a", "96k", str(clip_mp3)])

    audio_seconds = estimate_audio_duration_seconds(clip_wav)
    reference_vtt_path = _detect_reference_vtt(args.source_id, args.episode_slug)
    reference_text = ""
    if reference_vtt_path:
        reference_text = _normalize_metric_text(reference_vtt_path.read_text(encoding="utf-8", errors="replace"))

    summary: dict[str, Any] = {
        "source_id": args.source_id,
        "source_title": source.title,
        "episode_slug": args.episode_slug,
        "episode_title": str(episode.get("title") or ""),
        "clip_start_seconds": int(args.clip_start),
        "clip_seconds_requested": int(args.clip_seconds),
        "clip_seconds_actual": audio_seconds,
        "media_url": media_url,
        "resolved_media_url": resolved_media_url,
        "reference_vtt": str(reference_vtt_path) if reference_vtt_path else "",
        "backends": [],
    }

    whisperx_text = ""
    metrics: list[BackendMetrics] = []

    for backend_name in args.backends:
        backend = _make_backend(backend_name, args)
        started = time.perf_counter()
        srt_text, vtt_text = backend.transcribe(clip_wav, args.language)
        runtime_seconds = time.perf_counter() - started
        vtt_text = vtt_text or srt_to_vtt(srt_text)

        backend_dir = out_dir / backend_name
        backend_dir.mkdir(parents=True, exist_ok=True)
        _write_text(backend_dir / "transcript.srt", srt_text)
        _write_text(backend_dir / "transcript.vtt", vtt_text)

        plain_text = _extract_text_from_vtt(vtt_text)
        normalized_plain_text = _normalize_metric_text(plain_text)
        if backend_name == "whisperx":
            whisperx_text = normalized_plain_text

        metric = BackendMetrics(
            backend=backend_name,
            runtime_seconds=runtime_seconds,
            audio_seconds=audio_seconds,
            realtime_factor=(runtime_seconds / audio_seconds) if audio_seconds > 0 else 0.0,
            transcript_words=len(plain_text.split()),
            transcript_chars=len(plain_text),
            samples=_extract_sample_cues(vtt_text),
        )
        metrics.append(metric)

        _write_text(
            backend_dir / "metrics.json",
            json.dumps(
                {
                    **asdict(metric),
                    "normalized_text": normalized_plain_text,
                },
                indent=2,
            ),
        )

    for metric in metrics:
        backend_vtt = out_dir / metric.backend / "transcript.vtt"
        normalized_text = _normalize_metric_text(_extract_text_from_vtt(backend_vtt.read_text(encoding="utf-8", errors="replace")))
        if whisperx_text:
            metric.wer_vs_whisperx = float(wer(whisperx_text, normalized_text))
            metric.cer_vs_whisperx = float(cer(whisperx_text, normalized_text))
        if reference_text:
            metric.wer_vs_reference = float(wer(reference_text, normalized_text))
            metric.cer_vs_reference = float(cer(reference_text, normalized_text))

    summary["backends"] = [asdict(metric) for metric in metrics]
    _write_text(out_dir / "run.json", json.dumps(summary, indent=2))

    lines: list[str] = [
        f"# Transcription Backend Benchmark: {args.source_id}/{args.episode_slug}",
        "",
        f"- Episode: {summary['episode_title'] or args.episode_slug}",
        f"- Clip start: {int(args.clip_start)}s",
        f"- Clip length requested: {int(args.clip_seconds)}s",
        f"- Clip length actual: {audio_seconds:.2f}s",
        f"- Reference transcript: `{reference_vtt_path}`" if reference_vtt_path else "- Reference transcript: none",
        "",
        "## Metrics",
        "",
        "| Backend | Runtime (s) | RT factor | Words | WER vs WhisperX | CER vs WhisperX | WER vs reference | CER vs reference |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for metric in metrics:
        lines.append(
            "| "
            + " | ".join(
                [
                    metric.backend,
                    f"{metric.runtime_seconds:.2f}",
                    f"{metric.realtime_factor:.3f}",
                    str(metric.transcript_words),
                    f"{metric.wer_vs_whisperx:.4f}" if metric.wer_vs_whisperx is not None else "",
                    f"{metric.cer_vs_whisperx:.4f}" if metric.cer_vs_whisperx is not None else "",
                    f"{metric.wer_vs_reference:.4f}" if metric.wer_vs_reference is not None else "",
                    f"{metric.cer_vs_reference:.4f}" if metric.cer_vs_reference is not None else "",
                ]
            )
            + " |"
        )

    lines.extend(["", "## Sample Cues", ""])
    for metric in metrics:
        lines.append(f"### {metric.backend}")
        lines.append("")
        if not metric.samples:
            lines.append("_No cues captured._")
            lines.append("")
            continue
        for sample in metric.samples:
            lines.append(f"- `{sample['time']}` {sample['text']}")
        lines.append("")

    _write_text(out_dir / "README.md", "\n".join(lines).rstrip() + "\n")
    print(str(out_dir))


if __name__ == "__main__":
    main()
