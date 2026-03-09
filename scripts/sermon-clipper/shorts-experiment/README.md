# Shorts Experiment

Vertical shorts (`1080x1920`) from church feed clips. This uses the same answer-engine index and shared content cache as the long-form clipper, but is tuned for 2-4 clips of roughly 10-18 seconds each.

## What is implemented

1. `search_shorts.py` returns only shorts-friendly clips and, by default, only keeps clips that already have a transcript and a video enclosure.
2. `write_short_script.py` writes a usable first-draft short with intro, clip context, and outro instead of leaving empty placeholders.
3. `render_short.py` builds a split-screen vertical video with a speaker panel, a context panel, subtitles, and preserved audio.
4. `clean` removes the old `work*` folders, concat manifests, and internal scratch state.

## Defaults that matter

- Minimum clips: 2
- Default clip length: 10-18 seconds
- Default total runtime target: under 55 seconds
- Shared content cache: `cache/<env>/sermon-clipper/content/`
- Scratch work dir: auto-created under `scripts/sermon-clipper/.work/` and removed after successful render unless `--keep-work` is passed

## Quick start

```powershell
$py = scripts/answer-engine/.venv/Scripts/python.exe

$py scripts/sermon-clipper/shorts-experiment/search_shorts.py --theme forgiveness --output out/shorts/forgiveness-clips.json
$py scripts/sermon-clipper/shorts-experiment/write_short_script.py --theme forgiveness --clips out/shorts/forgiveness-clips.json --output out/shorts/forgiveness.md
python scripts/sermon-clipper/shorts-experiment/render_short.py --script out/shorts/forgiveness.md --output out/shorts/forgiveness.mp4
python scripts/sermon-clipper/cleanup_outputs.py --path out/shorts
```

Or use the wrapper:

```powershell
short.ps1 search --theme forgiveness --output out/shorts/forgiveness-clips.json
short.ps1 write --theme forgiveness --clips out/shorts/forgiveness-clips.json --output out/shorts/forgiveness.md
short.ps1 render --script out/shorts/forgiveness.md --output out/shorts/forgiveness.mp4
short.ps1 clean --path out/shorts
```

## Script format

```markdown
# Short: Forgiveness

## metadata
theme: forgiveness
clips: 3

## intro
One short hook sentence.

## clip
feed: ...
episode: ...
start_sec: ...
end_sec: ...
quote: "..."
episode_title: ...
feed_title: ...
context: One or two sentences that explain why this clip matters.
decorators: optional keywords for the context panel

## outro
One short closing line.
```

## Render notes

- The context panel is rendered as an image, so it does not depend on ffmpeg font configuration.
- `--no-download` uses only the shared content cache.
- `--trim-silence` trims leading and trailing silence from each clip.
- `--context-bottom` flips the speaker/context stack.
- `--min-clips` prevents accidental single-clip or broken outputs.
