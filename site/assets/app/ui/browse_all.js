/**
 * Browse All: Netflix-style rows by category.
 * Featured (manual), Continue Watching (in-progress), then randomized category rows.
 */
import { html, useMemo } from "../runtime/vendor.js";
import { fallbackInitials, thumbFallbackStyle, titlePosClass, VodCarouselRow } from "./vod_carousel.js";

function onThumbImgError(e) {
  try {
    const img = e.currentTarget;
    img.style.display = "none";
  } catch {}
}

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

function fnv1a32(s) {
  const str = String(s || "");
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
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

  // Fluidify: assign each show to ONE of its categories to balance row sizes.
  const normCats = (cats) =>
    (Array.isArray(cats) ? cats : [])
      .map((c) => String(c || "").trim())
      .filter(Boolean);

  const showKeyOf = (item) => byShowKey(item.feedId, item.show.id);
  const allKeys = new Map();
  for (const item of allShows) allKeys.set(showKeyOf(item), item);

  const counts = new Map();
  for (const c of otherCategories) counts.set(c, 0);

  const assigned = new Map(); // showKey -> category
  const itemsShuffled = shuffledWithSeed(allShows, daySeed + 17);
  for (const item of itemsShuffled) {
    const cats = normCats(item.show.categories);
    if (!cats.length) continue;
    let best = cats[0];
    let bestCount = counts.get(best) || 0;
    let bestTie = fnv1a32(`${daySeed}:${item.feedId}:${item.show.id}:${best}`);
    for (let i = 1; i < cats.length; i++) {
      const cat = cats[i];
      const c = counts.get(cat) || 0;
      const tie = fnv1a32(`${daySeed}:${item.feedId}:${item.show.id}:${cat}`);
      if (c < bestCount || (c === bestCount && tie < bestTie)) {
        best = cat;
        bestCount = c;
        bestTie = tie;
      }
    }
    assigned.set(showKeyOf(item), best);
    counts.set(best, (counts.get(best) || 0) + 1);
  }

  // Rebalance underfull categories by moving multi-category shows out of overfull ones.
  const totalAssigned = [...assigned.keys()].length;
  const MIN_ITEMS = Math.min(12, Math.max(6, Math.floor(Math.sqrt(Math.max(1, totalAssigned))) + 2));
  const catKeysByAsc = [...otherCategories].sort((a, b) => (counts.get(a) || 0) - (counts.get(b) || 0));

  const itemCatsCache = new Map();
  const getCats = (item) => {
    const k = showKeyOf(item);
    if (itemCatsCache.has(k)) return itemCatsCache.get(k);
    const v = normCats(item.show.categories);
    itemCatsCache.set(k, v);
    return v;
  };

  for (const underCat of catKeysByAsc) {
    let underCount = counts.get(underCat) || 0;
    if (underCount >= MIN_ITEMS) continue;

    // Find candidates currently assigned elsewhere that also have underCat as a category.
    const candidates = [];
    const pool = categoryToShows.get(underCat) || [];
    for (const it of pool) {
      const key = showKeyOf(it);
      const curCat = assigned.get(key);
      if (!curCat || curCat === underCat) continue;
      candidates.push({ key, it, curCat });
    }
    if (!candidates.length) continue;

    // Move from the most overfull categories first.
    candidates.sort((a, b) => {
      const ca = counts.get(a.curCat) || 0;
      const cb = counts.get(b.curCat) || 0;
      if (cb !== ca) return cb - ca;
      return fnv1a32(`${daySeed}:${a.key}:${underCat}`) - fnv1a32(`${daySeed}:${b.key}:${underCat}`);
    });

    for (const c of candidates) {
      if (underCount >= MIN_ITEMS) break;
      const donorCount = counts.get(c.curCat) || 0;
      if (donorCount <= MIN_ITEMS) continue;
      // Ensure the show actually has underCat (and not just stale mapping).
      if (!getCats(c.it).includes(underCat)) continue;
      assigned.set(c.key, underCat);
      counts.set(c.curCat, Math.max(0, donorCount - 1));
      underCount++;
      counts.set(underCat, underCount);
    }
  }

  const byCat = new Map();
  for (const [key, cat] of assigned.entries()) {
    if (!cat) continue;
    if (!byCat.has(cat)) byCat.set(cat, []);
    const item = allKeys.get(key);
    if (item) byCat.get(cat).push(item);
  }

  for (const cat of shuffledCats) {
    const shows = byCat.get(cat) || [];
    if (shows.length) {
      const safeId = String(cat).replace(/[^a-z0-9_-]+/gi, "_");
      rows.push({ id: `cat-${safeId}`, label: titleCase(cat), shows: shuffledWithSeed(shows, daySeed + cat.length) });
    }
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
        <div class="browseAllContent" data-carousel-group="browseAll">
          ${categoryRows.map(
            (row) => html`
              <${VodCarouselRow} rowId=${row.id} title=${row.label} className="browseAllRow" key=${row.id}>
                ${row.shows.map(({ feedId, feedTitle, show }, idx) => {
                  const progress = getShowProgress(show, feedId, history, player);
                  const showTitle = show.title_full || show.title;
                  const posClass = titlePosClass(`${feedId}:${show.slug || show.id}`);
                  const total = progress.totalEpisodes || (show.episodeCount || 0);
                  const watched = progress.watchedCount || 0;
                  const resumeLabel = progress.resumeEpisode ? "Resume" : "Play";
                  const watchedPct = total > 0 ? Math.round((watched / total) * 100) : 0;
                  const thumbSeed = `${feedId}:${show.slug || show.id}`;
                  const initials = fallbackInitials(showTitle) || "TV";

                  return html`
                    <div class="vodCarouselItem vodCarouselItemShow" key=${feedId + ":" + show.id} data-carousel-idx=${idx}>
                      <div class=${"vodThumbWrap " + posClass}>
                        <button
                          class="vodThumbBtn"
                          type="button"
                          data-navitem="1"
                          aria-label=${showTitle || "Show"}
                          onClick=${() => playShow(feedId, show)}
                          onFocus=${(e) => {
                            try {
                              e.currentTarget.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "start" });
                            } catch {}
                          }}
                        >
                          <div class="vodThumb" style=${thumbFallbackStyle(thumbSeed)}>
                            <span class="vodThumbPlaceholder">${initials}</span>
                            ${show.artworkUrl
                              ? html`<img class="vodThumbImg" src=${show.artworkUrl} alt="" loading="lazy" onError=${onThumbImgError} />`
                              : ""}
                            ${(show.artworkOverlay || showTitle)
                              ? html`
                                  <span class="vodThumbTitle">
                                    <span class="vodThumbTitleBar">${show.artworkOverlay || showTitle}</span>
                                  </span>
                                `
                              : ""}
                            <span class="vodThumbMeta" aria-hidden="true">
                              <span class="vodThumbMetaTop">${feedTitle}</span>
                              <span class="vodThumbMetaMid">${resumeLabel} · ${total} eps${watched ? ` · ${watched} watched` : ""}</span>
                              ${watchedPct > 0
                                ? html`
                                    <span class="vodThumbMetaBar">
                                      <span class="vodThumbMetaBarFill" style=${{ width: `${watchedPct}%` }}></span>
                                    </span>
                                  `
                                : ""}
                            </span>
                          </div>
                        </button>
                        ${onShowClick
                          ? html`
                              <button
                                class="vodThumbIcon"
                                type="button"
                                data-navitem="1"
                                aria-label="View episodes"
                                title="Episodes"
                                onClick=${() => onShowClick?.(feedId, show)}
                              >
                                ≡
                              </button>
                            `
                          : ""}
                      </div>
                    </div>
                  `;
                })}
              </${VodCarouselRow}>
            `
          )}
        </div>
      </div>
    </div>
  `;
}
