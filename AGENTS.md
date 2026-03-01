<INSTRUCTIONS>
# AGENTS.md (vodcasts project guide)

This folder is intended to be movable as its own project. Keep imports and scripts
relative to this folder, not the parent repo.

## Process notes

- Build output lives in `dist/`; generate it with `python3 -m scripts.build_site --base-path / --out dist`.
- Feed cache lives in `cache*/feeds/` and is copied into the build as `dist/data/feeds/` to avoid CORS issues.
- Dev server uses Vite rooted at `dist/` with a plugin that rebuilds (and copies assets on change).
- In dev only, a `/__feed?url=…` proxy exists to fetch remote feeds/transcripts (see `vite.config.js`).

## Deployments

- Use `feeds*.md` + a matching `cache*` directory per deployment.
- Keep feed slugs stable: cached filenames are `cache/<env>/feeds/<slug>.xml`.

## Client architecture

- HTML loads `site/assets/app.js`, which bootstraps the ESM app at `site/assets/app/index.js`.
- The app reads config from `window.__VODCASTS__` (injected by the build into `index.html`).
- The app loads `video-sources.json` (built artifact) which points each source’s `feed_url` at either:
  - `data/feeds/<slug>.xml` when cached, or
  - the original remote RSS URL as a fallback (likely CORS-blocked in prod).

## File map (1 line per file)

- `package.json` — local scripts (`update/build/dev`) and stack (`vite` + `dotenv`).
- `feeds/complete.md` — full feed set (porting reference; not used in normal builds).
- `feeds/church.md` — church-only deployment feeds config.
- `feeds/tech.md` — tech/edu-ish deployment feeds config.
- `feeds/dev.md` — tiny dev feed set for quick local iteration.
- `feeds/video-sources.json` — legacy JSON sources list (reference copy; not required by the build).
- `vite.config.js` — Vite dev server rooted at `dist/` + dev rebuild plugin + `/__feed` proxy.

### Build scripts

- `scripts/update_feeds.py` — fetches feed XML into `cache*/feeds/` with cooldown + ETag/Last-Modified support.
- `scripts/find-feeds.js` — find video podcasts via PodcastIndex API; add to feeds config (requires .env with PODCASTINDEX_KEY/SECRET). Caches API + RSS in `cache/find-feeds/`.
- `scripts/build_site.py` — copies assets + cached feeds into `dist/`, writes `site.json`, `video-sources.json` (with per-feed features), `feed-manifest.json` (all feeds + episodes brief), renders `index.html`.
- `scripts/sources.py` — loads sources from feeds markdown and normalizes categories + titles.
- `scripts/shared.py` — markdown config loader + `curl`-based fetch helper with hard timeouts.
- `scripts/feeds_md.py` — markdown feeds parser (copied from the parent project; keep compatible).

### Static site

- `site/templates/index.html` — single-page UI shell; includes details sidebar w/ comments panel.
- `site/assets/style.css` — main stylesheet; @imports partials from `site/assets/styles/` (variables, layout, player, audio-viz, progress, captions, overlays, guide-bar, guide-panel, panels, corner, idle).
- `site/assets/themes.css` — theme overrides (modern/dos).
- `site/assets/app.js` — stable loader that imports `assets/app/index.js` as a module.

### Client app modules

- `site/assets/app/index.js` — composition root; calls `bootApp()`.
- `site/assets/app/main/boot.js` — loads env + sources; creates store + controller.
- `site/assets/app/main/controller.js` — wires UI panels (player/guide/details/history) and global UX glue (idle fade, Esc).
- `site/assets/app/runtime/env.js` — reads `window.__VODCASTS__` and exposes `sourcesUrl` + `feedProxy` (dev).
- `site/assets/app/runtime/store.js` — minimal `getState/update/subscribe`.
- `site/assets/app/runtime/log.js` — log panel writer.
- `site/assets/app/player/player.js` — video element controller (HLS via `hls.js`, progress persistence, chapters/subtitles, sleep timer).
- `site/assets/app/player/audio_viz.js` — audio-only display: uses preferred plugin from registry.
- `site/assets/app/player/audio_plugins/` — built-in plugins: wave, starfield, clock, weather, calendar, aquarium. Preference via Audio options (◐) when playing audio-only.
- `site/assets/app/ui/guide.js` — channel guide renderer (lazy loads episodes per feed).
- `site/assets/app/ui/details.js` — details sidebar coordinator (binds comments to current episode when open).
- `site/assets/app/ui/chapters.js` — chapters loader + renderer.
- `site/assets/app/state/history.js` — session history store + renderer.
- `site/assets/app/vod/sources.js` — loads `video-sources.json`.
- `site/assets/app/vod/feed_cache.js` — browser Cache API wrapper + heuristic TTL for remote fetches.
- `site/assets/app/vod/feed_parse.js` — RSS/Atom parsing + enclosure picking + chapters/transcripts extraction.
- `site/assets/app/vod/timed_comments.js` — Supabase timed comments (optional; configured by `site.json`).

</INSTRUCTIONS>
