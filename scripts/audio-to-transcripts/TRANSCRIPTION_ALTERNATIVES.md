# Transcription alternatives to WhisperX

Quick reference for faster/local alternatives that support VTT/SRT timestamps.

## Parakeet TDT (NVIDIA) — ✅ timestamps, fastest

- **Full NeMo**: Word-level timestamps, `timestamps=True` in transcribe. Production example: [gist](https://gist.github.com/lokafinnsw/95727707f542a64efc18040aefe47751) (Parakeet v3 + diarization → VTT/SRT).
- **nano-parakeet**: Lightweight (`pip install nano-parakeet`), ~5 deps, but **no timestamps**.
- **parakeet-stream**: Optional word-level timestamps.
- Speed: ~60 min audio in 1 sec (0.6B), ~80× realtime on RTX 4000.
- Catch: NeMo has ~180 deps, slower cold start.

## Moonshine — ✅ phrase-level timestamps

- `TranscriptLine` has `start_time` and `duration` → can build VTT (phrase-level, not word-level).
- `pip install moonshine-voice`
- Better WER than Whisper Large v3 with smaller models (245M params).
- **Catch**: Optimized for **live streaming**, not batch. Their README: *"if you're working with GPUs in the cloud on data in bulk where throughput is most important then Whisper (or Nvidia alternatives like Parakeet) offer advantages like batch processing"*.
- Speaker diarization "has room for improvement".
- English-focused (language-specific models for others).

## Drax (aiOla) — ❌ no timestamps

- Source sets `no_timestamps=True`; returns text only.
- Not suitable for VTT without forced alignment.
- License: CC-BY-NC (non-commercial).

## Recommendation for batch sermon → VTT

- **Parakeet TDT** (NeMo or parakeet-stream) for max throughput + word-level timestamps.
- **Moonshine** if you want lighter deps and phrase-level VTT is acceptable; may be slower for batch.
