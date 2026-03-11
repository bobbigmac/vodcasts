# Sermon Clipper Agent Guide

This folder is the video-production surface for transcript-driven sermon/church source material.

## Scope

Use this folder when the task is:

- find source clips from repo-local transcript/index tooling
- draft a long-form or short-form video render sheet
- render or rerender a video from markdown source of truth
- clean scratch state while preserving the shared content cache

Use `scripts/markdown-video-editor/` for feature-specific edit/manipulation plans such as spacetime compression. The `spacetime-compression/` folder here is compatibility surface only.

## Folder shape

- `search_clips.py`
  Long-form source discovery from answer-engine results.
- `write_script.py`
  Draft long-form markdown render sheets.
- `make_title_cards.py`
  Render title-card PNGs for long-form productions.
- `render_video.py`
  Compose long-form outputs from the markdown sheet plus optional cards/subtitles/overlays.
- `cleanup_outputs.py`
  Remove internal scratch, pycache, output-side `work*` dirs, and stray concat manifests.
- `shorts-experiment/`
  Short-form vertical workflow with its own search/write/render scripts and markdown contract.
- `spacetime-compression/`
  Compatibility wrappers that forward to `scripts/markdown-video-editor/`.
- `_lib.py`
  Shared sermon-clipper helpers: cache/env resolution, transcript extraction, script parsing, shared content-cache paths, etc.

## External dependencies this folder expects

- `scripts/answer-engine/.venv/`
  Used by `search_clips.py`, `write_script.py`, and the shorts search/write tools.
- `ffmpeg` / `ffprobe`
  Required for render, download, clip prep, silence trimming, and media probing.
- `node_modules/remotion` and `@remotion/cli`
  Required for the short-form final composition pass.
- `site/assets/transcripts/`
  Used for clipped subtitle generation when transcripts exist locally.
- `cache/<env>/feeds/`
  Used to resolve enclosure URLs and renderability.
- `scripts/markdown-video-editor/`
  Owns edit-plan-driven manipulation features.

## Caches and scratch

- Query cache: `cache/<env>/sermon-clipper/query-cache/`
- Shared content cache: `cache/<env>/sermon-clipper/content/`
- Internal scratch: `scripts/sermon-clipper/.work/`

Cleanup policy:

- preserve final outputs
- preserve markdown render sheets
- preserve shared content cache unless explicitly asked otherwise
- remove scratch/work artifacts freely once outputs are accepted

## Long-form contract

Canonical flow:

1. `search_clips.py`
2. `write_script.py`
3. `make_title_cards.py`
4. `render_video.py`
5. `cleanup_outputs.py` as needed

Long-form render source of truth is the markdown script consumed by `render_video.py`.

Supported sections:

- `## metadata`
- `## intro`
- `## title_card`
- repeated `## clip`
- repeated `## transition`
- `## outro`

Important fields in each `clip` block:

- `feed`
- `episode`
- `start_sec`
- `end_sec`
- `quote`
- `episode_title`
- `feed_title`

Notes:

- `transition` sections are rendered as title cards
- subtitles are clipped from local `.vtt` / `.srt` files when available
- rendered output is normalized to a consistent MP4 target

## Short-form contract

Canonical flow:

1. `shorts-experiment/search_shorts.py`
2. `shorts-experiment/write_short_script.py`
3. `shorts-experiment/render_short.py`

Short-form render source of truth is the markdown script consumed by `render_short.py`.

Supported sections:

- `## metadata`
- `## intro`
- repeated `## clip`
- `## outro`

Clip-specific fields:

- `feed`
- `episode`
- `start_sec`
- `end_sec`
- `quote`
- `episode_title`
- `feed_title`
- `context`
- `decorators`

Quality rules:

- do not accept under-filled shorts unless the user explicitly asks for that tradeoff
- prefer renderable video sources with local transcripts
- context text should label the idea, not restate the quote
- default short target is 7-10 short thought-bites, not 2-4 long clips

## Edit/manipulation features

Current state:

- sermon-clipper owns long-form and short-form render-sheet workflows
- markdown-video-editor owns edit-plan workflows
- the two are related but not yet unified into one universal sheet format

When asked to apply temporal edits or clip-manipulation features, prefer the canonical scripts in `scripts/markdown-video-editor/`:

- `analyze_spacetime_plan.py`
- `apply_edit_plan.py`

## Operator intent

Assume the user may ask for:

- a long-form video on a topic/question
- a short-form video on a topic/question
- a rerender with different production properties
- a feature pass that manipulates already-selected media

The LLM/operator should be able to:

- query for source material
- draft the markdown control sheet
- render from it
- inspect and revise it
- clean scratch state without deleting the expensive shared source cache
