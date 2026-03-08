# WhisperX transcript cache (offline, local)

This is a **local-only** workflow for building a transcript/subtitles cache for the vodcasts library.
It is **not wired into** `yarn build`.

## What it does

- Reads cached feeds from `cache/<env>/feeds/<slug>.xml`
- For each episode:
  - If the feed provides `podcast:transcript` links, downloads them (preferred; no generation)
  - Validates that the downloaded payload is *actually* VTT/SRT subtitles with plausible transcript text
  - Otherwise (missing/unusable), generates subtitles using **WhisperX**
- Writes a folder per feed slug:
  - `cache/<env>/transcripts/<feed-slug>/<episode-slug>.vtt`
  - Optionally, a spot-check audio clip (generation only):
    - `cache/<env>/transcripts/<feed-slug>/<episode-slug>.spotcheck.mp3` (first 10 minutes)

## Prereqs (Windows)

- Python 3.10+ (recommended)
- `ffmpeg` on `PATH`
- NVIDIA GPU + CUDA drivers (generation runs **CUDA-only** by default; no CPU fallback)

Note: WhisperX may download model weights the first time you run it. If you want a *strictly offline* run, pre-cache models and set `HF_HUB_OFFLINE=1`.

## Venv (recommended)

```powershell
.\scripts\audio-to-transcripts\setup-venv.ps1
```

This creates `scripts/audio-to-transcripts/.venv/` and installs deps (including CUDA-enabled torch + whisperx).

## Persistent worker

Generation now prefers a local persistent WhisperX worker so the ASR model stays warm across files.
The transcript runner now keeps **up to two generation jobs in flight**, and the worker keeps **two warm WhisperX model slots** so `transcripts:fast` is not stuck at one-file-at-a-time generation.
Normal `run-transcripts-whisperx.ps1 -Execute -GenerateMissing` runs auto-start a private worker for the batch, route per-file requests over `http://127.0.0.1:<port>`, and stop it afterward.

If you want to keep one shared worker running across multiple commands, start it explicitly:

```powershell
.\scripts\audio-to-transcripts\run-transcripts-whisperx.ps1 -ServeWorker -WorkerWarmup
```

Then point transcript runs at it:

```powershell
.\scripts\audio-to-transcripts\run-transcripts-whisperx.ps1 -Execute -GenerateMissing `
  -WhisperxWorkerUrl "http://127.0.0.1:8776"
```

The worker accepts concurrent HTTP requests safely and services them with a fixed two-slot worker pool. The transcript runner also only drives up to two in-flight jobs at a time, so concurrency stays capped at 2.

## One-command run (recommended)

```powershell
yarn transcripts
```

This processes the **currently-selected env** (`yarn use dev|church|tech|complete`), limiting to **church/sermons** sources and **10 episodes per feed** by default (20 for high-value feeds), with periodic MP3 spot-checks enabled.

Other presets:

- `yarn transcripts:fast` (smaller model + int8 compute)
- `yarn transcripts:hq` (large-v3; slowest)

## Dry run (recommended first)

From repo root:

```powershell
.\scripts\audio-to-transcripts\run-transcripts-whisperx.ps1
```

This prints what it *would* download/generate, without writing files.

## Execute (downloads provided transcripts)

```powershell
.\scripts\audio-to-transcripts\run-transcripts-whisperx.ps1 -Execute
```

## Execute + generate missing (WhisperX)

```powershell
.\scripts\audio-to-transcripts\run-transcripts-whisperx.ps1 -Execute -GenerateMissing `
  -WhisperxModel "large-v3" -Language "en"
```

## Notes

- When `-GenerateMissing` is enabled, generation uses `--whisperx-device cuda` and **fails fast** unless you pass `-AllowCpu`.
- Provided `podcast:transcript` links are preferred **only if** they validate as usable VTT/SRT subtitles (non-subtitles payloads like HTML are rejected).
- If you want to test on a tiny sample, pass `-MaxEpisodesPerFeed 3` or set `--max-episodes-total` in the Python CLI.
- Spot-check MP3 sampling is disabled by default. Enable via `-SpotCheckEvery` / `-SpotCheckSeconds`.
- Temp working files use the `Q:` RAM disk (and `-Execute` refuses to run if it can't find it).
- Unless overridden via `-WhisperxExtraArgs`, generation defaults to `--vad_method silero` to avoid pyannote/torchcodec issues.
- Runs are restartable: a previously-written `.vtt` that looks complete is never re-downloaded/regenerated (unless `-Refresh`).
- If `-WhisperxExtraArgs` includes flags the worker path does not support yet, the generator falls back to the old per-file `whisperx` CLI invocation for those runs.

## Housekeeping

- **Sanity failures retry**: Entries in `transcript-sanity-failures.md` may pass after the MM:SS timestamp fix. Remove an entry and re-run to retry.
- **Orphan spotcheck MP3s**: Failed runs can leave `.spotcheck.mp3` files in feed folders without a matching `.vtt`. These are debug artifacts; safe to delete if no companion VTT exists.
- **High-value feeds**: Feeds in `HIGH_VALUE_FEEDS` get 20 episodes (vs default 10). See `transcripts_whisperx.py` for the list.

## Speed vs quality (WhisperX)

WhisperX speed is mostly driven by model size and GPU VRAM/bandwidth.

- Fastest (lower accuracy): `-WhisperxModel small` (or `base`/`tiny`)
- Good default: `-WhisperxModel medium`
- Best accuracy (slowest): `-WhisperxModel large-v3`

Useful tuning knobs (passed through to `whisperx` via `-WhisperxExtraArgs`):

- `--batch_size N` (bigger = faster if VRAM allows)
- `--compute_type int8` (faster, sometimes slightly worse)

## Single-episode test

Dry-run a small sample from a specific cached feed:

```powershell
.\scripts\audio-to-transcripts\run-transcripts-whisperx.ps1 -SourceId "transcripted-ai-video" -MaxEpisodesPerFeed 5
```

Once you spot an `episode_slug` in the output, run just that episode:

```powershell
.\scripts\audio-to-transcripts\run-transcripts-whisperx.ps1 -SourceId "transcripted-ai-video" -EpisodeSlug "<slug>" -Execute -GenerateMissing
```

