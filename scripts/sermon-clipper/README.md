# Sermon Clipper

Generate YouTube-style video essays from church feed content: search the transcript index for themed clips, write a video script (markdown), generate title cards, and render a composed video with ffmpeg.

## Flow

1. **search_clips** — Query the answer-engine index for segments matching a theme; output JSON of clips with timestamps.
2. **write_script** — Assemble clips into a video script (markdown) with intro, commentary, and outro.
3. **make_title_cards** — Generate title card images for intro/outro and commentary sections.
4. **render_video** — Download source videos, extract clips by timestamp, concatenate with title cards.

## Requirements (design notes)

- **Query cache** — Answer-engine queries cost money. Cache responses by theme so the same video/root-query reuses cached results instead of rerunning analyze/query. Use `--no-cache` to bypass.
- **Content cache** — Don't duplicate source videos. Use a shared project-local content cache that can be cleared later. During dev the retrieval set is small; project-local is fine. In production, clean up occasionally.
- **Audio and subtitles** — Final videos must have sound and subtitles. Clip audio must not be lost along the way.

## Query cache

Search results are cached at `cache/<env>/sermon-clipper/query-cache/` by theme. Re-running the same theme reuses the cache instead of querying again. Use `--no-cache` to force a fresh search.

## Content cache

Source videos are stored in a shared project-local cache at `cache/<env>/sermon-clipper/content/`. No duplication across outputs; clear the folder occasionally in production. Override with `--content-cache`.

## Rules

- **One clip per feed** — no repeated sources in a single video
- **Target ~15 minutes** — favor clips under 2 min
- **Exclude used clips** — pass `--exclude-used out/used-clips.json` so future videos don't reuse the same clip
- **Snappiness** — `--max-duration 45` for quick bites; default 120s for fuller explanations

## Usage

Use the answer-engine venv for search/write. Use system Python for cards/render.

```powershell
# 1. Search (exclude already-used clips)
sc.ps1 search --theme "when forgiveness feels impossible" --output out/clips.json --exclude-used out/used-clips.json

# 2. Write script (LLM enriches intro, transitions, outro — see AGENTS.md)
sc.ps1 write --theme forgiveness --clips out/clips.json --output out/forgiveness-video.md

# 3. Generate title cards (intro, transitions, outro)
sc.ps1 cards --script out/forgiveness-video.md --output out/title-cards

# 4. Render (source overlay on clips, register used clips)
sc.ps1 render --script out/forgiveness-video.md --output out/forgiveness.mp4 --title-cards out/title-cards --register out/used-clips.json
```

Or run directly with the answer-engine venv for search/write:

```powershell
scripts/answer-engine/.venv/Scripts/python.exe scripts/sermon-clipper/search_clips.py --theme forgiveness --output out/clips.json
scripts/answer-engine/.venv/Scripts/python.exe scripts/sermon-clipper/write_script.py --theme forgiveness --clips out/clips.json --output out/forgiveness-video.md
python scripts/sermon-clipper/make_title_cards.py --script out/forgiveness-video.md --output out/title-cards
python scripts/sermon-clipper/render_video.py --script out/forgiveness-video.md --output out/forgiveness.mp4 --title-cards out/title-cards
```

## Video Script Format (Markdown)

The script is the source of truth for rendering. Structure:

```markdown
# Video: [Title]

## metadata
theme: forgiveness
duration_estimate: 8m

## intro
[Text for intro section]

## title_card
id: intro
text: What Pastors Say About Forgiveness

## commentary
[Optional commentary before first clip]

## clip
feed: bridgetown
episode: 2026-03-02-the-good-news-about-our-bodies-10g2du
start_sec: 120.5
end_sec: 145.2
quote: "The quote text..."
commentary: [Optional commentary after clip]

## outro
[Text for outro]

## title_card
id: outro
text: Thanks for watching
```

## Dependencies

- **search_clips / write_script**: Use answer-engine venv (has transcript index deps).
- **make_title_cards**: `pip install Pillow`
- **render_video**: ffmpeg (downloads source videos, extracts clips, concatenates).

## Output format

All segments are normalized to **1080p, 30fps, yuv420p, AAC 48kHz mono** before concatenation. This avoids duration issues (e.g. 4x length) from frame rate or timebase mismatch between title cards and source clips.

## Subtitles

When a transcript exists at `site/assets/transcripts/<feed>/<episode>.vtt` (or `.srt`), the render embeds clipped subtitles into each video segment. Cues within the clip's time range are extracted and timestamps adjusted. Use `--no-subs` to skip.

## Fair Use

Structure videos as commentary/criticism: short excerpts, heavy intercutting with your own framing, clear source attribution. See `ChatGPT-Podcast_Clips_Fair_Use.md` for guidance.
