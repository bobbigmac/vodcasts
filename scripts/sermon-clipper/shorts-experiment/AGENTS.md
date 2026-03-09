# Shorts Experiment — Agent Guide

Vertical, 2–4 clip shorts from church feed content. Same index and tools as the main sermon-clipper, but tuned for **10–25 second clips**, **vertical layout**, **split-screen** (speaker + context panel), and **fast iteration**.

## Goals

- **Broadcast understanding** — Share perspectives in bite-sized form
- **Extremely tight editing** — Every second matters; cut filler, keep the point
- **Contextualize** — The context panel explains *why* this clip matters
- **Explore** — Overlap speakers, try layouts, add decorators, experiment with transformations

## Risks & Opportunities

### Risks

- **Shallow clips** — 10–20s segments may lack enough substance; search can surface generic or incomplete thoughts
- **Misrepresentation** — Tight cuts can distort intent; avoid editing that changes meaning
- **Filler overload** — Short segments often have "um," "you know," "like"; word-level trimming helps but adds complexity
- **Context drift** — The context panel must accurately reflect what the speaker said

### Opportunities

- **Fast iteration** — Renders are quick; try many ideas, layouts, and themes
- **Format experiments** — Overlap two speakers, alternate layouts, try different decorators (emojis, keywords, related ideas)
- **Word-level control** — Optional WhisperX/aeneas step: per-word timestamps → cut filler, splice strong phrases
- **Discovery** — Shorts can surface themes that warrant full-length videos

## Pipeline

1. **search_shorts** — Query index for 10–18s clips (2–4, one per feed, ~50s total). Single-clip shorts are never acceptable.
2. **write_short_script** — Theme, clips, context text per clip, optional word-trim hints
3. **render_short** — Vertical 1080×1920, split screen, subtitles, context panel

## Script Format (Markdown)

```markdown
# Short: [Theme in a few words]

## metadata
theme: forgiveness
clips: 3

## intro
[1 sentence max. Hook.]

## clip
feed: ...
episode: ...
start_sec: ...
end_sec: ...
quote: "..."
context: [1–2 sentences. What is the pastor saying? Why does it matter?]
decorators: [Optional: keywords, emojis, related ideas for onscreen flair]

## clip
...

## outro
[1 sentence. CTA or punchline.]
```

## Query Tips for Shorts

- **Punchy phrases** — "forgiveness isn't weakness", "pray when you don't feel it"
- **Questions** — "what do I do when I can't forgive?"
- **Avoid** — Overly broad terms that yield long, rambling segments

## Trim silence

Use `--trim-silence` on render to remove leading/trailing silence from clips (ffmpeg silenceremove). For tighter cuts after trimming, subtitle timings come from the original transcript; aeneas on extracted clips can re-align if needed.

## Optional: Word-Level Trimming (aeneas)

If you have WhisperX or aeneas output with per-word timestamps:

- Identify filler spans (um, uh, you know, like, repeated words)
- Produce `trim_ranges`: e.g. `[[start1, end1], [start2, end2]]` — keep these, drop the rest
- Enables "5 sec from early sentence + 12 sec from later" without the cruft

The LLM can optionally emit trim hints in the script; render_short can apply them when word-level data exists.

## TODO (later)

- **OpenCV face smart-crop** — Detect faces and smart-crop to speaker instead of fixed half-and-half; enables variable layouts (speaker inset, picture-in-picture, etc.)

## Exploration Ideas

- **Overlap speakers** — Two pastors on the same theme, intercut or split-screen
- **Layout variants** — Speaker top vs bottom; context as scrolling text vs static
- **Decorators** — Keywords, emojis, "Related: X" — keep it tasteful
- **Transformation steps** — Speed up/slow down for emphasis; subtle zoom on key words
- **Series** — "3 pastors on X" as a recurring format

## Files

- `search_shorts.py` — Favors 10–25s clips, limit 4, one per feed
- `write_short_script.py` — Script from clips + context
- `render_short.py` — Vertical 1080×1920, split screen (speaker + context), subtitles
- `short.ps1` — Entrypoint: `short.ps1 search|write|render`
- `_lib.py` — Imports from parent sermon-clipper

## Quick workflow

```powershell
cd scripts/sermon-clipper/shorts-experiment
short.ps1 search --theme "forgiveness" --output out/clips.json
# LLM: edit script, fill context + decorators per clip
short.ps1 write --theme forgiveness --clips out/clips.json --output out/short.md
short.ps1 render --script out/short.md --output out/short.mp4
```
