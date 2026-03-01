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

## Analytics (optional)

GA4 can be enabled by setting a measurement id:

- In a feeds `.md` under `# Site`: `- ga_measurement_id: G-XXXX`
- Or via env var: `VOD_GA_MEASUREMENT_ID=G-XXXX`

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

## Priority: real page content

- [ ] **Real page content per page** — TBD: monkey-patch `404.html` vs build dedicated landing page per feed (hotswap, faking multipage). Need to decide approach before implementing.
  - Probably want to make some ability to browse channel episodes like a profile page, since our episode guide is a little tricky on small devices (needs to scale/react better) and for users unfamiliar with sky/cable/tv browsing.
    - Netflix/AmazonPrimeVideo/Disney+/iPlayer ALL use that same format, let's bucket known episodes into 'shows' that are browsable like Netflix.

## Discoverability + accessibility

- [ ] Bake real text into homepage: what it is, what “video RSS” means, what you don’t do (no recommendations/comments), example categories (Services, Sermons, Prayer, Kids, Study)
- [ ] Give every feed its own page with stable URL, plain description, tiny episode list (for indexing + sharing)
- [ ] Optional audio/radio feeds, what about visuals?
- [ ] OpenGraph/Twitter cards so shared links preview as “watchable”
- [ ] Sitemap + sensible canonical URLs; 

## Porting goals

- [ ] Details panel: add timed comments UI (per channel/episode/timestamp)
- [ ] Build step: optionally parse + precompute chapters/transcripts JSON
- [ ] PWA/offline: cache app shell + cached feed XML + (optional) user-selected media
- [ ] Guide: category filter (toggle/selector to show only channels in a category; keep keyboard/remote navigation working)
- [ ] Dynamic “virtual channels”: client-side playlists built from filters/search across other feeds (e.g. Christmas/festive, spiritual support, christian rock)
  - custom feeds made up of live-collections of videos from other feeds, determined as filters, searches, so the site can keep them up to date on the client-side, like dynamic playlists, so we can add a christmas feed that gets christmas/festive/etc by a few filters. some combos like spirtual support or christian rock can then be used to continually form dynamic collections/channels, without having the server determine them all in advance, we can instead code them up in our codebase.
