#!/usr/bin/env python3
"""Transcribe a single audio file using any backend. Produces SRT/VTT samples."""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Script dir (audio-to-transcripts) must be in path for transcription_backends
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from transcription_backends import get_backend, list_backends
from transcription_backends.subtitle_utils import srt_to_vtt


def _ensure_16k_wav(input_path: Path, ffmpeg_cmd: str = "ffmpeg") -> Path:
    """Convert to 16kHz mono WAV if needed. Returns path to WAV."""
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"input not found: {input_path}")

    # Quick heuristic: .wav might already be 16k mono; we still re-encode for consistency
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = Path(f.name)
    try:
        subprocess.run(
            [
                ffmpeg_cmd,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(input_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                str(wav_path),
            ],
            check=True,
        )
        return wav_path
    except Exception:
        wav_path.unlink(missing_ok=True)
        raise


def main() -> None:
    p = argparse.ArgumentParser(
        description="Transcribe a single audio file using whisperx, parakeet, or moonshine. Outputs SRT/VTT."
    )
    p.add_argument("audio", help="Path to audio file (any format supported by ffmpeg).")
    p.add_argument(
        "--backend",
        default="whisperx",
        choices=list_backends(),
        help="Transcription backend (default: whisperx).",
    )
    p.add_argument("--language", default="en", help="Language code (default: en).")
    p.add_argument("--out-srt", default="", help="Write SRT to this path (default: stdout).")
    p.add_argument("--out-vtt", default="", help="Write VTT to this path.")
    p.add_argument("--ffmpeg", default="ffmpeg", help="ffmpeg executable.")
    # WhisperX-specific
    p.add_argument("--whisperx-worker-url", default="", help="WhisperX worker URL (whisperx backend only).")
    p.add_argument("--whisperx", default="whisperx", help="whisperx executable (whisperx backend only).")
    p.add_argument("--whisperx-model", default="medium", help="WhisperX model (whisperx backend only).")
    p.add_argument("--whisperx-device", default="cuda", help="WhisperX device (whisperx backend only).")
    p.add_argument("--whisperx-compute-type", default="float16", help="WhisperX compute type.")
    p.add_argument("--whisperx-extra-args", default="", help="WhisperX extra args.")
    args = p.parse_args()

    audio_path = Path(args.audio)
    if not audio_path.exists():
        print(f"error: file not found: {audio_path}", file=sys.stderr)
        raise SystemExit(1)

    wav_path: Path | None = None
    try:
        wav_path = _ensure_16k_wav(audio_path, ffmpeg_cmd=args.ffmpeg)

        if args.backend == "whisperx":
            backend = get_backend(
                "whisperx",
                worker_url=args.whisperx_worker_url,
                whisperx_cmd=args.whisperx,
                model=args.whisperx_model,
                device=args.whisperx_device,
                compute_type=args.whisperx_compute_type,
                extra_args=args.whisperx_extra_args or "--vad_method silero",
            )
        elif args.backend == "parakeet":
            backend = get_backend("parakeet", device=args.whisperx_device, config="balanced")
        elif args.backend == "moonshine":
            backend = get_backend("moonshine", language=args.language)
        else:
            backend = get_backend(args.backend)

        srt, vtt = backend.transcribe(wav_path, args.language)
        vtt = vtt or srt_to_vtt(srt)

        if args.out_srt:
            out_srt = Path(args.out_srt)
            out_srt.parent.mkdir(parents=True, exist_ok=True)
            out_srt.write_text(srt, encoding="utf-8")
            print(f"[write] {args.out_srt}")
        else:
            print(srt)

        if args.out_vtt:
            out_vtt = Path(args.out_vtt)
            out_vtt.parent.mkdir(parents=True, exist_ok=True)
            out_vtt.write_text(vtt, encoding="utf-8")
            print(f"[write] {args.out_vtt}")
        elif args.out_srt:
            vtt_path = Path(args.out_srt).with_suffix(".vtt")
            vtt_path.parent.mkdir(parents=True, exist_ok=True)
            vtt_path.write_text(vtt, encoding="utf-8")
            print(f"[write] {vtt_path}")
    finally:
        if wav_path and wav_path.exists():
            wav_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
