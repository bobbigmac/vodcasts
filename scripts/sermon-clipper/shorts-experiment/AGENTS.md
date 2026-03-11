# Shorts Experiment Agent Guide

This folder produces vertical sermon shorts from the same church transcript index used by the long-form clipper.

## Current contract

- `search_shorts.py` is tuned for 2-6.5 second thought-bites, 8-12 clips total, and under ~58 seconds total.
- The selector should mine recurring motifs from the index/transcripts, not just trust the initial theme query at face value.
- By default a short should use different feeds for every clip unless the user explicitly asks for a different tradeoff.
- Search defaults to clips that are actually renderable: video enclosure present and transcript present.
- `write_short_script.py` produces a usable draft with a concise practical hook, short context labels, and outro.
- `render_short.py` uses ffmpeg to prep trimmed clips/captions, then Remotion composes the final vertical short.
- Remotion props should be passed via JSON file on Windows, not inline JSON, to avoid `cmd.exe` quoting problems.
- `cleanup_outputs.py` from the parent folder cleans old `work*` directories, concat files, pycache, and internal scratch.

## Script contract

```markdown
# Short: Grace

## metadata
theme: grace
format: curated thought-bites
selection: multi-feed practical arc
clips: 10

## intro
One short hook sentence that carries a practical message.

## clip
feed: ...
episode: ...
start_sec: ...
end_sec: ...
quote: "..."
episode_title: ...
feed_title: ...
context: Short label for why the clip lands.
decorators: Optional keywords for the panel.

## outro
One short closing line.
```

Under-filled shorts are not acceptable unless the user explicitly accepts that tradeoff for a faster local proof render.

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

- Keep the clip count in the 8-12 range unless the user explicitly asks otherwise.
- Do not rely on sources that will fail render later.
- Context text should label the idea, not restate the quote.
- The draft script does not need to read like a perfect essay, but it should try to carry one meaningful thread or answer a real-life question rather than feeling listy.
