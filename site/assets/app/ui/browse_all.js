/**
 * Browse All: Netflix-style rows by category.
 * Featured (manual), Continue Watching (in-progress), then randomized category rows.
 */
import { html, useMemo } from "../runtime/vendor.js";

function getShowProgress(show, feedId, history, player) {
  const episodes = show.episodes || [];
  const total = episodes.length;
  if (total === 0) return { watchedCount: 0, resumeEpisode: null, totalEpisodes: 0 };
  const WATCHED_THRESHOLD = 0.9;
  let watchedCount = 0;
  let resumeEpisode = null;
  let bestProgress = 0;
  for (const ep of episodes) {
    const maxProg = player?.getProgressMaxSec?.(feedId, ep.id) ?? 0;
    const dur = ep.durationSec;
    const isWatched = Number.isFinite(dur) && dur > 0 ? maxProg >= dur * WATCHED_THRESHOLD : maxProg > 60;
    if (isWatched) watchedCount++;
    else if (maxProg > bestProgress && maxProg > 0) {
      bestProgress = maxProg;
      resumeEpisode = ep;
    }
  }
  if (!resumeEpisode && watchedCount < total) {
    const historyAll = history?.all?.value || [];
    const episodeIds = new Set(episodes.map((e) => e?.id).filter(Boolean));
    for (const e of historyAll) {
      if (e.sourceId === feedId && episodeIds.has(e.episodeId)) {
        resumeEpisode = episodes.find((x) => x?.id === e.episodeId);
        break;
      }
    }
  }
  return { watchedCount, resumeEpisode, totalEpisodes: total };
}

/** Day-of-year seed (1–366) for daily-varying order */
function dayOfYearSeed() {
  const d = new Date();
  const start = new Date(d.getFullYear(), 0, 0);
  const diff = d - start;
  return Math.floor(diff / (1000 * 60 * 60 * 24)) + 1;
}

