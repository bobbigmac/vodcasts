# Sermon Clipper

Generate long-form commentary videos from church feed content: search the transcript index for themed clips, write a usable first-draft script, generate title cards, and render a composed video with ffmpeg.

## What is implemented

1. `search_clips` queries the answer-engine index and, by default, only returns clips that already have a local transcript and a video enclosure.
2. `write_script` turns those clips into a usable markdown draft with intro, transitions, outro, and title-card copy.
3. `make_title_cards` renders PNG cards from the script.
4. `render_video` downloads source videos into the shared content cache, cuts the clips, burns in optional source overlays and clipped subtitles, concatenates everything, and can register used clips.
5. `clean` removes clipper scratch state plus obvious leftover render junk such as `work*` directories and `concat_list.txt`.

## Requirements and defaults

- Query cache: `cache/<env>/sermon-clipper/query-cache/`
- Shared content cache: `cache/<env>/sermon-clipper/content/`
- Scratch work dir: auto-created under `scripts/sermon-clipper/.work/` and removed after a successful render unless you pass `--keep-work`
- Audio and subtitles: renders preserve audio; subtitles are embedded when a matching transcript exists

## Usage

Use the answer-engine venv for `search` and `write`. Use system Python for `cards`, `render`, and `clean`.

```powershell
# 1. Search renderable clips
sc.ps1 search --theme "when forgiveness feels impossible" --output out/sermon-clips-examples/forgiveness-clips.json --exclude-used out/sermon-clips-examples/used-clips.json

# 2. Write a first draft script
sc.ps1 write --theme "when forgiveness feels impossible" --clips out/sermon-clips-examples/forgiveness-clips.json --output out/sermon-clips-examples/forgiveness-video.md

# 3. Generate cards
sc.ps1 cards --script out/sermon-clips-examples/forgiveness-video.md --output out/sermon-clips-examples/forgiveness-cards

# 4. Render and register
sc.ps1 render --script out/sermon-clips-examples/forgiveness-video.md --output out/sermon-clips-examples/forgiveness.mp4 --title-cards out/sermon-clips-examples/forgiveness-cards --register out/sermon-clips-examples/used-clips.json

# 5. Clean output-side leftovers if you used old work dirs
sc.ps1 clean --path out/sermon-clips-examples
```

Direct Python usage:

```powershell
scripts/answer-engine/.venv/Scripts/python.exe scripts/sermon-clipper/search_clips.py --theme forgiveness --output out/clips.json
scripts/answer-engine/.venv/Scripts/python.exe scripts/sermon-clipper/write_script.py --theme forgiveness --clips out/clips.json --output out/video.md
python scripts/sermon-clipper/make_title_cards.py --script out/video.md --output out/title-cards
python scripts/sermon-clipper/render_video.py --script out/video.md --output out/video.mp4 --title-cards out/title-cards
python scripts/sermon-clipper/cleanup_outputs.py --path out
```

## Search behavior

Default search rules:

- one clip per feed
- favor clips under 2 minutes
- require video enclosures
- require local transcripts
- skip clips already registered in `used-clips.json`

Relax the defaults only when needed:

- `--allow-audio`
- `--allow-missing-transcript`
- `--no-cache`

## Script format

The markdown script is the render source of truth.

```markdown
# Video: When Forgiveness Gets Real

## metadata
theme: forgiveness
target_duration_minutes: 15

## intro
Two sentences that frame the question and set expectation.

## title_card
id: intro
text: One sentence for the opening card.

## clip
feed: antioch-church
episode: 2023-08-20-full-bloom-93yx2
start_sec: 1827.761
end_sec: 1948.69
quote: "The quote text..."
episode_title: Full Bloom
feed_title: Antioch Church

## transition
One to three sentences that connect the previous clip to the next one.

## outro
Wrap up the thread and point to full context.

## title_card
id: outro
text: Full episodes and full context at prays.be
```

## Render notes

- Output format is normalized to `1080p / 30fps / yuv420p / AAC 48kHz mono`.
- Subtitle clips are cut from `site/assets/transcripts/<feed>/<episode>.vtt` or `.srt`.
- `--no-download` means "use the shared content cache only"; it does not look in old output work folders.
- `--min-clips` prevents accidental card-only or single-clip renders.

## Fair use

Keep the transformation obvious: short excerpts, clear attribution, and real commentary between clips.
