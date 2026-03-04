/**
 * Browse All: Netflix-style rows by category.
 * Featured (manual), Continue Watching (in-progress), then randomized category rows.
 */
import { html, useEffect, useMemo, useRef, useState, useSignal } from "../runtime/vendor.js";
import { fallbackInitials, thumbFallbackStyle, titlePosClass, VodCarouselRow } from "./vod_carousel.js";
import { HeadphonesIcon, TvIcon } from "./icons.js";

const BROWSE_ALL_PREFS_KEY = "vodcasts_browse_all_prefs_v2";

function loadBrowseAllPrefs() {
  try {
    const raw = JSON.parse(localStorage.getItem(BROWSE_ALL_PREFS_KEY) || "{}");
    const showAudioOnlyFeeds = raw?.showAudioOnlyFeeds !== false;
    return { showAudioOnlyFeeds };
  } catch {
    return { showAudioOnlyFeeds: true };
  }
}

function saveBrowseAllPrefs({ showAudioOnlyFeeds }) {
  try {
    localStorage.setItem(BROWSE_ALL_PREFS_KEY, JSON.stringify({ showAudioOnlyFeeds: showAudioOnlyFeeds !== false }));
  } catch {}
}

function onThumbImgError(e) {
  try {
    const img = e.currentTarget;
    img.style.display = "none";
  } catch {}
}

function isVideoEpisode(ep) {
  const m = ep?.media || null;
  if (!m) return false;
  if (m.pickedIsVideo === true) return true;
  if (m.pickedIsVideo === false) return false;
  const t = String(m.type || "").toLowerCase();
  if (t.startsWith("video/")) return true;
  if (t.startsWith("audio/")) return false;
  const u = String(m.url || "").toLowerCase();
  if (u.includes(".m3u8")) return true;
  if (u.match(/\.(mp4|m4v|mov|webm)(\?|$)/)) return true;
  if (u.match(/\.(mp3|m4a|aac|ogg|opus)(\?|$)/)) return false;
  return false;
}

