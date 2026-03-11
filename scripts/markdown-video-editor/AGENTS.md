# Markdown Video Editor Agent Guide

This folder is the standalone home for markdown-driven, non-destructive video editing workflows.

## Current features

- `analyze_spacetime_plan.py` analyzes a source video for spacetime-compression edits and writes a markdown edit plan.
- `apply_edit_plan.py` applies a markdown edit plan and renders a new output without touching the source.

Spacetime compression is one feature of this tool, not the whole tool.

## Design intent

- Keep each feature callable on its own.
- Keep the markdown plan as the source of truth.
- Leave room for other plan-driven features such as reframing or AutoCrop-Vertical integration.
- Preserve paired audio/video keep-range behavior in spacetime compression unless you have explicitly revalidated timing/sync behavior end to end.

## Sync caution

There is an active timing/sync investigation around silence-boundary decisions and downstream transitions.

Do not:

- replace paired trim logic with audio-only silence filters
- collapse the feature into a simpler but behaviorally different gap-removal pass
- remove markers or keep-range metadata that help explain why cuts were made

## Current plan format

- `## metadata`
- `## summary`
- repeated `## action` sections
- optional advisory `## marker` sections

## Wrapper commands

```bash
bash scripts/markdown-video-editor/mve.sh analyze-spacetime --input in/source.mp4 --output out/source.edit.md
bash scripts/markdown-video-editor/mve.sh apply --plan out/source.edit.md --output out/source.out.mp4
```
