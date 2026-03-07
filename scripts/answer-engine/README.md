# Answer Engine (transcript search + auto-chapters)

This folder contains a small, local-first helper for searching our subtitle/transcript dataset (WebVTT/SRT) in `site/assets/transcripts/` and surfacing timestamped "answer-ish" segments for a free-text question.

The search/index path is intentionally not an LLM. The optional chapter-refinement path can use a small local instruct model for better chapter boundaries, titles, kinds, and tags.

## What it builds

- A SQLite full-text index of transcript segments (default output under `cache/<env>/answer-engine/`).
- Auto-chapters JSON per transcript.

## Quick start

1. Pick your active env:

- `yarn use dev|church|tech|complete`

2. Ensure the Python deps are installed in the local venv:

- macOS/Linux:
  - `bash scripts/answer-engine/ae.sh analyze --help`
- Windows PowerShell:
  - `powershell -ExecutionPolicy Bypass -File scripts/answer-engine/ae.ps1 analyze --help`

3. Build the derived caches:

- Parse transcripts into cached segments:
  - `bash scripts/answer-engine/ae.sh analyze`
- Rebuild the FTS answer index from cached segments:
  - `bash scripts/answer-engine/ae.sh index`

4. Query for candidate answers:

- `bash scripts/answer-engine/ae.sh query search --q "I struggle to forgive someone I trusted" --limit 12`
- `bash scripts/answer-engine/ae.sh query search --q "How can I handle myself better in stressful situations?" --json | jq`

## Auto-chapters

Generate chapter JSON files from analyzed transcripts:

- Parse transcripts first:
  - `bash scripts/answer-engine/ae.sh analyze`
- Write chapters into `site/assets/chapters/`:
  - `bash scripts/answer-engine/ae.sh chapters`
- Write chapters adjacent to transcripts as `*.chapters.json`:
  - `bash scripts/answer-engine/ae.sh chapters --adjacent`
- Rewrite existing chapters after algorithm tweaks:
  - `bash scripts/answer-engine/ae.sh chapters --force`

When present, the client fetches chapters from `assets/chapters/<feed>/<episode>.chapters.json` (and also `*.chapters.json` next to a local transcript) when the episode has no feed-provided chapters.

### Fast spot-check

For dev iteration, analyze and generate chapters for one transcript:

- `bash scripts/answer-engine/ae.sh analyze --transcript <feed>/<episode>.vtt`
- `bash scripts/answer-engine/ae.sh analyze --transcript <feed>/<episode>.vtt --transcript <feed>/<episode-2>.vtt`
- `bash scripts/answer-engine/ae.sh chapters --transcript <feed>/<episode>.vtt --force --print`
- `bash scripts/answer-engine/ae.sh chapters --transcript <feed>/<episode>.vtt --llm-url http://127.0.0.1:8765 --force --print`

### Chapter modes

- `hybrid` (default): semantic candidates plus local LLM refinement.
- `semantic`: semantic candidates only, no LLM pass.

The semantic path uses `sentence-transformers` + `keybert`. `ae.sh` / `ae.ps1` ensure a CUDA-capable torch wheel (`cu128`) is installed when CUDA is available, matching the audio-to-transcripts tooling.

### Chapter kinds

The chapterer now aims for human-facing section labels instead of only generic `message` / `topic`. Current kinds include:

- `welcome`, `intro`, `worship`, `prayer`, `scripture`, `message`, `teaching`, `application`
- `illustration`, `story`, `testimony`, `conversation`, `interview`, `q_and_a`
- `response`, `invitation`, `communion`, `announcements`, `giving`, `ad`, `transition`, `benediction`, `outro`

Not every feed will use every kind. The point is to describe the section the way a listener would, not the way a low-level segment classifier would.

### Persistent LLM server

If you are processing multiple files, keep the chapter LLM warm in one process instead of reloading it in every `chapters` run.

Start the server once:

- macOS/Linux:
  - `bash scripts/answer-engine/ae.sh serve-llm --warmup`
- Windows PowerShell:
  - `powershell -ExecutionPolicy Bypass -File scripts/answer-engine/ae.ps1 serve-llm --warmup`

Then point chapter runs at it:

- `bash scripts/answer-engine/ae.sh chapters --llm-url http://127.0.0.1:8765 --transcript <feed>/<episode>.vtt --force --print`
- `powershell -ExecutionPolicy Bypass -File scripts/answer-engine/ae.ps1 chapters --llm-url http://127.0.0.1:8765 --transcript <feed>/<episode>.vtt --force --print`

Defaults:

- Model: `Qwen/Qwen2.5-1.5B-Instruct`
- Device: `cuda` when available, otherwise `cpu`

Useful env overrides:

- `VOD_ANSWER_LLM_MODEL`
- `VOD_ANSWER_LLM_DEVICE`
- `VOD_ANSWER_LLM_MAX_INPUT_CHARS`
- `VOD_ANSWER_LLM_HTTP_TIMEOUT_SEC`

### Dependencies

Installed automatically by `ae.sh` / `ae.ps1` into `scripts/answer-engine/.venv/`:

- `scripts/answer-engine/requirements.txt`

## Notes

- Indexing is based on `site/assets/transcripts/**.vtt|.srt`.
- The shared cached artifact is analyzed transcript segments in SQLite; search indexing and chapter writing are separate downstream steps.
- Episode metadata is best-effort joined from cached feeds in `cache/<env>/feeds/<slug>.xml` when available.
- Outputs live in `cache/` and are regenerable; they are ignored by git.