function getShowProgress(show, feedId, historyFeedEntries, player) {
  const episodes = show.episodes || [];
  const total = episodes.length;
  if (total === 0) return { watchedCount: 0, resumeEpisode: null, totalEpisodes: 0 };
  const hist = Array.isArray(historyFeedEntries) ? historyFeedEntries : [];
  if (!hist.length) return { watchedCount: 0, resumeEpisode: null, totalEpisodes: total };

  const histEpIds = new Set();
  for (const e of hist) {
    const eid = e?.episodeId;
    if (typeof eid === "string" && eid) histEpIds.add(eid);
  }
  if (!histEpIds.size) return { watchedCount: 0, resumeEpisode: null, totalEpisodes: total };

  const WATCHED_THRESHOLD = 0.9;
  let watchedCount = 0;
  let resumeEpisode = null;
  let bestProgress = 0;
  for (const ep of episodes) {
    if (!histEpIds.has(ep?.id)) continue;
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
    let bestAt = 0;
    let bestId = null;
    for (const e of hist) {
      if (typeof e?.episodeId !== "string" || !e.episodeId) continue;
      if (!histEpIds.has(e.episodeId)) continue;
      const at = Number(e?.at) || 0;
      if (at > bestAt) {
        bestAt = at;
        bestId = e.episodeId;
      }
    }
    if (bestId) resumeEpisode = episodes.find((x) => x?.id === bestId) || null;
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
function buildCategoryRows(allShows, historyAll, player) {
  const histAll = Array.isArray(historyAll) ? historyAll : [];
  const byShowKey = (feedId, showId) => `${feedId}::${showId}`;

  const continueWatching = [];
  const lastWatchedAt = new Map();
  const itemsByFeed = new Map();
  for (const it of allShows) {
    if (!itemsByFeed.has(it.feedId)) itemsByFeed.set(it.feedId, []);
    itemsByFeed.get(it.feedId).push(it);
  }

  const epIndexByFeed = new Map(); // feedId -> Map(episodeId -> { item, ep })
  const ensureEpIndex = (feedId) => {
    if (epIndexByFeed.has(feedId)) return epIndexByFeed.get(feedId);
    const idx = new Map();
    const items = itemsByFeed.get(feedId) || [];
    for (const item of items) {
      const show = item.show;
      const eps = show?.episodes || [];
      if (!Array.isArray(eps) || !eps.length) continue;
      for (const ep of eps) {
        const eid = ep?.id;
        if (typeof eid !== "string" || !eid) continue;
        if (!idx.has(eid)) idx.set(eid, { item, ep });
      }
    }
    epIndexByFeed.set(feedId, idx);
    return idx;
  };

  const WATCHED_THRESHOLD = 0.9;
  const seen = new Set();
  const recent = histAll.slice(0, 600);
  for (const e of recent) {
    const feedId = e?.sourceId;
    const episodeId = e?.episodeId;
    if (typeof feedId !== "string" || !feedId) continue;
    if (typeof episodeId !== "string" || !episodeId) continue;
    if (!itemsByFeed.has(feedId)) continue;
    const at = Number(e?.at) || 0;
    const idx = ensureEpIndex(feedId);
    const hit = idx.get(episodeId);
    if (!hit) continue;
    const { item, ep } = hit;
    const key = byShowKey(feedId, item.show.id);
    if (seen.has(key)) continue;
    const maxProg = player?.getProgressMaxSec?.(feedId, episodeId) ?? 0;
    if (!(maxProg > 0)) continue;
    const dur = ep?.durationSec;
    const isWatched = Number.isFinite(dur) && dur > 0 ? maxProg >= dur * WATCHED_THRESHOLD : maxProg > 60;
    if (isWatched) continue;
    seen.add(key);
    lastWatchedAt.set(key, at);
    continueWatching.push(item);
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

  const titleCase = (s) => String(s || "").replace(/\b\w/g, (c) => c.toUpperCase());
  const rows = [];
  if (featured.length) rows.push({ id: "featured", label: "Featured", shows: shuffledWithSeed(featured, daySeed + 1), cats: [] });
  if (continueWatching.length) rows.push({ id: "continue", label: "Continue Watching", shows: continueWatching, cats: [] });

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

  const guessProfile = (countsMap) => {
    const n = (c) => countsMap.get(c) || 0;
    const hasChurch =
      n("sermons") +
        n("worship") +
        n("praise") +
        n("devotional") +
        n("bible-study") +
        n("teaching") +
        n("tv-ministry") >
      6;
    if (hasChurch) return "church";
    const hasTech = n("tech") + n("dev") + n("security") + n("programming") + n("keynotes") > 6;
    if (hasTech) return "tech";
    if (n("news") > 6) return "news";
    return "general";
  };

  const profile = guessProfile(counts);
  const tierOf = (cat) => {
    const c = String(cat || "").trim().toLowerCase();
    if (!c) return 9;
    const inSet = (set) => set.has(c);

    const churchCore = new Set([
      "sermons",
      "worship",
      "praise",
      "devotional",
      "bible-study",
      "teaching",
      "prayer",
      "tv-ministry",
      "apologetics",
      "theology",
      "discipleship",
      "family",
      "kids",
      "hymns",
      "music",
    ]);
    const techCore = new Set(["tech", "dev", "programming", "security", "keynotes"]);

    if (profile === "church") {
      if (inSet(churchCore)) return 0;
      if (c === "news") return 1;
      if (c === "science" || c === "lectures") return 2;
      if (inSet(techCore)) return 3;
      if (c === "lifestyle" || c === "radio") return 3;
      return 2;
    }

    if (profile === "tech") {
      if (inSet(techCore)) return 0;
      if (c === "news") return 1;
      if (c === "science" || c === "lectures") return 2;
      if (inSet(churchCore)) return 3;
      if (c === "lifestyle" || c === "radio") return 3;
      return 2;
    }

    if (profile === "news") {
      if (c === "news") return 0;
      if (c === "science") return 1;
      if (c === "lectures") return 2;
      if (inSet(churchCore)) return 2;
      return 3;
    }

    // general: size-first, keep obviously "core" categories early-ish
    if (c === "news") return 1;
    if (c === "science" || c === "lectures") return 2;
    if (inSet(churchCore) || inSet(techCore)) return 1;
    return 3;
  };

  // Order categories by: tier (audience relevance), size (row fullness), then a small daily jitter.
  const orderedCats = [...otherCategories]
    .filter((cat) => (byCat.get(cat) || []).length)
    .map((cat) => {
      const count = (counts.get(cat) || 0) | 0;
      const jitter01 = (fnv1a32(`${daySeed}:${profile}:${cat}`) % 1000) / 1000;
      const jitter = (jitter01 - 0.5) * 0.18; // ±9% size variance, seeded daily
      const effective = count * (1 + jitter);
      return { cat, tier: tierOf(cat), count, effective, jitter01 };
    })
    .sort((a, b) => {
      if (a.tier !== b.tier) return a.tier - b.tier;
      if (a.effective !== b.effective) return b.effective - a.effective;
      // Stable daily tie-break
      return a.jitter01 - b.jitter01;
    })
    .map((x) => x.cat);

  for (const cat of orderedCats) {
    const shows = byCat.get(cat) || [];
    if (shows.length) {
      const safeId = String(cat).replace(/[^a-z0-9_-]+/gi, "_");
      rows.push({ id: `cat-${safeId}`, label: titleCase(cat), shows: shuffledWithSeed(shows, daySeed + cat.length), cats: [cat] });
    }
  }

  // Merge small neighboring category rows into a longer row to reduce visual clutter and
  // improve scroll performance. Cap at ~4 categories or ~12 shows in the merged row.
  // (Featured / Continue rows are never merged.)
  const MAX_MERGE_CATS = 4;
  const MAX_MERGE_SHOWS = 12;
  const SMALL_ROW_MAX_SHOWS = Math.max(3, Math.min(6, Math.floor(MIN_ITEMS / 2)));
  const merged = [];
  const uniqKey = (it) => `${it?.feedId || ""}::${it?.show?.id || it?.show?.slug || ""}`;

  for (let i = 0; i < rows.length; i++) {
    const r = rows[i];
    const isCatRow = typeof r?.id === "string" && r.id.startsWith("cat-");
    const canMergeStart = isCatRow && Array.isArray(r.shows) && r.shows.length > 0 && r.shows.length <= SMALL_ROW_MAX_SHOWS;
    if (!canMergeStart) {
      merged.push(r);
      continue;
    }

    const take = [r];
    let takeShows = r.shows.length;
    while (i + 1 < rows.length) {
      const nxt = rows[i + 1];
      const isNextCat = typeof nxt?.id === "string" && nxt.id.startsWith("cat-");
      if (!isNextCat) break;
      if (!Array.isArray(nxt.shows) || !nxt.shows.length) break;
      if (nxt.shows.length > SMALL_ROW_MAX_SHOWS) break;
      if (take.length >= MAX_MERGE_CATS) break;
      if (takeShows + nxt.shows.length > MAX_MERGE_SHOWS) break;
      take.push(nxt);
      takeShows += nxt.shows.length;
      i++;
    }

    if (take.length === 1) {
      merged.push(r);
      continue;
    }

    const label = take.map((x) => x.label).filter(Boolean).join(" • ");
    const cats = take.flatMap((x) => (Array.isArray(x.cats) ? x.cats : [])).filter(Boolean);
    const seen = new Set();
    const combined = [];
    for (const t of take) {
      for (const it of t.shows || []) {
        const k = uniqKey(it);
        if (!k || seen.has(k)) continue;
        seen.add(k);
        combined.push(it);
      }
    }
    const mergeId = `cat-merged-${fnv1a32(cats.join("|") || label || take.map((x) => x.id).join("|"))}`;
    merged.push({
      id: mergeId,
      label,
      shows: shuffledWithSeed(combined, daySeed + (fnv1a32(mergeId) % 1000)),
      cats,
    });
  }

  return merged;
}

function BrowseAllRowPlaceholder({ rowId, title, count = 10 }) {
  const items = [];
  const n = Math.max(6, Math.min(14, Number(count) || 10));
  for (let i = 0; i < n; i++) items.push(i);
  return html`
    <section class="vodCarouselRow browseAllRow browseAllRowPlaceholder" data-carousel-rowroot=${rowId}>
      ${title ? html`<h3 class="vodCarouselTitle">${title}</h3>` : ""}
      <div class="vodCarouselViewport">
        <div class="vodCarouselStrip">
          <div class="vodCarouselStripInner" data-carousel-row=${rowId}>
            ${items.map(
              (i) => html`
                <div class="vodCarouselItem vodCarouselItemShow vodCarouselItemSkeleton" key=${rowId + ":" + i}>
                  <div class="vodThumbWrap">
                    <div class="vodThumb vodThumbSkeleton"></div>
                  </div>
                </div>
              `
            )}
          </div>
        </div>
      </div>
    </section>
  `;
}

export function BrowseAllPanel({ env, isOpen, showsConfig, feedTitles, player, history, onClose, onShowClick }) {
  const browseLogoUrl = String(env?.site?.browseLogoUrl || "").trim();
  const curSourceId = player?.currentSourceId?.value || null;
  const curEpId = player?.currentEpisodeId?.value || null;

  const feeds = showsConfig?.feeds || {};
  const titles = feedTitles || {};

  const prefsInitRef = useRef(loadBrowseAllPrefs());
  const showAudioOnlyFeeds = useSignal(prefsInitRef.current.showAudioOnlyFeeds !== false);
  useEffect(() => {
    saveBrowseAllPrefs({ showAudioOnlyFeeds: showAudioOnlyFeeds.value });
  }, [showAudioOnlyFeeds.value]);

  const feedAudioOnlyIds = useMemo(() => {
    const out = new Set();
    for (const feedId of Object.keys(feeds)) {
      const shows = feeds[feedId];
      if (!Array.isArray(shows) || !shows.length) continue;
      let hasVideo = false;
      for (const show of shows) {
        const eps = show?.episodes || [];
        if (!Array.isArray(eps) || !eps.length) continue;
        for (const ep of eps) {
          if (isVideoEpisode(ep)) {
            hasVideo = true;
            break;
          }
        }
        if (hasVideo) break;
      }
      if (!hasVideo) out.add(feedId);
    }
    return out;
  }, [feeds]);

  const totalFeedCount = useMemo(() => Object.keys(feeds).length, [feeds]);
  const audioOnlyFeedCount = feedAudioOnlyIds.size;
  const visibleFeedCount = showAudioOnlyFeeds.value ? totalFeedCount : Math.max(0, totalFeedCount - audioOnlyFeedCount);

  const allShows = useMemo(() => {
    const out = [];
    for (const [feedId, shows] of Object.entries(feeds)) {
      if (!Array.isArray(shows)) continue;
      if (!showAudioOnlyFeeds.value && feedAudioOnlyIds.has(feedId)) continue;
      const feedTitle = titles[feedId] || feedId;
      for (const show of shows) {
        const eps = show.episodes || [];
        if (!eps.length) continue;
        out.push({ feedId, feedTitle, show });
      }
    }
    return out;
  }, [feeds, titles, showAudioOnlyFeeds.value, feedAudioOnlyIds]);

  const historyAll = history?.all?.value || [];
  const historyByFeed = useMemo(() => {
    const m = new Map();
    const arr = Array.isArray(historyAll) ? historyAll : [];
    for (const e of arr) {
      const feedId = e?.sourceId;
      if (typeof feedId !== "string" || !feedId) continue;
      if (!m.has(feedId)) m.set(feedId, []);
      m.get(feedId).push(e);
    }
    return m;
  }, [historyAll]);

  const categoryRows = useMemo(() => buildCategoryRows(allShows, historyAll, player), [allShows, historyAll, player]);

  const rowElsRef = useRef(new Map());
  const visibleIdxRef = useRef(new Set());
  const observerRef = useRef(null);
  const [rowWindow, setRowWindow] = useState({ start: 0, end: 6 });

  useEffect(() => {
    if (!isOpen) return;
    const content = document.querySelector("#browseAllPanel .browseAllContent");
    if (!content) return;
    visibleIdxRef.current = new Set([0, 1, 2]);
    setRowWindow({ start: 0, end: Math.min(6, Math.max(0, categoryRows.length - 1)) });

    const observer = new IntersectionObserver(
      (entries) => {
        let changed = false;
        for (const e of entries) {
          const idx = Number(e.target?.getAttribute?.("data-row-idx"));
          if (!Number.isFinite(idx)) continue;
          if (e.isIntersecting) {
            if (!visibleIdxRef.current.has(idx)) {
              visibleIdxRef.current.add(idx);
              changed = true;
            }
          } else {
            if (visibleIdxRef.current.delete(idx)) changed = true;
          }
        }
        if (!changed) return;
        const arr = [...visibleIdxRef.current].sort((a, b) => a - b);
        const min = arr.length ? arr[0] : 0;
        const max = arr.length ? arr[arr.length - 1] : min;
        const start = Math.max(0, min - 2);
        const end = Math.min(categoryRows.length - 1, max + 3);
        setRowWindow({ start, end });
      },
      { root: content, rootMargin: "700px 0px 700px 0px", threshold: 0.01 }
    );
    observerRef.current = observer;

    for (const el of rowElsRef.current.values()) {
      try {
        observer.observe(el);
      } catch {}
    }
    return () => {
      try {
        observer.disconnect();
      } catch {}
      observerRef.current = null;
    };
  }, [isOpen, categoryRows.length]);

  useEffect(() => {
    if (!isOpen) return;
    const panel = document.getElementById("browseAllPanel");
    if (!panel) return;
    const a = document.activeElement;
    if (a && panel.contains(a)) return;
    const playingBtn =
      panel.querySelector(".vodCarouselItem.playing .vodThumbBtn[data-navitem='1']") ||
      panel.querySelector(".vodCarouselItem.playing [data-navitem='1']");
    if (playingBtn && typeof playingBtn.focus === "function") {
      try {
        playingBtn.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "start" });
      } catch {}
      try {
        playingBtn.focus();
      } catch {}
    }
  }, [isOpen, curSourceId, curEpId, categoryRows.length]);

  const playShow = (feedId, show, startEp = null) => {
    const episodes = show.episodes || [];
    if (!episodes.length || !feedId) return;
    const progress = getShowProgress(show, feedId, historyByFeed.get(feedId), player);
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
            <div class="browseAllHeaderLeft">
              <button class="browseAllBack" type="button" onClick=${() => onClose?.()} aria-label="Back" title="Back">←</button>
              ${browseLogoUrl ? html`<img class="browseAllLogo" src=${browseLogoUrl} alt="" aria-hidden="true" />` : ""}
              <h2 class="browseAllTitle">Browse Shows</h2>
            </div>
            <div class="browseAllHeaderActions">
              <button
                class=${"browseAllHeaderBtn browseAllHeaderBtnAudioOnly" + (showAudioOnlyFeeds.value ? "" : " active")}
                type="button"
                aria-pressed=${showAudioOnlyFeeds.value ? "false" : "true"}
                title=${showAudioOnlyFeeds.value ? "Audio-only feeds visible" : "Audio-only feeds hidden"}
                aria-label=${showAudioOnlyFeeds.value ? "Audio-only feeds visible" : "Audio-only feeds hidden"}
                onClick=${() => {
                  showAudioOnlyFeeds.value = !showAudioOnlyFeeds.value;
                }}
              >
                ${showAudioOnlyFeeds.value
                  ? html`<${HeadphonesIcon} size=${14} /> All ${visibleFeedCount}/${totalFeedCount}`
                  : html`<${TvIcon} size=${14} /> TV ${visibleFeedCount}/${totalFeedCount}`}
              </button>
              <button class="browseAllClose" type="button" onClick=${onClose} aria-label="Close">×</button>
            </div>
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
          <div class="browseAllHeaderLeft">
            <button class="browseAllBack" type="button" onClick=${() => onClose?.()} aria-label="Back" title="Back">←</button>
            ${browseLogoUrl ? html`<img class="browseAllLogo" src=${browseLogoUrl} alt="" aria-hidden="true" />` : ""}
            <h2 class="browseAllTitle">Browse Shows</h2>
          </div>
          <div class="browseAllHeaderActions">
            <button
              class=${"browseAllHeaderBtn browseAllHeaderBtnAudioOnly" + (showAudioOnlyFeeds.value ? "" : " active")}
              type="button"
              aria-pressed=${showAudioOnlyFeeds.value ? "false" : "true"}
              title=${showAudioOnlyFeeds.value ? "Audio-only feeds visible" : "Audio-only feeds hidden"}
              aria-label=${showAudioOnlyFeeds.value ? "Audio-only feeds visible" : "Audio-only feeds hidden"}
              onClick=${() => {
                showAudioOnlyFeeds.value = !showAudioOnlyFeeds.value;
              }}
            >
              ${showAudioOnlyFeeds.value
                ? html`<${HeadphonesIcon} size=${14} /> All ${visibleFeedCount}/${totalFeedCount}`
                : html`<${TvIcon} size=${14} /> TV ${visibleFeedCount}/${totalFeedCount}`}
            </button>
            <button class="browseAllClose" type="button" onClick=${onClose} aria-label="Close">×</button>
          </div>
        </header>
        <div class="browseAllContent" data-carousel-group="browseAll">
          ${categoryRows.map(
            (row, rowIdx) => {
              const isActive = rowIdx >= rowWindow.start && rowIdx <= rowWindow.end;
              return html`
                <div
                  class="browseAllRowMount"
                  key=${row.id}
                  data-row-idx=${rowIdx}
                  ref=${(el) => {
                    if (el) {
                      rowElsRef.current.set(rowIdx, el);
                      try {
                        observerRef.current?.observe?.(el);
                      } catch {}
                    } else {
                      rowElsRef.current.delete(rowIdx);
                    }
                  }}
                >
                  ${isActive
                    ? html`
                        <${VodCarouselRow} rowId=${row.id} title=${row.label} className="browseAllRow">
                          ${row.shows.map(({ feedId, feedTitle, show }, idx) => {
                            const progress = getShowProgress(show, feedId, historyByFeed.get(feedId), player);
                            const showTitle = show.title_full || show.title;
                            const posClass = titlePosClass(`${feedId}:${show.slug || show.id}`);
                            const eps = show.episodes || [];
                            const isPlayingShow = curSourceId === feedId && curEpId && eps.some((e) => e?.id === curEpId);
                            const isAudioOnlyFeed = feedAudioOnlyIds.has(feedId);
                            const total = progress.totalEpisodes || (show.episodeCount || 0);
                            const watched = progress.watchedCount || 0;
                            const resumeLabel = progress.resumeEpisode ? "Resume" : "Play";
                            const watchedPct = total > 0 ? Math.round((watched / total) * 100) : 0;
                            const thumbSeed = `${feedId}:${show.slug || show.id}`;
                            const initials = fallbackInitials(showTitle) || "TV";

                            return html`
                              <div class=${"vodCarouselItem vodCarouselItemShow" + (isPlayingShow ? " playing" : "")} key=${feedId + ":" + show.id} data-carousel-idx=${idx}>
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
                                      ${isPlayingShow ? html`<span class="vodThumbBadge" aria-hidden="true">Playing</span>` : ""}
                                      ${isAudioOnlyFeed
                                        ? html`<span class="vodThumbAudio" aria-hidden="true" title="Audio-only feed"><${HeadphonesIcon} size=${16} /></span>`
                                        : ""}
                                      ${(show.artworkOverlay || showTitle)
                                        ? html`
                                            <span class="vodThumbTitle">
                                              <span class="vodThumbTitleBar">${show.artworkOverlay || showTitle}</span>
                                            </span>
                                          `
                                        : ""}
                                      <span class="vodThumbMeta" aria-hidden="true">
                                        <span class="vodThumbMetaTop">
                                          ${isAudioOnlyFeed
                                            ? html`<span class="vodThumbFeedAudioIcon" aria-hidden="true"><${HeadphonesIcon} size=${12} /></span>`
                                            : ""}
                                          ${feedTitle}
                                        </span>
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
                    : html`<${BrowseAllRowPlaceholder} rowId=${row.id} title=${row.label} />`}
                </div>
              `;
            }
          )}
        </div>
      </div>
    </div>
  `;
}
