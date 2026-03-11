# Markdown Video Editor

Standalone markdown-driven video editing tool.

The current feature set is focused on spacetime compression:

1. Analyze a local media file and write a markdown edit plan.
2. Review or edit that plan.
3. Apply the plan to render a new output.

The important distinction is architectural: spacetime compression is one feature inside this tool, not the entire tool. That leaves room for other features, such as reframing or AutoCrop-Vertical, to plug into the same plan-driven workflow later.

## Current commands

```bash
python3 scripts/markdown-video-editor/analyze_spacetime_plan.py --input in/source.mp4 --output out/source.edit.md
python3 scripts/markdown-video-editor/apply_edit_plan.py --plan out/source.edit.md --output out/source.out.mp4
```

Wrapper form:

```bash
bash scripts/markdown-video-editor/mve.sh analyze-spacetime --input in/source.mp4 --output out/source.edit.md
bash scripts/markdown-video-editor/mve.sh apply --plan out/source.edit.md --output out/source.out.mp4
```

## Spacetime compression support

- `trim_edges` on or off
- `compress_gaps` on or off
- optional advisory video-scene markers
- optional advisory audio-change markers

The markdown plan remains the render source of truth.

## Timing and sync note

There is an open timing/sync investigation around silence-boundary choices and transition behavior.

Important constraint:

- the apply step intentionally trims audio and video from the same `keep` ranges
- do not "optimize" this into audio-only silence removal
- do not replace paired trim logic with independent audio/video retiming unless the feature behavior is revalidated

The current design is intentionally conservative because preserving feature semantics is more important than drive-by simplification.
