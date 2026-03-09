# Sermon Clipper — Agent Guide

This folder produces YouTube-style video essays from church feed transcripts. An LLM uses the answer-engine index to find compelling clips, then writes a video script that the tools render.

## Index & Querying

### How to search

```bash
# Use the answer-engine venv
scripts/answer-engine/.venv/Scripts/python.exe scripts/sermon-clipper/search_clips.py --theme "..." --output out/clips.json
```

Or via `sc.ps1 search` / `sc.sh search`.

### Query patterns that work well

- **Single concept**: `forgiveness`, `prayer`, `suffering`, `hope` — good for broad exploration
- **Question / concern**: `when I can't forgive`, `struggling with doubt`, `how do I pray when it feels empty`
- **Life situation**: `chronic illness and faith`, `parenting with grace`, `work and calling`
- **Theological angle**: `theology of suffering`, `grace and law`, `reconciliation`
- **Emotional / experiential**: `when God feels silent`, `joy in hardship`, `peace that passes understanding`

The index uses FTS + reranking. Broader terms surface more; specific phrases can yield sharper matches. Try multiple queries and merge results if needed.

### Rules (enforced by search_clips)

- **One clip per feed** — no repeated sources in a single video
- **Target ~15 minutes** — `--target-duration 900` (seconds)
- **Favor clips under 2 minutes** — `--max-duration 120`
- **Exclude already-used clips** — `--exclude-used out/used-clips.json`
- **Snappiness** — `--max-duration 45` for quick bites; default 120 for fuller explanations

## Video script format (markdown)

The script is the source of truth. Structure:

```markdown
# Video: [Compelling title — not just "What Pastors Say About X"]

## metadata
theme: [topic]
target_duration_minutes: 15

## intro
[2–3 sentences that frame the issue. Why does this matter? What question or concern are we exploring?]

## title_card
id: intro
text: [Brief discussion of the issue — 1–2 sentences. Not "here are some pastors." Set up the journey.]

## clip
feed: ...
episode: ...
start_sec: ...
end_sec: ...
quote: "..."
episode_title: [for overlay]
feed_title: [for overlay, optional]

## transition
[Radio-style "link": reflect on what just played, add depth, flow into the next. Can use question, concern, conceit. 1–3 sentences. Not DJ-ish — substantive.]

## clip
...

## outro
[Wrap up. What did we learn? Where might the viewer go from here?]

## title_card
id: outro
text: [Closing thought or call to action]
```

### Script quality guidelines

- **Title card intro**: Discuss the issue briefly. Why this topic? What’s at stake? Set up the journey.
- **Transitions**: After each clip, say something that adds depth — reflect, question, connect. Flow into the next clip. Think radio links, not DJ banter.
- **Goal**: Compelling, inspiring, exploratory. Take the viewer on a journey. Curate clips that build on each other.
- **Fair use**: Short excerpts, clear attribution, your commentary/analysis carries the piece.

## Pipeline

1. **search_clips** — Query index, apply rules, output JSON
2. **write_script** — Produce markdown script (LLM fills intro, transitions, outro, title card text)
3. **make_title_cards** — Generate images from `title_card` sections
4. **render_video** — Download, extract clips, add source overlays, concatenate
5. **Register clips** — Append to `used-clips.json` so future videos don’t reuse them

## Shorts experiment

See `shorts-experiment/AGENTS.md` for vertical shorts. TODO: OpenCV face smart-crop for variable layouts (see shorts AGENTS.md). (2–4 clips, 10–25s each, split-screen layout). Same index, tuned for quick iteration.

## Files

- `search_clips.py` — Query index, one-per-feed, duration rules, exclude-used
- `write_script.py` — Skeleton from clips; LLM enriches intro/transitions/outro
- `make_title_cards.py` — PNG title cards from script
- `render_video.py` — ffmpeg: download to shared content cache, extract, overlay source (feed + episode title), concat
- `_lib.py` — clip_id, used-clips registry, get_feed_title

## Example workflow

```powershell
# 1. Search (exclude clips already used)
sc.ps1 search --theme "when forgiveness feels impossible" --output out/clips.json --exclude-used out/used-clips.json

# 2. LLM: Read clips.json, write a rich script (intro, transitions, outro, title card text)
#    Edit out/forgiveness-video.md with compelling content

# 3. Generate title cards (intro + transitions + outro)
sc.ps1 cards --script out/forgiveness-video.md --output out/title-cards

# 4. Render (adds source overlay to clips, registers used clips)
sc.ps1 render --script out/forgiveness-video.md --output out/forgiveness.mp4 --title-cards out/title-cards --register out/used-clips.json
```