/** Seeded shuffle for stable daily order */
function shuffledWithSeed(arr, seed) {
  const a = [...arr];
  let s = seed;
  for (let i = a.length - 1; i > 0; i--) {
    s = (s * 9301 + 49297) % 233280;
    const j = Math.floor((s / 233280) * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

/** Build category rows: Featured, Continue Watching, then shuffled other categories */
function buildCategoryRows(allShows, history, player) {
  const historyAll = history?.all?.value || [];
  const byShowKey = (feedId, showId) => `${feedId}::${showId}`;

  const continueWatching = [];
  const lastWatchedAt = new Map();
  for (const { feedId, feedTitle, show } of allShows) {
    const progress = getShowProgress(show, feedId, history, player);
    if (!progress.resumeEpisode) continue;
    let maxAt = 0;
    const epIds = new Set((show.episodes || []).map((e) => e?.id).filter(Boolean));
    for (const e of historyAll) {
      if (e.sourceId === feedId && epIds.has(e.episodeId)) {
        const t = Number(e.at) || 0;
        if (t > maxAt) maxAt = t;
      }
    }
    lastWatchedAt.set(byShowKey(feedId, show.id), maxAt);
    continueWatching.push({ feedId, feedTitle, show });
  }
  continueWatching.sort((a, b) => (lastWatchedAt.get(byShowKey(b.feedId, b.show.id)) || 0) - (lastWatchedAt.get(byShowKey(a.feedId, a.show.id)) || 0));

  const featured = allShows.filter(({ show }) => show.featured);

  const categoryToShows = new Map();
  for (const item of allShows) {
    const cats = item.show.categories || [];
    if (!cats.length) continue;
    for (const c of cats) {
      if (!c) continue;
      const key = String(c).trim();
      if (!key) continue;
      if (!categoryToShows.has(key)) categoryToShows.set(key, []);
      const list = categoryToShows.get(key);
      if (!list.some((x) => x.feedId === item.feedId && x.show.id === item.show.id)) {
        list.push(item);
      }
    }
  }
  const otherCategories = [...categoryToShows.keys()];
  const daySeed = dayOfYearSeed();
  const shuffledCats = shuffledWithSeed(otherCategories, daySeed);

  const titleCase = (s) => String(s || "").replace(/\b\w/g, (c) => c.toUpperCase());
  const rows = [];
  if (featured.length) rows.push({ id: "featured", label: "Featured", shows: shuffledWithSeed(featured, daySeed + 1) });
  if (continueWatching.length) rows.push({ id: "continue", label: "Continue Watching", shows: continueWatching });
  for (const cat of shuffledCats) {
    const shows = categoryToShows.get(cat) || [];
    if (shows.length) rows.push({ id: `cat-${cat}`, label: titleCase(cat), shows: shuffledWithSeed(shows, daySeed + cat.length) });
  }
  return rows;
}

export function BrowseAllPanel({ isOpen, showsConfig, feedTitles, player, history, onClose, onShowClick }) {
  const feeds = showsConfig?.feeds || {};
  const titles = feedTitles || {};
  const allShows = useMemo(() => {
    const out = [];
    for (const [feedId, shows] of Object.entries(feeds)) {
      if (!Array.isArray(shows)) continue;
      const feedTitle = titles[feedId] || feedId;
      for (const show of shows) {
        const eps = show.episodes || [];
        if (!eps.length) continue;
        out.push({ feedId, feedTitle, show });
      }
    }
    return out;
  }, [feeds, titles]);

  const categoryRows = useMemo(
    () => buildCategoryRows(allShows, history, player),
    [allShows, history?.all?.value, player]
  );

  const playShow = (feedId, show, startEp = null) => {
    const episodes = show.episodes || [];
    if (!episodes.length || !feedId) return;
    const progress = getShowProgress(show, feedId, history, player);
    const ep = startEp || progress.resumeEpisode || episodes[0];
    if (!ep?.id) return;
    player.selectSourceAndEpisode(feedId, ep.id, {
      autoplay: true,
      playlist: { feedId, episodes, showSlug: show.slug || show.id },
    });
    onClose?.();
  };

  if (!allShows.length) {
    return html`
      <div id="browseAllPanel" class="browseAllPanel" aria-hidden=${isOpen ? "false" : "true"} role="dialog">
        <div class="browseAllPanel-inner">
          <header class="browseAllHeader">
            <h2 class="browseAllTitle">Browse Shows</h2>
            <button class="browseAllClose" type="button" onClick=${onClose} aria-label="Close">×</button>
          </header>
          <div class="browseAllEmpty">No shows available.</div>
        </div>
      </div>
    `;
  }

  return html`
    <div id="browseAllPanel" class="browseAllPanel" aria-hidden=${isOpen ? "false" : "true"} role="dialog">
      <div class="browseAllPanel-inner">
        <header class="browseAllHeader">
          <h2 class="browseAllTitle">Browse Shows</h2>
          <button class="browseAllClose" type="button" onClick=${onClose} aria-label="Close">×</button>
        </header>
        <div class="browseAllContent">
          ${categoryRows.map(
            (row) => html`
              <section class="browseAllRow" key=${row.id}>
                <h3 class="browseAllRowTitle">${row.label}</h3>
                <div class="browseAllRowStrip">
                  <div class="browseAllRowStrip-inner">
                    ${row.shows.map(
                      ({ feedId, feedTitle, show }) => {
                        const progress = getShowProgress(show, feedId, history, player);
                        const showTitle = show.title_full || show.title;
                        return html`
                          <div
                            class="browseAllShowCard${onShowClick ? " browseAllShowCardClickable" : ""}"
                            key=${feedId + ":" + show.id}
                            role=${onShowClick ? "button" : undefined}
                            tabIndex=${onShowClick ? 0 : undefined}
                            onClick=${onShowClick ? (e) => { if (!e.target.closest(".browseAllShowCardActions")) onShowClick(feedId, show); } : undefined}
                            onKeyDown=${onShowClick ? (e) => { if (e.key === "Enter" && !e.target.closest(".browseAllShowCardActions")) onShowClick(feedId, show); } : undefined}
                          >
                            <div class="browseAllShowCardPoster">
                              ${show.artworkUrl
                                ? html`
                                    <img src=${show.artworkUrl} alt="" loading="lazy" />
                                    ${(show.artworkOverlay || showTitle) ? html`
                                      <span class="browseAllShowCardOverlay">
                                        <span class="browseAllShowCardOverlayBar">${show.artworkOverlay || showTitle}</span>
                                      </span>
                                    ` : ""}
                                  `
                                : html`<span class="browseAllShowCardPlaceholder">${show.episodeCount || 0}</span>`}
                            </div>
                            <div class="browseAllShowCardInfo">
                              <span class="browseAllShowCardTitle">${showTitle}</span>
                              <span class="browseAllShowCardMeta">${feedTitle} · ${progress.totalEpisodes} episodes</span>
                            </div>
                            <div class="browseAllShowCardActions">
                              ${progress.resumeEpisode
                                ? html`
                                    <button class="browseAllPlayBtn" type="button" onClick=${(e) => { e.stopPropagation(); playShow(feedId, show, progress.resumeEpisode); }}>
                                      Resume
                                    </button>
                                  `
                                : ""}
                              <button class="browseAllPlayBtn" type="button" onClick=${(e) => { e.stopPropagation(); playShow(feedId, show); }}>
                                Play
                              </button>
                            </div>
                          </div>
                        `;
                      }
                    )}
                  </div>
                </div>
              </section>
            `
          )}
        </div>
      </div>
    </div>
  `;
}
