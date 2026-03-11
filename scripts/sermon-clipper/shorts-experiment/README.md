# Shorts Experiment

Vertical shorts (`1080x1920` by default) from church feed clips. This uses the same answer-engine index and shared content cache as the long-form clipper, but is tuned for 8-12 short, memorable thought-bites that can still collapse down to a publishable short if one or two clips fail prep.

## What is implemented

1. `search_shorts.py` now starts from the answer-engine query, mines recurring motifs from the index/transcripts, expands via SQLite FTS, and defaults to one clip per feed.
2. `write_short_script.py` writes a usable first-draft short with a practical hook, short context labels, and an outro that aims at a coherent message rather than a list of disconnected quotes.
3. `render_short.py` uses ffmpeg to prep clips, trim silence, and clip captions, then hands the final visual composition to Remotion.
4. Remotion now renders on Windows by passing props as a JSON file instead of inline CLI JSON, which avoids `cmd.exe` quoting failures on larger manifests.
5. `clean` removes the old `work*` folders, concat manifests, and internal scratch state.

## Defaults that matter

- Minimum clips: 8
- Default target clips: 10
- Default clip length: 2-6.5 seconds
- Default total runtime target: under 58 seconds
- Default feed diversity: 1 clip per feed and 1 clip per episode
- Shared content cache: `cache/<env>/sermon-clipper/content/`
- Scratch work dir: auto-created under `scripts/sermon-clipper/.work/` and removed after successful render unless `--keep-work` is passed
- Remotion staging: `public/sermon-shorts/` during render

## Quick start

```powershell
$ yarn install
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
format: curated thought-bites
selection: multi-feed practical arc
clips: 10

## intro
One short hook sentence that pushes toward a practical message.

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
- Remotion handles the final short assembly, overlays, visual skins, and captions.
- Inter-clip title cards are intentionally gone; pacing is now clip-to-clip without isolated bumpers.
- `--no-download` uses only the shared content cache.
- `--trim-silence` trims leading and trailing silence from each clip.
- `--min-clips` prevents accidental under-filled outputs.
