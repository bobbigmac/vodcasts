# Chapter Generation

This folder contains the current standalone chapter-generation tooling for transcript files under `site/assets/transcripts/`.

Unlike Answer Engine, this path does not read the SQLite transcript analysis cache or the FTS index. It parses transcript files directly, segments them locally, and writes chapter JSON files.

## Quick start

1. Ensure the local venv exists:

- macOS/Linux:
  - `bash scripts/chapter-generation/cg.sh chapters --help`
- Windows PowerShell:
  - `powershell -ExecutionPolicy Bypass -File scripts/chapter-generation/cg.ps1 chapters --help`

2. Generate chapters into `site/assets/chapters/`:

- `bash scripts/chapter-generation/cg.sh chapters`

3. Generate chapters for one transcript and print them:

- `bash scripts/chapter-generation/cg.sh chapters --transcript <feed>/<episode>.vtt --force --print`

4. Write chapters next to transcripts:

- `bash scripts/chapter-generation/cg.sh chapters --adjacent`

## Modes

- `hybrid` (default): semantic candidates plus local LLM refinement
- `semantic`: semantic candidates only, no LLM pass

## Persistent LLM server

Start the chapter-only helper once:

- `bash scripts/chapter-generation/cg.sh serve-llm --warmup`

Then point chapter runs at it:

- `bash scripts/chapter-generation/cg.sh chapters --llm-url http://127.0.0.1:8765 --transcript <feed>/<episode>.vtt --force --print`

Useful env overrides:

- `VOD_CHAPTER_LLM`
- `VOD_CHAPTER_LLM_PROVIDER`
- `VOD_CHAPTER_LLM_MODEL`
- `VOD_CHAPTER_OPENAI_MODEL`
- `VOD_CHAPTER_LLM_DEVICE`
- `VOD_CHAPTER_LLM_MAX_INPUT_CHARS`
- `VOD_CHAPTER_LLM_HTTP_TIMEOUT_SEC`

## Notes

- Outputs default to `site/assets/chapters/<feed>/<episode>.chapters.json`.
- Existing chapter quality is intentionally preserved here while the feature is reworked in isolation.
