# Shorts Experiment

Vertical shorts (1080×1920) from church feed clips. Same answer-engine index as sermon-clipper, tuned for 2–4 clips of 10–25 seconds each.

## Requirements (design notes)

- **No single-clip shorts** — Every script must have at least 2–3 clips; prefer more. Never allow single-clip shorts.
- **Tight editing** — Under 50 seconds total is a stretch for pastors. Dial up tight editing: remove short breaths and silences between parts of speech. Use `--trim-silence` on render.
- **Subtitle timings** — If clips are trimmed tighter, subtitle timings may need adjustment. aeneas on extracted clips can re-align with exact timings; don't rely on it exclusively but it's a good option.
- **Audio and subtitles** — Final shorts must have sound and subtitles. Clip audio must not be lost.
- **Shared content cache** — Same as main sermon-clipper; no duplicate source videos.

## Quick start

```powershell
# From repo root; use answer-engine venv
$py = scripts/answer-engine/.venv/Scripts/python.exe

$py scripts/sermon-clipper/shorts-experiment/search_shorts.py --theme forgiveness -o out/short-clips.json
$py scripts/sermon-clipper/shorts-experiment/write_short_script.py --theme forgiveness --clips out/short-clips.json -o out/short.md
# Edit out/short.md: fill context + decorators per clip
$py scripts/sermon-clipper/shorts-experiment/render_short.py --script out/short.md -o out/short.mp4
```

Or from `shorts-experiment/`:

```powershell
short.ps1 search --theme forgiveness --output ../out/clips.json
short.ps1 write --theme forgiveness --clips ../out/clips.json --output ../out/short.md
short.ps1 render --script ../out/short.md --output ../out/short.mp4
```

## Output

- **search_shorts**: JSON with 2–4 clips (10–18s each, ~50s total, one per feed)
- **write_short_script**: Markdown skeleton; LLM fills `context` and `decorators` per clip
- **render_short**: Vertical MP4, split screen (speaker half + context half), subtitles from transcripts

## Options

- `--min-duration` / `--max-duration`: Clip length bounds (default 10–18s for ~50s total)
- `--max-total-duration`: Cap total seconds across all clips (default 55)
- `--trim-silence`: Remove leading/trailing silence from clips
- `--no-subs`: Skip transcript subtitles
- `--context-bottom`: Put context panel on bottom instead of top
- `--intro-duration` / `--outro-duration`: Card length in seconds

See `AGENTS.md` for risks, opportunities, and exploration ideas (WhisperX filler removal, layout variants, etc.).
