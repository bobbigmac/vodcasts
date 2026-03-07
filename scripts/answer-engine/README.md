# Answer Engine (transcript search + auto-chapters)

This folder contains a small, local-first helper for searching our subtitle/transcript dataset (WebVTT/SRT) in `site/assets/transcripts/` and surfacing timestamped “answer-ish” segments for a free-text question (e.g. a Reddit post).

It is intentionally **not** an LLM and does not call any LLM APIs. The goal is to be a fast “tool” an LLM (or a human) can drive: build an index, run different styles of query, then open specific candidates and verify context.

## What it builds

- A SQLite full-text index of transcript **segments** (default output under `cache/<env>/answer-engine/`).
- Auto-chapters JSON per transcript (so the site can load them alongside transcripts).

## Quick start

1) Pick your active env:

- `yarn use dev|church|tech|complete`

2) Ensure the Python deps are installed (PEP 668 means this must be in a venv):

- macOS/Linux (auto-creates `scripts/answer-engine/.venv/`):
  - `bash scripts/answer-engine/ae.sh analyze --help`
- Windows PowerShell:
  - `powershell -ExecutionPolicy Bypass -File scripts/answer-engine/ae.ps1 analyze --help`

3) Build the derived caches:

- Parse transcripts into cached segments:
  - `bash scripts/answer-engine/ae.sh analyze`
- Rebuild the FTS answer index from cached segments:
  - `bash scripts/answer-engine/ae.sh index`

4) Query for candidate answers:

- `bash scripts/answer-engine/ae.sh query search --q "I struggle to forgive someone I trusted" --limit 12`
- `bash scripts/answer-engine/ae.sh query search --q "How can I handle myself better in stressful situations?" --json | jq`

## Auto-chapters

Generate chapter JSON files for transcripts using semantic topic shifts plus representative-sentence titles:

- Parse transcripts first:
  - `bash scripts/answer-engine/ae.sh analyze`
- Write chapters into `site/assets/chapters/` (default):
  - `bash scripts/answer-engine/ae.sh chapters`
- (Alt) Write chapters adjacent to transcripts as `*.chapters.json`:
  - `bash scripts/answer-engine/ae.sh chapters --adjacent`
- Rewrite existing chapters after algorithm tweaks:
  - `bash scripts/answer-engine/ae.sh chapters --force`

When present, the client will attempt to fetch chapters from `assets/chapters/<feed>/<episode>.chapters.json` (and also `*.chapters.json` next to a local transcript) when the episode has no chapters in the feed.

### Fast spot-check (single file)

For dev iteration (avoid re-indexing everything), analyze and generate chapters for one transcript:

- `bash scripts/answer-engine/ae.sh analyze --transcript <feed>/<episode>.vtt`
- `bash scripts/answer-engine/ae.sh analyze --transcript <feed>/<episode>.vtt --transcript <feed>/<episode-2>.vtt`
- `bash scripts/answer-engine/ae.sh chapters --transcript <feed>/<episode>.vtt --force --print`

### Dependencies

Installed automatically by `ae.sh` / `ae.ps1` into `scripts/answer-engine/.venv/`:

- `scripts/answer-engine/requirements.txt`

### Chapter mode

Semantic chapters are the default and only supported mode:

- `bash scripts/answer-engine/ae.sh chapters`

This uses `sentence-transformers` + `keybert` and downloads model weights the first time. `ae.sh` / `ae.ps1` ensure a CUDA-capable torch wheel (`cu128`) is installed when CUDA is available, to match `scripts/audio-to-transcripts/`, but model initialization still falls back to CPU if CUDA cannot be used at runtime.

## Notes

- Indexing is based on `site/assets/transcripts/**.vtt|.srt` (not `cache/<env>/transcripts/`).
- The shared cached artifact is analyzed transcript segments in SQLite; search indexing and chapter writing are separate downstream steps.
- Episode metadata is best-effort joined from cached feeds in `cache/<env>/feeds/<slug>.xml` when available.
- Outputs live in `cache/` and are regenerable; they are ignored by git.
