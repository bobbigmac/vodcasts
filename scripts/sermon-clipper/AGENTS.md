# Sermon Clipper Agent Guide

This folder produces long-form commentary videos from church feed transcripts.

## What the tools do now

- `search_clips.py` searches the answer-engine index and, by default, filters to clips that are actually renderable: video enclosure present, transcript present, one clip per feed, duration bounds respected, used clips excluded.
- `write_script.py` writes a usable first-draft markdown script from those clips. It now fills intro, transitions, outro, and title-card copy automatically instead of leaving bracket placeholders everywhere.
- `make_title_cards.py` renders PNG cards from `title_card` and `transition` sections.
- `render_video.py` downloads source media into the shared content cache, extracts clips, adds optional overlays and subtitles, concatenates the result, and refuses to publish if too few clips survive render.
- `cleanup_outputs.py` removes `__pycache__`, internal `.work/`, output-side `work*` directories, and stray `concat_list.txt` files.

## Caches and scratch

- Query cache: `cache/<env>/sermon-clipper/query-cache/`
- Shared content cache: `cache/<env>/sermon-clipper/content/`
- Scratch render dir: `scripts/sermon-clipper/.work/`
- Default scratch dirs are removed after a successful render unless `--keep-work` is passed.

## Script contract

The markdown script remains the render source of truth:

```markdown
# Video: When Forgiveness Gets Real

## metadata
theme: forgiveness
target_duration_minutes: 15

## intro
2-3 sentences that frame the issue.

## title_card
id: intro
text: One sentence that sets up the journey.

## clip
feed: ...
episode: ...
start_sec: ...
end_sec: ...
quote: "..."
episode_title: ...
feed_title: ...

## transition
1-3 sentences connecting the previous clip to the next.

## outro
Brief wrap-up that points viewers to the fuller context.

## title_card
id: outro
text: Full episodes and full context at prays.be
```

`render_video.py` treats `transition` sections as title cards named `transition_1`, `transition_2`, and so on.

## Workflow

```powershell
# Search renderable clips
sc.ps1 search --theme "when forgiveness feels impossible" --output out/sermon-clips-examples/forgiveness-clips.json --exclude-used out/sermon-clips-examples/used-clips.json

# Write first draft script
sc.ps1 write --theme "when forgiveness feels impossible" --clips out/sermon-clips-examples/forgiveness-clips.json --output out/sermon-clips-examples/forgiveness-video.md

# Generate cards
sc.ps1 cards --script out/sermon-clips-examples/forgiveness-video.md --output out/sermon-clips-examples/forgiveness-cards

# Render
sc.ps1 render --script out/sermon-clips-examples/forgiveness-video.md --output out/sermon-clips-examples/forgiveness.mp4 --title-cards out/sermon-clips-examples/forgiveness-cards --register out/sermon-clips-examples/used-clips.json

# Clean leftovers from older runs if needed
sc.ps1 clean --path out/sermon-clips-examples
```

## Useful flags

- `search_clips.py`: `--allow-audio`, `--allow-missing-transcript`, `--exclude-used`, `--no-cache`
- `render_video.py`: `--no-download`, `--trim-silence`, `--no-subs`, `--no-overlay`, `--min-clips`, `--keep-work`

## Quality bar

- Do not accept card-only or one-clip long-form renders.
- Prefer clips that can render cleanly before writing scripts.
- Keep commentary substantive. Short excerpts plus framing, not clip dumping.
