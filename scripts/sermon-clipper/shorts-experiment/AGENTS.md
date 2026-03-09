# Shorts Experiment Agent Guide

This folder produces vertical sermon shorts from the same church transcript index used by the long-form clipper.

## Current contract

- `search_shorts.py` is tuned for 10-18 second clips, 2-4 clips total, one clip per feed, and under ~55 seconds total.
- Search now defaults to clips that are actually renderable: video enclosure present and transcript present.
- `write_short_script.py` produces a usable draft with intro, clip context, and outro.
- `render_short.py` renders a vertical split-screen short with context panel, subtitles, preserved audio, and shared source caching.
- `cleanup_outputs.py` from the parent folder cleans old `work*` directories, concat files, pycache, and internal scratch.

## Script contract

```markdown
# Short: Grace

## metadata
theme: grace
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
context: Why the clip matters.
decorators: Optional keywords for the panel.

## outro
One short closing line.
```

Single-clip shorts are never acceptable.

## Workflow

```powershell
short.ps1 search --theme forgiveness --output out/shorts/forgiveness-clips.json
short.ps1 write --theme forgiveness --clips out/shorts/forgiveness-clips.json --output out/shorts/forgiveness.md
short.ps1 render --script out/shorts/forgiveness.md --output out/shorts/forgiveness.mp4
short.ps1 clean --path out/shorts
```

## Useful flags

- `search_shorts.py`: `--feeds`, `--allow-audio`, `--allow-missing-transcript`, `--exclude-used`, `--no-cache`
- `render_short.py`: `--trim-silence`, `--context-bottom`, `--no-download`, `--no-subs`, `--min-clips`, `--keep-work`

## Quality bar

- Keep the clip count at 2 or more.
- Do not rely on sources that will fail render later.
- Context text should explain the clip, not just repeat it.
