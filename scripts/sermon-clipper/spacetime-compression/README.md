# Spacetime Compression

This path is now the compatibility location for the spacetime-compression feature of `scripts/markdown-video-editor/`.

Preferred home:

```bash
bash scripts/markdown-video-editor/mve.sh analyze-spacetime --input in/source.mp4 --output out/source.edit.md
bash scripts/markdown-video-editor/mve.sh apply --plan out/source.edit.md --output out/source.out.mp4
```

The feature itself is still the same non-destructive gap-compression workflow:

1. Analyze the source media and write an editable markdown plan.
2. Apply that plan to render a compressed output.

The first implementation uses ffmpeg's `silencedetect` filter. The markdown plan is designed so future transcript- or utterance-driven guides can produce the same `## action` sections and reuse the same apply step.

## What it supports now

- `trim_edges` on or off
- `compress_gaps` on or off
- optional video scene markers for early visual-boundary review
- optional audio scene markers for early recording/program-change review
- variable edge padding via `--edge-pad-sec`
- variable preserved interior pause via `--interior-gap-sec`
- editable action sidecar in markdown

## Quick start

```bash
python scripts/markdown-video-editor/analyze_spacetime_plan.py \
  --input in/sermon.mp4 \
  --output out/sermon.edit.md \
  --threshold-db -35 \
  --min-silence-sec 0.35 \
  --detect-video-scenes \
  --detect-audio-scenes \
  --edge-pad-sec 0.08 \
  --interior-gap-sec 0.05

python scripts/markdown-video-editor/apply_edit_plan.py \
  --plan out/sermon.edit.md \
  --output out/sermon.compressed.mp4
```

Wrapper form:

```bash
bash scripts/markdown-video-editor/mve.sh analyze-spacetime --input in/sermon.mp4 --output out/sermon.edit.md
bash scripts/markdown-video-editor/mve.sh apply --plan out/sermon.edit.md --output out/sermon.compressed.mp4
```

## Analyze flags

- `--threshold-db`: silence threshold passed to `silencedetect`
- `--min-silence-sec`: minimum silence duration to detect
- `--trim-edges` / `--keep-edges`
- `--compress-gaps` / `--keep-gaps`
- `--edge-pad-sec`: how much silence to keep around the outer edges when trimming
- `--interior-gap-sec`: how much of each interior silent gap to preserve after compression
- `--detect-video-scenes`: add `## marker` sections from ffmpeg scene-score changes
- `--video-scene-threshold`: visual scene sensitivity
- `--detect-audio-scenes`: add `## marker` sections from abrupt audio RMS changes
- `--audio-scene-window-sec`: analysis window for audio change detection
- `--audio-scene-threshold-db`: minimum RMS delta for an audio marker

## Plan format

```markdown
# Edit Plan: sermon.mp4

## metadata
source_path: /abs/path/to/sermon.mp4
analysis_method: silencedetect
trim_edges: true
compress_gaps: true
threshold_db: -35.0
min_silence_sec: 0.35
edge_pad_sec: 0.08
interior_gap_sec: 0.05

## summary
Detected 12 silent regions and kept 13 audible ranges.

## action
kind: keep
source_start_sec: 0.080
source_end_sec: 4.912
output_start_sec: 0.000
output_end_sec: 4.832
duration_sec: 4.832
reason: audible_region

## action
kind: cut
source_start_sec: 4.912
source_end_sec: 5.687
duration_sec: 0.775
reason: removed_gap

## marker
kind: boundary
source_sec: 123.400
detector: audio_change
score: 11.800
score_unit: delta_db
reason: audio_program_change
```

`apply_edit_plan.py` trusts the `keep` actions in the file, so you can tune ranges manually before rendering. `## marker` sections are advisory and are there to help you notice likely segment transitions, ad breaks, or recording changes before you edit the actions.

## Notes

- This currently expects local media files.
- The source file is never edited in place.
- The apply step writes an ffmpeg filter script into its scratch directory so the generated edit graph stays inspectable.
