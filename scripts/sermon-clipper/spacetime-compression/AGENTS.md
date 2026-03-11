# Spacetime Compression Agent Guide

This path is now a compatibility wrapper over the standalone markdown-video-editor tool.

## Current contract

- Canonical home: `scripts/markdown-video-editor/`
- This folder keeps the old spacetime-compression entrypoints working.
- `analyze_edit_plan.py` forwards to `scripts/markdown-video-editor/analyze_spacetime_plan.py`
- `apply_edit_plan.py` forwards to `scripts/markdown-video-editor/apply_edit_plan.py`

## What the toggles do

- `trim_edges`: remove leading and trailing silence while optionally keeping a small pad.
- `compress_gaps`: remove or shrink interior silent gaps while preserving all detected audible regions.

Both toggles can be on or off independently.

## Plan format

The markdown edit plan is still the source of truth. It contains:

- `## metadata` with source path, thresholds, and toggle state
- `## summary` with a human-readable description of what was found
- repeated `## action` sections with `keep` and `cut` ranges
- optional `## marker` sections for advisory scene/boundary candidates

Human or LLM edits should be made in the `## action` sections or the toggle metadata.

## Workflow

Preferred workflow:

```bash
bash scripts/markdown-video-editor/mve.sh analyze-spacetime --input in/source.mp4 --output out/source.edit.md
bash scripts/markdown-video-editor/mve.sh apply --plan out/source.edit.md --output out/source.compressed.mp4
```

## Quality bar

- Keep the source untouched.
- Make the plan readable enough to edit by hand.
- Prefer deterministic cut logic over hidden heuristics.
- Preserve paired audio/video keep-range behavior unless timing/sync has been explicitly revalidated.

## Sync caution

There is an active timing/sync investigation around silence-boundary decisions.

Do not simplify spacetime compression into:

- audio-only silence trimming
- independent audio and video retiming
- hidden heuristic gap removal that erases the inspectable plan semantics
