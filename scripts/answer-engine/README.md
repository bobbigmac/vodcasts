# Answer Engine (transcript search + auto-chapters)

This folder contains a small, local-first helper for searching our subtitle/transcript dataset (WebVTT/SRT) in `site/assets/transcripts/`, grounding answers to free-text questions, and generating auto-chapters.

The retrieval/index path stays SQLite FTS over analyzed transcript segments. The local LLM layer is used for question understanding and grounded answer review so a free-text question can turn into a few precise timestamped recommendations with summaries and quotes.

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

5. Ask for grounded timestamped answers:

- `bash scripts/answer-engine/ae.sh query answer --q "I struggle to forgive someone I trusted" --answers 3`
- `powershell -ExecutionPolicy Bypass -File scripts/answer-engine/ae.ps1 query answer --q "How can I handle myself better in stressful situations?" --answers 3`
- `bash scripts/answer-engine/ae.sh query answer --llm-url http://127.0.0.1:8765 --q "How do I stop living in fear?" --json | jq`

The `answer` flow:

- asks the local LLM to expand the question into related retrieval intents and topics
- runs several targeted FTS searches against the analyzed transcript segments
- loads transcript context around the strongest hits
- asks the LLM to turn the strongest grounded context into a natural recommendation-style reply plus a literal quote
- returns the best few episode/timestamp matches instead of just raw search hits

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

Not every feed will use every kind. The point is to describe the section the way a listener would, not the way a low-level segment classifier would. The LLM may also propose other short snake_case kinds when a clearer label fits a feed better, for example `news_update`, `panel_discussion`, `conference_talk`, or `kids_story`.

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

The same server can also back `query answer --llm-url http://127.0.0.1:8765 ...`, which avoids reloading the LLM for every answer query.

Defaults:

- Model: `Qwen/Qwen2.5-1.5B-Instruct`
- Device: `cuda` when available, otherwise `cpu`

OpenAI swap-in:

- Set `OPENAI_API_KEY` in `.env` or your shell.
- Set `VOD_ANSWER_LLM_PROVIDER=openai` to route the same helper calls through the OpenAI API instead of the local Transformers model.
- Optional: set `VOD_ANSWER_OPENAI_MODEL` (default: `gpt-4o-mini`).
- Or run the HTTP helper in OpenAI mode: `bash scripts/answer-engine/ae.sh serve-llm --provider openai --openai-model gpt-4o-mini`
- This uses the same query/chapter helper functions with restrained output-token caps and `store: false`.

Useful env overrides:

- `VOD_ANSWER_LLM_PROVIDER`
- `VOD_ANSWER_LLM_MODEL`
- `VOD_ANSWER_OPENAI_MODEL`
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
