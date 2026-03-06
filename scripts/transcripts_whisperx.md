# WhisperX transcript cache (offline, local)

This is a **local-only** workflow for building a transcript/subtitles cache for the vodcasts library.
It is **not wired into** `yarn build`.

## What it does

- Reads cached feeds from `cache/<env>/feeds/<slug>.xml`
- For each episode:
  - If the feed provides `podcast:transcript` links, downloads and caches them (when sensible)
  - Otherwise (optional), generates subtitles using **WhisperX** (fully local speech-to-text)
- Writes a folder per feed slug:
  - `cache/<env>/transcripts/<feed-slug>/<episode-slug>.vtt`
  - `cache/<env>/transcripts/<feed-slug>/<episode-slug>.txt` (plain text, good for indexing)
  - `cache/<env>/transcripts/<feed-slug>/<episode-slug>.meta.json`

## Prereqs (Windows)

- Python 3.10+ (recommended)
- `ffmpeg` on `PATH`
- WhisperX installed (example):
  - `pip install whisperx`

Note: WhisperX may download model weights the first time you run it. If you want a *strictly offline* run, pre-cache models and set `HF_HUB_OFFLINE=1`.

## Dry run (recommended first)

From repo root:

```powershell
.\scripts\run-transcripts-whisperx.ps1 -Cache "cache\\dev" -Tag "sermons"
```

This prints what it *would* download/generate, without writing files.

## Execute (downloads provided transcripts)

```powershell
.\scripts\run-transcripts-whisperx.ps1 -Cache "cache\\dev" -Tag "sermons" -Execute
```

## Execute + generate missing (WhisperX)

```powershell
.\scripts\run-transcripts-whisperx.ps1 -Cache "cache\\dev" -Tag "sermons" -Execute -GenerateMissing `
  -WhisperxModel "large-v3" -Language "en"
```

## Notes

- By default, the Python script filters to sources tagged/categorized as `sermons`. Use `-AllSources` to scan everything.
- If you want to test on a tiny sample, pass `-MaxEpisodesPerFeed 3`.

