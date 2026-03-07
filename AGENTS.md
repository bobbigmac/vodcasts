<INSTRUCTIONS>
# AGENTS.md (vodcasts project guide)

This folder is intended to be movable as its own project. Keep imports and scripts relative to this folder (not the parent repo).

## Quick commands

- Select env (persists to `.vodcasts-env`): `yarn use dev|church|tech|complete`
- Update RSS cache: `yarn update`
- Build static site (runs a quiet update first): `yarn build` (set `VOD_BASE_PATH` for subpath builds)
- Dev server (Vite; rebuilds into `dist/`): `yarn dev`
- Answer Engine (transcript search): `bash scripts/answer-engine/ae.sh analyze` then `bash scripts/answer-engine/ae.sh index` then `bash scripts/answer-engine/ae.sh query search --q "..."` (cache stored under `cache/<env>/answer-engine/`)
- Auto-chapters from analyzed transcripts: `bash scripts/answer-engine/ae.sh chapters` (writes to `site/assets/chapters/<feed>/<episode>.chapters.json`)
- Fast dev spot-check (single file): `bash scripts/answer-engine/ae.sh chapters --transcript <feed>/<episode>.vtt --force --print`

## Deployments (feeds + cache)

- Each deployment is a pair: `feeds/<env>.md` + `cache/<env>/`.
- Feed slugs must remain stable: cached filenames are `cache/<env>/feeds/<slug>.xml` and build outputs reference them.
- The build copies cached feeds into the site at `dist/data/feeds/<slug>.xml` to avoid CORS issues.
- Dev-only remote fetch/proxy exists at `/__feed?url=…` (see `vite.config.js`).

## Build outputs (what the client consumes)

- `dist/site.json` — site config + build metadata (also used for optional analytics/comments config).
- `dist/video-sources.json` — normalized sources from feeds markdown, with computed `features` and resolved `feed_url`.
- `dist/shows-config.json` — per-feed “shows” (derived from `feeds/shows/<slug>.json` + feed content) used by Browse UIs.
- `dist/feed-manifest.json` — compact episode metadata used for client-side preload.
- `dist/data/feeds/` — shipped RSS cache used by `video-sources.json` when available.
- `dist/feed/<slug>/index.html` — per-feed landing pages.
- `dist/browse/index.html` — browse-all entrypoint (route `/browse/`).

Build script entrypoints:
- `scripts/update_feeds.py` — fetch RSS into `cache/<env>/feeds/` (cooldown + ETag/Last-Modified).
- `scripts/build_site.py` — writes the artifacts above, plus landing pages and show RSS exports.
- `scripts/show_filters.py` — applies show filter rules to group episodes into shows.
- `scripts/scan_feed_titles.py` — scans cached feeds for title patterns (useful when authoring show filters).
- `scripts/report_show_filters.py` — helper report for missing/empty show configs and detected shows (writes to `tmp/`).

## Client architecture (runtime)

- HTML template: `site/templates/index.html` injects `window.__VODCASTS__` (basePath/site/initialFeed/initialView).
- App entry: `site/assets/app.js` loads `site/assets/app/index.js` which calls `bootApp()` (`site/assets/app/main/boot.js`).
- Routes: `site/assets/app/main/route.js` supports `/browse/`, `/feed/<slug>/…`, and legacy `/<slug>/…` forms (also GitHub Pages `?p=` redirect).
- `initialView` values:
  - `"browse"` — used by feed landing pages (open per-feed Browse panel).
  - `"browseAll"` — used by the browse-all entrypoint.
- Newcomer behavior: on `/` (homepage), if there is no prior player state in `localStorage` (`vodcasts_state_v1` absent), the app opens Browse All by default.
- Default feed selection heuristic lives in `site/assets/app/player/player.js` (`pickDefaultSourceId()` uses the first ~10 sources as the head and prefers “core” categories with video).

## Front-end modules (high-signal)

- `site/assets/app/main/app.js` — main UI composition (player + panels + corner buttons) and route syncing.
- `site/assets/app/main/controls.js` — keyboard/remote focus + input helpers.
- `site/assets/app/player/player.js` — media controller (HLS, progress persistence, play/pause intent persistence, chapters/subtitles).
- `site/assets/app/ui/browse_all.js` — Browse All Shows panel (category rows, light virtualization, audio-only toggle, newcomer hero).
- `site/assets/app/ui/browse.js` — per-feed show browsing panel.
- `site/assets/app/ui/guide.js` — channel guide (feed list + episodes).
- `site/assets/app/ui/details.js` — details sidebar.
- `site/assets/app/state/history.js` — local history store (Continue Watching).

## Persistence keys (client)

- `vodcasts_state_v1` — player state (volume/mute, playIntent, last feed/episode, prefs).
- `vodcasts_history_v1` — watch/play history used by Continue Watching and progress UI.
- `vodcasts_guide_prefs_v1` — guide favorites and guide-related prefs.
- `vodcasts_browse_all_prefs_v2` — Browse All prefs (e.g. audio-only visibility toggle).
- `vodcasts_browse_all_intro_v1` — Browse All newcomer hero dismissal.

</INSTRUCTIONS>
