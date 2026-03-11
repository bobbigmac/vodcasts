# Sermon Clipper

Smart, mostly automated video composition tooling for sermon and church-feed source material in this repo.

This folder is where you come to make videos from transcript-indexed source material:

- long-form commentary / compilation videos
- short-form vertical videos
- repeatable rerenders from markdown source-of-truth files
- cache-aware workflows that reuse search results, source media, and scratch outputs until you deliberately clean them

## What lives here

- `search_clips.py` / `write_script.py`: find long-form source clips from the answer-engine index and draft a long-form render sheet
- `render_video.py` / `make_title_cards.py`: render long-form videos from that sheet
- `shorts-experiment/`: short-form search, draft, and Remotion render flow for vertical outputs
- `cleanup_outputs.py`: remove scratch state and obvious temp leftovers without touching deliberate outputs or the shared source cache
- `spacetime-compression/`: compatibility entrypoints for the markdown-video-editor feature set; the canonical home is `scripts/markdown-video-editor/`

## Working model

There are currently two markdown source-of-truth layers:

- long-form / short-form render sheets in this folder
- feature-specific edit plans in `scripts/markdown-video-editor/`

That means the system is already rerenderable and inspectable, but it is not yet a single universal edit-sheet format. When asked to make a video, the normal pattern is:

1. Find candidate source clips from the transcript/index tooling.
2. Draft the markdown render sheet that describes the production.
3. Render, review, and rerender from that same markdown file.
4. Clean scratch state when the output is confirmed good, while keeping the shared content cache for future runs.

## Main entrypoints

Long-form:

```bash
bash scripts/sermon-clipper/sc.sh search --theme "forgiveness" --output out/clips.json
bash scripts/sermon-clipper/sc.sh write --theme "forgiveness" --clips out/clips.json --output out/video.md
python scripts/sermon-clipper/make_title_cards.py --script out/video.md --output out/title-cards
python scripts/sermon-clipper/render_video.py --script out/video.md --output out/video.mp4 --title-cards out/title-cards
```

Short-form:

```bash
python scripts/sermon-clipper/shorts-experiment/search_shorts.py --theme "forgiveness" --output out/shorts/clips.json
python scripts/sermon-clipper/shorts-experiment/write_short_script.py --theme "forgiveness" --clips out/shorts/clips.json --output out/shorts/video.md
python scripts/sermon-clipper/shorts-experiment/render_short.py --script out/shorts/video.md --output out/shorts/video.mp4 --trim-silence
```

Edit/manipulation feature tooling:

```bash
python scripts/markdown-video-editor/analyze_spacetime_plan.py --input in/source.mp4 --output out/source.edit.md
python scripts/markdown-video-editor/apply_edit_plan.py --plan out/source.edit.md --output out/source.out.mp4
```

Cleanup:

```bash
python scripts/sermon-clipper/cleanup_outputs.py --path out --path out/shorts
```

## Cache and cleanup rule

Keep:

- final markdown sheets
- final renders
- shared source media cache under `cache/<env>/sermon-clipper/content/`

Safe to clean and regenerate:

- internal scratch under `scripts/sermon-clipper/.work/`
- output-side `work*` directories
- concat manifests
- pycache

## Goal

The intended operator experience is: ask for a long or short video on a topic/question, let the LLM assemble the right sources and markdown control sheet, render from that source of truth, inspect the result, then rerender or clean without losing the expensive cached source material. For shorts, ffmpeg now handles source prep while Remotion handles the final look and sequencing.


## TODO: 

 if you can find some nice libs or components for Remotion (I don't know much about how it works) I want each video to have its own character and style, so either use some available extensions for really nice video polish, or just work in more style, offsets, patterns, themes, skins, etc. I want a broad variety of video layout options, so we can experiement, while still having our current base version that works well enough (additive, componentised, flavour, not destructive). TikTokers are very sensitive to jank or weirdness, and appreciate slick presentation, so let's try and make sure every video we produce is just awesome by default, even tho it's basically just videos of mostly guys talking, we're trying to reall ymake the rest of the video really deliver on its promise of meaningful and slick videos. (A big ask perhaps, but we have all the parts we need to make that happen, but it just takes work to get everything right, is the theory )