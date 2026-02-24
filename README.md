# VODcasts

A minimal “vodcast TV” player + static site builder. One codebase can ship many small
deployments (church sermons, university lectures, tech shows, fitness, etc.) just by
swapping the feeds config.

## What it ships

- Channel guide (feed switching without losing place)
- Per-feed + per-episode progress (resume)
- Chapters (Podlove Simple Chapters + Podcasting 2.0 `podcast:chapters` JSON)
- Subtitles (WebVTT/SRT via `podcast:transcript`)
- History panel (segment log + restart/continue)
- Sleep timer
- Details sidebar with timed comments (optional; Supabase + realtime)

## Why the build step matters (CORS)

In production, most third-party RSS feeds can’t be fetched by the browser due to CORS.
The `update` step caches raw feed XML into `cache*/feeds/*.xml`, and the `build` step
copies those into the site as `dist/data/feeds/*.xml`. The client then fetches feeds
same-origin.

## Local commands

Run these from inside the `vodcasts/` folder:

- `yarn update` — fetch + cache feeds into `cache/`
- `yarn build` — build static site into `dist/`
- `yarn dev` — dev server on port `8000` (small feed set)

## Deployments

Each deployment is just a different feeds file (and optionally a different cache dir):

- `feeds/complete.md` — full set (porting reference; `yarn use complete` to build)
- `feeds/church.md` — church-only pack
- `feeds/tech.md` — tech/edu-ish pack
- `feeds/dev.md` — tiny set for fast local dev

## Timed comments (optional)

Configure at build time via env vars:

- `VOD_SUPABASE_URL`
- `VOD_SUPABASE_ANON_KEY`
- `VOD_HCAPTCHA_SITEKEY` (optional)

Schema notes live in `docs/supabase-comments.md`.

## Roadmap / goals

- Optional build-time enrichment (precompute chapters/transcripts JSON)
- PWA/offline media caching (app shell + cached feeds + optional user-selected media)

# VODcasts TODO

## Porting goals

- [?] Feed parsing split into `feed/*` + `player/*` + `ui/*`
- [ ] Details panel: add timed comments UI (per channel/episode/timestamp)
- [ ] Build step: optionally parse + precompute chapters/transcripts JSON
- [ ] PWA/offline: cache app shell + cached feed XML + (optional) user-selected media

