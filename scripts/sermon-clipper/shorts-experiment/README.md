# Shorts Experiment

Vertical shorts (`1080x1920`) from church feed clips. This uses the same answer-engine index and shared content cache as the long-form clipper, but is tuned for 7-10 short, memorable thought-bites rather than a few long paragraphs.

## What is implemented

1. `search_shorts.py` reranks toward short, single-sentence sermon snippets and defaults to 7-9 clips.
2. `write_short_script.py` writes a usable first-draft short with a concise hook, short context labels, and outro.
3. `render_short.py` uses ffmpeg to prep clips, trim silence, and clip captions, then hands the final visual composition to Remotion.
4. `clean` removes the old `work*` folders, concat manifests, and internal scratch state.

## Defaults that matter

- Minimum clips: 7
- Default clip length: 2-6.5 seconds
- Default total runtime target: under 58 seconds
- Shared content cache: `cache/<env>/sermon-clipper/content/`
- Scratch work dir: auto-created under `scripts/sermon-clipper/.work/` and removed after successful render unless `--keep-work` is passed
- Remotion staging: `public/sermon-shorts/` during render

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
format: thought-bites
clips: 8

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
context: Short label for the idea in the clip.
decorators: optional keywords for on-screen pills

## outro
One short closing line.
```

## Render notes

- ffmpeg still handles source download, silence trimming, and clip extraction.
- Remotion handles the final short assembly, overlays, titles, and captions.
- `--no-download` uses only the shared content cache.
- `--trim-silence` trims leading and trailing silence from each clip.
- `--min-clips` prevents accidental under-filled outputs.
