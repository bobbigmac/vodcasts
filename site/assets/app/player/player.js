import { computed, effect, signal } from "../runtime/vendor.js";
import { fetchCached } from "../vod/feed_cache.js";
import { parseFeedXml } from "../vod/feed_parse.js";
import { loadChaptersForEpisode } from "../ui/chapters.js";

export function createPlayerService({ env, log, history }) {
  const STORAGE_KEY = "vodcasts_state_v1";
  const FEED_PROXY = env.feedProxy;

  let videoEl = null;
  let hls = null;
  let transcriptBlobUrls = [];
  let lastPersistMs = 0;

  let sources = [];
  let currentSource = null;
  let episodes = [];
  let episodesBySource = {};
  let currentEp = null;

  let userPaused = false;
  let didInitLoad = false;
  let pendingInitSourceId = null;
  let pendingInitRoute = null;

  let sleepEndAt = null;
  let sleepTickId = null;

  let shuffleTickId = null;
  let shuffleBusy = false;

  const persisted = loadState();

  const current = signal({ source: null, episode: null });
  const chapters = signal([]);
  const VOLUME_STEP = 0.1;
  const DEFAULT_RATE_STEPS = [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2, 2.5, 3, 3.5, 4, 4.5, 5, 7, 12];
  const SHUFFLE_INTERVALS = [
    { label: "10s", ms: 10 * 1000 },
    { label: "30s", ms: 30 * 1000 },
    { label: "1m", ms: 60 * 1000 },
    { label: "2m", ms: 2 * 60 * 1000 },
    { label: "5m", ms: 5 * 60 * 1000 },
    { label: "10m", ms: 10 * 60 * 1000 },
    { label: "20m", ms: 20 * 60 * 1000 },
    { label: "30m", ms: 30 * 60 * 1000 },
    { label: "1hr", ms: 60 * 60 * 1000 },
    { label: "2hr", ms: 2 * 60 * 60 * 1000 },
    { label: "3hr", ms: 3 * 60 * 60 * 1000 },
  ];
  const DEFAULT_SHUFFLE = { active: false, nextAt: null, intervalIdx: 4, changeFeed: true, changeEpisode: true, changeTime: true };
  const playback = signal({
    paused: true,
    muted: true,
    volume: Number(persisted.volume) >= 0 ? clamp(Number(persisted.volume), 0, 1) : 1,
    rate: 1,
    time: 0,
    duration: NaN,
  });
  const captions = signal({ available: false, showing: false });
  const sleep = signal({ active: false, label: "" });
  const sourceEpisodes = signal({});
  const audioBlocked = signal(false);
  const loading = signal(false);
  const chaptersLoadError = signal(null);
  const transcriptsLoadError = signal(null);
  const subtitleBox = signal(null);
  const subtitleCue = signal(null);
  const skip = signal(normalizeSkip(persisted.skip));
  const rateSteps = signal(normalizeRateSteps(persisted.rateSteps) || DEFAULT_RATE_STEPS.slice());
  const shuffle = signal({ ...normalizeShuffle(persisted.shuffle), label: "" });

  const currentSourceId = computed(() => current.value.source?.id || null);
  const currentEpisodeId = computed(() => current.value.episode?.id || null);

  const DEFAULT_SUBTITLE_PREFS = { x: 50, y: 78, w: 92, opacity: 1, scale: 1 };

  function loadState() {
    try {
      const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
      return raw && typeof raw === "object" ? raw : {};
    } catch {
      return {};
    }
  }
  function saveState() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(persisted));
    } catch {}
  }

  function clamp(v, a, b) {
    return Math.min(b, Math.max(a, v));
  }

  function normalizeSkip(input) {
    const s = input && typeof input === "object" ? input : {};
    return {
      back: Number.isFinite(Number(s.back)) ? clamp(Math.round(Number(s.back)), 5, 120) : 10,
      fwd: Number.isFinite(Number(s.fwd)) ? clamp(Math.round(Number(s.fwd)), 5, 180) : 30,
    };
  }

  function normalizeRateSteps(v) {
    const list = Array.isArray(v) ? v : [];
    const out = [];
    const seen = new Set();
    for (const r0 of list) {
      const r = Number(r0);
      if (!Number.isFinite(r) || r <= 0) continue;
      const clamped = clamp(r, 0.25, 12);
      const key = Math.round(clamped * 1000) / 1000;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(key);
    }
    if (!out.includes(1)) out.push(1);
    out.sort((a, b) => a - b);
    return out.length ? out : null;
  }

  function normalizeShuffle(input) {
    const s = input && typeof input === "object" ? input : {};
    const intervalIdx0 = Number.isFinite(Number(s.intervalIdx)) ? Math.round(Number(s.intervalIdx)) : DEFAULT_SHUFFLE.intervalIdx;
    const intervalIdx = clamp(intervalIdx0, 0, SHUFFLE_INTERVALS.length - 1);

    const changeFeed = s.changeFeed !== false;
    const changeEpisode = s.changeEpisode !== false;
    const changeTime = s.changeTime !== false;
    const hasAny = changeFeed || changeEpisode || changeTime;

    const nextAt = Number.isFinite(Number(s.nextAt)) ? Number(s.nextAt) : null;
    return {
      active: !!s.active,
      nextAt,
      intervalIdx,
      changeFeed: hasAny ? changeFeed : DEFAULT_SHUFFLE.changeFeed,
      changeEpisode: hasAny ? changeEpisode : DEFAULT_SHUFFLE.changeEpisode,
      changeTime: hasAny ? changeTime : DEFAULT_SHUFFLE.changeTime,
    };
  }

  function normalizeRate(v, steps = DEFAULT_RATE_STEPS) {
    if (!Number.isFinite(v) || v <= 0) return 1;
    const arr = steps && steps.length ? steps : DEFAULT_RATE_STEPS;
    let best = arr[0];
    let bestDist = Math.abs(v - best);
    for (let i = 1; i < arr.length; i++) {
      const r = arr[i];
      const d = Math.abs(v - r);
      if (d < bestDist) {
        best = r;
        bestDist = d;
      }
    }
    return best;
  }

  function fmtTime(s) {
    if (!Number.isFinite(s) || s < 0) return "00:00";
    const hh = Math.floor(s / 3600);
    const mm = Math.floor((s % 3600) / 60);
    const ss = Math.floor(s % 60);
    if (hh > 0) return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
    return `${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
  }

  function shuffleLeftLabel(nextAt) {
    if (!Number.isFinite(nextAt)) return "";
    const leftMs = nextAt - Date.now();
    const leftSec = Math.max(0, Math.ceil(leftMs / 1000));
    return fmtTime(leftSec);
  }

  function persistShuffle(next) {
    const s = next && typeof next === "object" ? next : shuffle.value;
    persisted.shuffle = {
      active: !!s.active,
      nextAt: Number.isFinite(Number(s.nextAt)) ? Number(s.nextAt) : null,
      intervalIdx: clamp(Math.round(Number(s.intervalIdx) || 0), 0, SHUFFLE_INTERVALS.length - 1),
      changeFeed: s.changeFeed !== false,
      changeEpisode: s.changeEpisode !== false,
      changeTime: s.changeTime !== false,
    };
    saveState();
  }

  function ensureShuffleTick() {
    if (!shuffle.value.active) {
      if (shuffleTickId) clearInterval(shuffleTickId);
      shuffleTickId = null;
      shuffleBusy = false;
      return;
    }
    if (shuffleTickId) return;
    shuffleTickId = setInterval(() => shuffleTick(), 400);
  }

  function setShuffleSettings(nextPartial, { resetNextAt = false } = {}) {
    const cur = shuffle.value;
    const next = { ...cur, ...(nextPartial && typeof nextPartial === "object" ? nextPartial : {}) };
    const any = !!next.changeFeed || !!next.changeEpisode || !!next.changeTime;
    if (!any) {
      next.changeFeed = cur.changeFeed;
      next.changeEpisode = cur.changeEpisode;
      next.changeTime = cur.changeTime;
    }
    next.intervalIdx = clamp(Math.round(Number(next.intervalIdx) || 0), 0, SHUFFLE_INTERVALS.length - 1);
    if (resetNextAt && next.active) next.nextAt = Date.now() + SHUFFLE_INTERVALS[next.intervalIdx].ms;
    next.label = next.active ? shuffleLeftLabel(next.nextAt) : "";
    shuffle.value = next;
    persistShuffle(next);
    ensureShuffleTick();
  }

  function startShuffle() {
    const cur = shuffle.value;
    const intervalIdx = clamp(Math.round(Number(cur.intervalIdx) || DEFAULT_SHUFFLE.intervalIdx), 0, SHUFFLE_INTERVALS.length - 1);
    const now = Date.now();
    const nextAt0 = Number.isFinite(Number(cur.nextAt)) ? Number(cur.nextAt) : null;
    const nextAt = nextAt0 && nextAt0 > now ? nextAt0 : now + SHUFFLE_INTERVALS[intervalIdx].ms;
    setShuffleSettings({ active: true, intervalIdx, nextAt }, { resetNextAt: false });
  }

  function stopShuffle() {
    const next = { ...shuffle.value, active: false, nextAt: null, label: "" };
    shuffle.value = next;
    persistShuffle(next);
    ensureShuffleTick();
  }

  function toggleShuffle() {
    if (shuffle.value.active) stopShuffle();
    else startShuffle();
  }

  function pickRandomId(list, { exclude } = {}) {
    const arr = Array.isArray(list) ? list : [];
    if (!arr.length) return null;
    if (arr.length === 1) return arr[0];
    for (let i = 0; i < 6; i++) {
      const v = arr[Math.floor(Math.random() * arr.length)];
      if (exclude == null || v !== exclude) return v;
    }
    return arr[Math.floor(Math.random() * arr.length)];
  }

  function scheduleShuffleSoon(ms = 15000) {
    const intervalIdx = clamp(Math.round(Number(shuffle.value.intervalIdx) || 0), 0, SHUFFLE_INTERVALS.length - 1);
    const nextAt = Date.now() + Math.max(1000, Math.min(ms, SHUFFLE_INTERVALS[intervalIdx].ms));
    setShuffleSettings({ nextAt }, { resetNextAt: false });
  }

  function scheduleNextShuffle() {
    const intervalIdx = clamp(Math.round(Number(shuffle.value.intervalIdx) || 0), 0, SHUFFLE_INTERVALS.length - 1);
    const nextAt = Date.now() + SHUFFLE_INTERVALS[intervalIdx].ms;
    setShuffleSettings({ nextAt }, { resetNextAt: false });
  }

  function seekRandomTimeSoon() {
    if (!videoEl) return;
    const apply = () => {
      if (!videoEl) return;
      const dur = videoEl.duration;
      if (!Number.isFinite(dur) || dur <= 2) return;
      const max = Math.max(0, dur - 20);
      if (max <= 1) return;
      const t = Math.random() * max;
      if (t > 0.25) videoEl.currentTime = t;
    };
    if (Number.isFinite(videoEl.duration) && videoEl.duration > 0) apply();
    else videoEl.addEventListener("loadedmetadata", apply, { once: true });
  }

  async function doShuffleNow() {
    if (!shuffle.value.active) return;
    if (!sources.length) return;
    if (!videoEl) return;
    if (loading.value) return;

    const pb = playback.value;
    if (pb.paused || pb.ended) return;

    const cfg = shuffle.value;
    const doFeed = !!cfg.changeFeed;
    const doEp = !!cfg.changeEpisode;
    const doTime = !!cfg.changeTime;

    if (doFeed) {
      const ids = sources.map((s) => s.id).filter(Boolean);
      const nextSourceId = pickRandomId(ids, { exclude: currentSource?.id || null }) || currentSource?.id || ids[0];
      const pickRandomEpisode = !!doEp;
      await selectSource(nextSourceId, {
        preserveEpisode: false,
        pickRandomEpisode,
        autoplay: true,
        ignoreLastBySource: true,
      });
      if (doTime) seekRandomTimeSoon();
      return;
    }

    if (doEp) {
      const playable = episodes.filter((e) => e.media?.url);
      const ids = playable.map((e) => e.id).filter(Boolean);
      const nextEpId = pickRandomId(ids, { exclude: currentEp?.id || null }) || currentEp?.id || ids[0];
      if (nextEpId) await selectEpisode(nextEpId, { autoplay: true });
      if (doTime) seekRandomTimeSoon();
      return;
    }

    if (doTime) {
      seekRandomTimeSoon();
    }
  }

  function shuffleTick() {
    if (!shuffle.value.active) {
      ensureShuffleTick();
      return;
    }
    const nextAt = shuffle.value.nextAt;
    if (!Number.isFinite(nextAt)) {
      scheduleNextShuffle();
      return;
    }
    const leftMs = nextAt - Date.now();
    if (leftMs <= 0) {
      if (shuffleBusy) return;
      shuffleBusy = true;
      Promise.resolve()
        .then(async () => {
          if (!videoEl || loading.value || playback.value.paused || playback.value.ended || !sources.length) {
            scheduleShuffleSoon(15000);
            return;
          }
          await doShuffleNow();
          scheduleNextShuffle();
        })
        .finally(() => {
          shuffleBusy = false;
        });
      return;
    }
    const label = shuffleLeftLabel(nextAt);
    if (label !== shuffle.value.label) shuffle.value = { ...shuffle.value, label };
  }

  function episodeKey(sourceId, episodeId) {
    return `${sourceId}::${episodeId}`;
  }

  function getProgressSec(sourceId, episodeId) {
    const v = persisted.progress?.[episodeKey(sourceId, episodeId)];
    return Number.isFinite(v) ? v : 0;
  }

  function setProgressSec(sourceId, episodeId, t) {
    persisted.progress ||= {};
    persisted.progress[episodeKey(sourceId, episodeId)] = Math.max(0, t || 0);
    persisted.last = { sourceId, episodeId, at: Date.now() };
    saveState();
  }

  function isProbablyHls(url, mime) {
    const u = String(url || "").toLowerCase();
    const t = String(mime || "").toLowerCase();
    if (u.includes(".m3u8")) return true;
    if (t.includes("application/vnd.apple.mpegurl")) return true;
    if (t.includes("application/x-mpegurl")) return true;
    return false;
  }

  function isNativeHls() {
    const can =
      videoEl?.canPlayType?.("application/vnd.apple.mpegurl") || videoEl?.canPlayType?.("application/x-mpegURL");
    return can === "probably" || can === "maybe";
  }

  function teardownPlayer() {
    transcriptBlobUrls.forEach((u) => URL.revokeObjectURL(u));
    transcriptBlobUrls = [];
    [...(videoEl?.querySelectorAll?.("track") || [])].forEach((t) => t.remove());
    captions.value = { available: false, showing: false };
    chapters.value = [];
    loading.value = false;

    if (hls) {
      try {
        hls.destroy();
      } catch {}
      hls = null;
    }
    videoEl?.pause?.();
    videoEl?.removeAttribute?.("src");
    try {
      videoEl?.load?.();
    } catch {}
  }

  async function waitForHlsJs(timeoutMs = 2500) {
    if (window.Hls && Hls.isSupported && Hls.isSupported()) return true;
    const t0 = Date.now();
    while (Date.now() - t0 < timeoutMs) {
      if (window.Hls && Hls.isSupported && Hls.isSupported()) return true;
      await new Promise((r) => setTimeout(r, 50));
    }
    return !!(window.Hls && Hls.isSupported && Hls.isSupported());
  }

  async function fetchText(url, fetchVia = "auto", { useCache = false } = {}) {
    const u = String(url || "");
    const isRemote = /^https?:\/\//i.test(u);
    const via = fetchVia === "auto" ? (isRemote ? (env.isDev ? "proxy" : "direct") : "direct") : fetchVia;
    const finalUrl = via === "proxy" && isRemote ? FEED_PROXY + encodeURIComponent(u) : u;
    if (useCache && isRemote) return fetchCached(finalUrl);
    const res = await fetch(finalUrl, { cache: "no-store" });
    if (!res.ok) throw new Error(`fetch ${res.status}`);
    return await res.text();
  }

  async function preloadCachedFeeds() {
    const cached = sources.filter((s) => s.has_cached_xml && s.feed_url);
    if (!cached.length) return;
    const results = await Promise.all(
      cached.map(async (src) => {
        try {
          const xmlText = await fetchText(src.feed_url, src.fetch_via || "auto", { useCache: false });
          const parsed = parseFeedXml(xmlText, src);
          return { sourceId: src.id, episodes: parsed.episodes };
        } catch (e) {
          log.warn(`Preload ${src.id}: ${String(e?.message || e)}`);
          return { sourceId: src.id, episodes: [] };
        }
      })
    );
    for (const { sourceId, episodes } of results) {
      episodesBySource[sourceId] = episodes;
    }
    sourceEpisodes.value = { ...episodesBySource };
  }

  async function loadSourceEpisodes(sourceId) {
    if (episodesBySource[sourceId]) return episodesBySource[sourceId];
    const src = sources.find((s) => s.id === sourceId);
    if (!src) return [];
    const xmlText = await fetchText(src.feed_url, src.fetch_via || "auto", { useCache: true });
    const parsed = parseFeedXml(xmlText, src);
    episodesBySource[sourceId] = parsed.episodes;
    sourceEpisodes.value = { ...episodesBySource };
    return parsed.episodes;
  }

  async function selectSource(
    sourceId,
    {
      preserveEpisode = true,
      pickRandomEpisode = false,
      skipAutoEpisode = false,
      autoplay = true,
      ignoreLastBySource = false,
      preferEpisodeId = null,
    } = {}
  ) {
    const src = sources.find((s) => s.id === sourceId) || sources[0];
    if (!src) return;
    currentSource = src;
    currentEp = null;
    current.value = { source: currentSource, episode: null };

    try {
      log.info(`Fetching feed: ${src.title || src.id}`);
      const xmlText = await fetchText(src.feed_url, src.fetch_via || "auto", { useCache: true });
      const parsed = parseFeedXml(xmlText, src);
      episodes = parsed.episodes;
      episodesBySource[src.id] = episodes;
      sourceEpisodes.value = { ...episodesBySource };

      const playable = episodes.filter((e) => e.media?.url);
      log.info(`${parsed.channelTitle}: ${playable.length} media (of ${episodes.length})`);

      let wanted = null;
      if (!skipAutoEpisode) {
        if (preferEpisodeId && playable.some((e) => e.id === preferEpisodeId)) {
          wanted = preferEpisodeId;
        } else if (pickRandomEpisode && playable.length) {
          wanted = playable[Math.floor(Math.random() * playable.length)].id;
        } else if (ignoreLastBySource) {
          wanted = playable[0]?.id || null;
        } else {
          const lastId =
            persisted.lastBySource?.[src.id] || (preserveEpisode && persisted.last?.sourceId === src.id ? persisted.last?.episodeId : null);
          const lastIsPlayable = lastId && playable.some((e) => e.id === lastId);
          wanted = (lastIsPlayable ? lastId : null) || playable[0]?.id || null;
        }
      }

      if (wanted) await selectEpisode(wanted, { autoplay: autoplay && !userPaused });
    } catch (e) {
      episodes = [];
      log.error(`Feed error: ${String(e?.message || e)} — ${src.feed_url}`);
    }
  }

  function resolveEpisodeIdBySlugOrId(epSlugOrId) {
    const q = String(epSlugOrId || "").trim();
    if (!q) return null;
    const bySlug = episodes.find((e) => String(e.slug || "").toLowerCase() === q.toLowerCase());
    if (bySlug?.id) return bySlug.id;
    const byId = episodes.find((e) => e.id === q);
    return byId?.id || null;
  }

  function firstPlayableEpisodeId() {
    const playable = episodes.filter((e) => e.media?.url);
    return playable[0]?.id || null;
  }

  async function applyRoute(route, { autoplay = true } = {}) {
    const feed = route?.feed ? String(route.feed) : "";
    const ep = route?.ep ? String(route.ep) : "";
    const t = Number(route?.t);
    if (!feed) return false;
    if (!sources.some((s) => s.id === feed)) return false;

    if (ep) {
      await selectSource(feed, { preserveEpisode: false, skipAutoEpisode: true, autoplay, ignoreLastBySource: true });
      const episodeId = resolveEpisodeIdBySlugOrId(ep) || firstPlayableEpisodeId();
      if (!episodeId) return true;
      await selectEpisode(episodeId, { autoplay, startAt: Number.isFinite(t) ? Math.max(0, t) : undefined });
      return true;
    }

    // Feed-only routes should not depend on local "last watched" state.
    await selectSource(feed, { preserveEpisode: false, skipAutoEpisode: false, autoplay, ignoreLastBySource: true });
    return true;
  }

  async function selectEpisode(episodeId, { autoplay = true, startAt: overrideStartAt } = {}) {
    const ep = episodes.find((e) => e.id === episodeId) || episodes.find((e) => e.media?.url);
    if (!ep || !currentSource) return;
    if (!ep.media?.url) return log.warn(`Episode "${(ep.title || "").slice(0, 40)}…": no media URL`);
    if (!videoEl) return log.error("Player: no <video> element attached");

    teardownPlayer();
    chaptersLoadError.value = null;
    transcriptsLoadError.value = null;
    loading.value = true;
    currentEp = ep;
    current.value = { source: currentSource, episode: currentEp };

    const startAt = overrideStartAt ?? getProgressSec(currentSource.id, ep.id) ?? 0;
    history.startSegment({
      sourceId: currentSource.id,
      episodeId: ep.id,
      episodeTitle: ep.title,
      channelTitle: ep.channelTitle || currentSource.title,
      startTime: startAt,
    });
    persisted.last = { sourceId: currentSource.id, episodeId: ep.id, at: Date.now() };
    persisted.lastBySource ||= {};
    persisted.lastBySource[currentSource.id] = ep.id;
    saveState();

    const mediaUrl = ep.media.url;
    const mediaType = ep.media.type || "";
    const shouldUseHls = isProbablyHls(mediaUrl, mediaType);
    const usingNative = shouldUseHls && isNativeHls();
    if (shouldUseHls && !usingNative && !window.Hls) {
      log.info("Waiting for hls.js…");
      await waitForHlsJs(2500);
    }
    const usingHlsJs = shouldUseHls && !usingNative && window.Hls && Hls.isSupported();

    if (shouldUseHls && !usingNative && !usingHlsJs) {
      log.error("HLS not supported");
      return;
    }

    if (usingNative) {
      videoEl.src = mediaUrl;
    } else if (usingHlsJs) {
      hls = new Hls({ enableWorker: true });
      hls.on(Hls.Events.ERROR, (_evt, data) => {
        if (data?.fatal) log.error(`HLS error: ${data?.type || "fatal"}`);
      });
      hls.loadSource(mediaUrl);
      hls.attachMedia(videoEl);
    } else {
      videoEl.src = mediaUrl;
    }

    videoEl.addEventListener(
      "loadedmetadata",
      () => {
        const dur = videoEl.duration;
        if (Number.isFinite(dur) && dur > 2) {
          const safe = startAt > dur - 20 ? 0 : clamp(startAt, 0, Math.max(0, dur - 0.25));
          if (safe > 0.25) videoEl.currentTime = safe;
        }
        if (autoplay) play({ userGesture: false });
      },
      { once: true }
    );

    await loadTranscripts(ep);
    await loadChapters(ep);
  }

  function srtToWebVTT(srt) {
    return (
      "WEBVTT\n\n" +
      String(srt || "")
        .replace(/\r\n/g, "\n")
        .replace(/\r/g, "\n")
        .replace(/(\d{2}:\d{2}:\d{2}),(\d{3})/g, "$1.$2")
        .trim()
    );
  }

  async function loadTranscripts(ep) {
    const list = ep.transcripts || [];
    if (!list.length || !videoEl) return;
    transcriptsLoadError.value = null;

    for (const t of list) {
      try {
        const isRemote = /^https?:\/\//i.test(t.url);
        const fetchOne = async (u) => {
          const res = await fetch(u, { cache: "no-store" });
          if (!res.ok) throw new Error(String(res.status));
          return res.text();
        };

        const directUrl = t.url;
        const proxyUrl = isRemote ? FEED_PROXY + encodeURIComponent(t.url) : t.url;
        let txt;
        try {
          txt = await fetchOne(directUrl);
        } catch {
          if (!env.isDev) throw new Error("direct fetch failed");
          txt = await fetchOne(proxyUrl);
        }
        if (t.type === "application/x-subrip" || t.type === "application/srt") txt = srtToWebVTT(txt);
        const blob = new Blob([txt], { type: "text/vtt" });
        const blobUrl = URL.createObjectURL(blob);
        transcriptBlobUrls.push(blobUrl);
        const track = document.createElement("track");
        track.kind = "subtitles";
        track.src = blobUrl;
        track.srclang = t.lang;
        track.label = t.lang === "en" ? "English" : t.lang;
        track.default = false;
        videoEl.appendChild(track);
        log.info(`Subtitles: loaded ${t.lang} (${t.type})`);
      } catch (e) {
        const msg = String(e?.message || e || "fetch failed");
        log.warn(`Subtitles failed: ${t.url} — ${msg}`);
        transcriptsLoadError.value = msg;
      }
    }

    if (transcriptBlobUrls.length) {
      const tracks = videoEl.textTracks;
      for (const t of tracks) t.mode = "hidden";
      if (tracks.length) setupCueListeners(tracks[0]);
      captions.value = { available: true, showing: true };
    } else if (list.length) transcriptsLoadError.value = transcriptsLoadError.value || "Failed to load subtitles";
  }

  async function loadChapters(ep) {
    try {
      const list = await loadChaptersForEpisode({ env, episode: ep, fetchText });
      chapters.value = list;
      chaptersLoadError.value = null;
    } catch (e) {
      const msg = String(e?.message || e || "fetch failed");
      log.warn(`Chapters failed: ${msg}`);
      chapters.value = [];
      chaptersLoadError.value = msg;
    }
  }

  function toggleCaptions() {
    if (!videoEl) return;
    const tracks = videoEl.textTracks;
    if (!tracks || !tracks.length) return;
    const anyShowing = [...tracks].some((t) => t.mode === "showing" || t.mode === "hidden");
    for (const t of tracks) t.mode = anyShowing ? "disabled" : "hidden";
    if (!anyShowing) {
      const track = tracks[0];
      track.mode = "hidden";
      setupCueListeners(track);
    } else {
      if (tracks.length && cueChangeHandler) clearCueListeners(tracks[0]);
      subtitleCue.value = null;
    }
    captions.value = { available: true, showing: !anyShowing };
  }

  let cueChangeHandler = null;
  function setupCueListeners(track) {
    if (cueChangeHandler) {
      track.removeEventListener("cuechange", cueChangeHandler);
      cueChangeHandler = null;
    }
    cueChangeHandler = () => {
      const cues = [...(track.activeCues || [])];
      const text = cues.map((c) => (c.getCueAsHTML ? stripHtml(c.getCueAsHTML()) : c.text || "")).join("\n");
      subtitleCue.value = text ? { text } : null;
    };
    track.addEventListener("cuechange", cueChangeHandler);
    cueChangeHandler();
  }
  function clearCueListeners(track) {
    if (cueChangeHandler && track) {
      track.removeEventListener("cuechange", cueChangeHandler);
      cueChangeHandler = null;
    }
    subtitleCue.value = null;
  }
  function stripHtml(html) {
    if (!html) return "";
    if (typeof html === "string") {
      const div = document.createElement("div");
      div.innerHTML = html;
      return div.textContent || "";
    }
    // VTTCue.getCueAsHTML() returns a DocumentFragment.
    if (typeof html === "object" && (html.nodeType || "textContent" in html)) {
      return html.textContent || "";
    }
    return String(html);
  }

  function normalizeSubtitlePrefs(input) {
    const s = input && typeof input === "object" ? input : {};

    const legacyHasH = Object.prototype.hasOwnProperty.call(s, "h");
    const isOldDefault =
      legacyHasH &&
      Number(s.x) === 10 &&
      Number(s.y) === 10 &&
      Number(s.w) === 80 &&
      Number(s.h) === 15 &&
      (s.opacity == null || Math.abs(Number(s.opacity) - 0.95) < 0.0001);

    if (isOldDefault) return { ...DEFAULT_SUBTITLE_PREFS };

    if (legacyHasH) {
      const x0 = Number.isFinite(Number(s.x)) ? Number(s.x) : 10;
      const y0 = Number.isFinite(Number(s.y)) ? Number(s.y) : 10;
      const w0 = Number.isFinite(Number(s.w)) ? Number(s.w) : 80;
      const h0 = Number.isFinite(Number(s.h)) ? Number(s.h) : 15;
      return {
        x: clamp(x0 + w0 / 2, 0, 100),
        y: clamp(y0 + h0 / 2, 0, 100),
        w: clamp(w0, 30, 100),
        opacity: Number.isFinite(Number(s.opacity)) ? clamp(Number(s.opacity), 0.15, 1) : DEFAULT_SUBTITLE_PREFS.opacity,
        scale: 1,
      };
    }

    return {
      x: Number.isFinite(Number(s.x)) ? clamp(Number(s.x), 0, 100) : DEFAULT_SUBTITLE_PREFS.x,
      y: Number.isFinite(Number(s.y)) ? clamp(Number(s.y), 0, 100) : DEFAULT_SUBTITLE_PREFS.y,
      w: Number.isFinite(Number(s.w)) ? clamp(Number(s.w), 30, 100) : DEFAULT_SUBTITLE_PREFS.w,
      opacity: Number.isFinite(Number(s.opacity)) ? clamp(Number(s.opacity), 0.15, 1) : DEFAULT_SUBTITLE_PREFS.opacity,
      scale: Number.isFinite(Number(s.scale)) ? clamp(Number(s.scale), 0.6, 2.4) : DEFAULT_SUBTITLE_PREFS.scale,
    };
  }

  function setSubtitleBox(s) {
    const box = normalizeSubtitlePrefs(s);
    persisted.subtitleBox = box;
    saveState();
    subtitleBox.value = box;
  }

  function setSkip(next) {
    const v = normalizeSkip(next);
    persisted.skip = v;
    saveState();
    skip.value = v;
  }

  function setRateSteps(next) {
    const norm = normalizeRateSteps(next) || DEFAULT_RATE_STEPS.slice();
    persisted.rateSteps = norm;
    saveState();
    rateSteps.value = norm;

    const snapped = normalizeRate(playback.value.rate || 1, norm);
    persisted.rate = snapped;
    if (snapped !== 1) persisted.lastNonOneRate = snapped;
    saveState();

    playback.value = { ...playback.value, rate: snapped };
    if (videoEl) {
      try {
        videoEl.playbackRate = snapped;
      } catch {}
    }
  }

  function resetRateSteps() {
    setRateSteps(DEFAULT_RATE_STEPS.slice());
  }

  async function play({ userGesture = true } = {}) {
    if (!videoEl) return;
    userPaused = false;
    const wantsMuted = userGesture ? false : persisted.muted === true;
    if (wantsMuted) {
      try {
        videoEl.muted = true;
        playback.value = { ...playback.value, muted: true };
      } catch {}
      try {
        await videoEl.play();
        audioBlocked.value = false;
      } catch {
        log.warn("Autoplay blocked (press Play)");
      }
      return;
    }
    try {
      try {
        videoEl.muted = false;
        playback.value = { ...playback.value, muted: false };
      } catch {}
      await videoEl.play();
      audioBlocked.value = false;
    } catch (err) {
      const isAutoplayBlock = err?.name === "NotAllowedError";
      if (isAutoplayBlock) {
        videoEl.pause();
        audioBlocked.value = true;
        log.warn("Sound muted by browser. Click video or Play to enable.");
      } else if (userGesture) {
        let recovered = false;
        try {
          videoEl.muted = true;
          await videoEl.play();
          recovered = true;
        } catch {}
        if (!recovered) log.warn("Autoplay blocked (press Play)");
      }
    }
  }

  function unmuteOnGesture() {
    if (!videoEl || !videoEl.muted) return;
    try {
      videoEl.muted = false;
      playback.value = { ...playback.value, muted: false };
      audioBlocked.value = false;
      persisted.muted = false;
      saveState();
    } catch {}
  }

  function pause() {
    if (!videoEl) return;
    userPaused = true;
    videoEl.pause();
  }

  function togglePlay() {
    if (!videoEl) return;
    if (videoEl.paused) {
      play({ userGesture: true });
    } else if (videoEl.muted) {
      // Playing but muted: unmute on user gesture instead of pausing
      try {
        videoEl.muted = false;
        playback.value = { ...playback.value, muted: false };
        audioBlocked.value = false;
        persisted.muted = false;
        saveState();
      } catch {}
    } else {
      pause();
    }
  }

  function seekBy(deltaSec) {
    if (!videoEl) return;
    videoEl.currentTime = Math.max(0, (videoEl.currentTime || 0) + deltaSec);
  }

  function seekToPct(pct01) {
    if (!videoEl) return;
    const dur = videoEl.duration;
    if (!Number.isFinite(dur) || dur <= 0) return;
    videoEl.currentTime = clamp(pct01, 0, 1) * dur;
  }

  function seekToTime(tSec) {
    if (!videoEl) return;
    const t = Math.max(0, Number(tSec) || 0);
    videoEl.currentTime = t;
  }

  function rateUp() {
    if (!videoEl) return;
    const steps = rateSteps.value && rateSteps.value.length ? rateSteps.value : DEFAULT_RATE_STEPS;
    const cur = normalizeRate(videoEl.playbackRate || playback.value.rate || 1, steps);
    const idx = steps.indexOf(cur);
    const next = steps[Math.min(steps.length - 1, (idx >= 0 ? idx : 2) + 1)] || 1;
    try {
      videoEl.playbackRate = next;
    } catch {}
    persisted.rate = next;
    if (next !== 1) persisted.lastNonOneRate = next;
    saveState();
    playback.value = { ...playback.value, rate: next };
  }

  function rateDown() {
    if (!videoEl) return;
    const steps = rateSteps.value && rateSteps.value.length ? rateSteps.value : DEFAULT_RATE_STEPS;
    const cur = normalizeRate(videoEl.playbackRate || playback.value.rate || 1, steps);
    const idx = steps.indexOf(cur);
    const next = steps[Math.max(0, (idx >= 0 ? idx : 2) - 1)] || 1;
    try {
      videoEl.playbackRate = next;
    } catch {}
    persisted.rate = next;
    if (next !== 1) persisted.lastNonOneRate = next;
    saveState();
    playback.value = { ...playback.value, rate: next };
  }

  function toggleRate() {
    if (!videoEl) return;
    const steps = rateSteps.value && rateSteps.value.length ? rateSteps.value : DEFAULT_RATE_STEPS;
    const cur = normalizeRate(videoEl.playbackRate || playback.value.rate || 1, steps);
    const next = cur === 1 ? (persisted.lastNonOneRate || 1.5) : 1;
    try {
      videoEl.playbackRate = next;
    } catch {}
    persisted.rate = next;
    if (next !== 1) persisted.lastNonOneRate = next;
    saveState();
    playback.value = { ...playback.value, rate: next };
  }

  function volumeUp() {
    if (!videoEl) return;
    const v = playback.value;
    let vol = clamp((v.volume ?? 1) + VOLUME_STEP, 0, 1);
    if (vol > 0 && v.muted) {
      try {
        videoEl.muted = false;
        audioBlocked.value = false;
        persisted.muted = false;
      } catch {}
    }
    videoEl.volume = vol;
    persisted.volume = vol;
    saveState();
    playback.value = { ...v, volume: vol, muted: !!videoEl.muted };
  }

  function volumeDown() {
    if (!videoEl) return;
    const v = playback.value;
    let vol = clamp((v.volume ?? 1) - VOLUME_STEP, 0, 1);
    videoEl.volume = vol;
    if (vol <= 0) {
      try {
        videoEl.muted = true;
        persisted.muted = true;
      } catch {}
    }
    persisted.volume = vol;
    saveState();
    playback.value = { ...v, volume: vol, muted: !!videoEl.muted };
  }

  function toggleMute() {
    if (!videoEl) return;
    const v = playback.value;
    const next = !v.muted;
    try {
      videoEl.muted = next;
    } catch {}
    persisted.muted = next;
    saveState();
    playback.value = { ...v, muted: next };
  }

  let preloadPromise = null;
  function ensurePreload() {
    if (!preloadPromise && sources.length) preloadPromise = preloadCachedFeeds();
    return preloadPromise || Promise.resolve();
  }

  async function setSources(nextSources, { initialRoute } = {}) {
    sources = Array.isArray(nextSources) ? nextSources : [];
    if (didInitLoad || !sources.length) return;
    const routeSourceId =
      initialRoute?.feed && typeof initialRoute.feed === "string" && sources.some((s) => s.id === initialRoute.feed) ? initialRoute.feed : null;
    const wantedSourceId = routeSourceId || persisted.last?.sourceId || sources[0]?.id;
    if (!wantedSourceId) return;
    if (!videoEl) {
      pendingInitSourceId = wantedSourceId;
      pendingInitRoute = routeSourceId ? initialRoute : null;
      ensurePreload();
      return;
    }
    didInitLoad = true;
    try {
      await ensurePreload();
      if (routeSourceId) {
        await applyRoute(initialRoute, { autoplay: true });
      } else {
        await selectSource(wantedSourceId, { preserveEpisode: true });
      }
    } catch (e) {
      log.error(String(e?.message || e || "init load failed"));
    }
  }

  function setSleepTimerMins(mins) {
    if (!videoEl) return;
    sleepEndAt = Date.now() + mins * 60 * 1000;
    sleep.value = { active: true, label: `${fmtTime(mins * 60)}` };
    if (sleepTickId) clearInterval(sleepTickId);
    sleepTickId = setInterval(() => {
      if (!sleepEndAt) return;
      const leftMs = sleepEndAt - Date.now();
      if (leftMs <= 0) {
        clearSleepTimer();
        history.markCurrentHadSleep();
        videoEl.pause();
        return;
      }
      const leftSec = Math.ceil(leftMs / 1000);
      sleep.value = { active: true, label: `${fmtTime(leftSec)}` };
    }, 400);
  }

  function clearSleepTimer() {
    sleepEndAt = null;
    if (sleepTickId) clearInterval(sleepTickId);
    sleepTickId = null;
    sleep.value = { active: false, label: "" };
  }

  function attachVideo(el) {
    videoEl = el;
    if (!videoEl) return;
    const vol = Number(persisted.volume) >= 0 ? clamp(Number(persisted.volume), 0, 1) : 1;
    videoEl.volume = vol;
    const muted = persisted.muted ?? true;
    // Init configurable skip + speed steps from persisted state.
    skip.value = normalizeSkip(persisted.skip);
    rateSteps.value = normalizeRateSteps(persisted.rateSteps) || DEFAULT_RATE_STEPS.slice();
    shuffle.value = { ...normalizeShuffle(persisted.shuffle), label: "" };
    if (shuffle.value.active) ensureShuffleTick();

    const rate = normalizeRate(Number(persisted.rate) || 1, rateSteps.value);
    try {
      videoEl.playbackRate = rate;
    } catch {}
    try {
      videoEl.muted = muted;
    } catch {}
    playback.value = { ...playback.value, volume: vol, muted, rate };

    if (persisted.subtitleBox) setSubtitleBox(persisted.subtitleBox);

    // Click/tap on video: unmute + toggle play/pause.
    videoEl.addEventListener("click", () => {
      unmuteOnGesture();
      togglePlay();
    });

    // One-time unlock: first user interaction anywhere tries to unmute.
    const unlockOnce = () => {
      unmuteOnGesture();
      document.removeEventListener("click", unlockOnce);
      document.removeEventListener("touchstart", unlockOnce);
      document.removeEventListener("keydown", unlockOnce);
    };
    document.addEventListener("click", unlockOnce, { once: true });
    document.addEventListener("touchstart", unlockOnce, { once: true });
    document.addEventListener("keydown", unlockOnce, { once: true });

    videoEl.addEventListener("timeupdate", () => {
      const now = Date.now();
      const dur = videoEl.duration;
      const cur = videoEl.currentTime;
      playback.value = {
        paused: videoEl.paused,
        muted: !!videoEl.muted,
        volume: Number.isFinite(videoEl.volume) ? videoEl.volume : playback.value.volume ?? 1,
        rate: normalizeRate(videoEl.playbackRate || playback.value.rate || 1),
        time: Number.isFinite(cur) ? cur : 0,
        duration: Number.isFinite(dur) ? dur : NaN,
      };

      if (!currentSource || !currentEp) return;
      history.updateEnd(videoEl.currentTime || 0);
      if (now - lastPersistMs > 2000) {
        lastPersistMs = now;
        setProgressSec(currentSource.id, currentEp.id, videoEl.currentTime || 0);
      }
    });

    videoEl.addEventListener("pause", () => {
      userPaused = true;
      playback.value = { ...playback.value, paused: true };
    });

    videoEl.addEventListener("play", () => {
      userPaused = false;
      playback.value = { ...playback.value, paused: false };
    });

    videoEl.addEventListener("loadstart", () => { loading.value = true; });
    videoEl.addEventListener("waiting", () => { loading.value = true; });
    videoEl.addEventListener("canplay", () => { loading.value = false; });
    videoEl.addEventListener("canplaythrough", () => { loading.value = false; });
    videoEl.addEventListener("playing", () => { loading.value = false; });

    window.addEventListener("beforeunload", () => history.finalize());

    if (!didInitLoad && pendingInitSourceId) {
      const sourceId = pendingInitSourceId;
      pendingInitSourceId = null;
      const route = pendingInitRoute;
      pendingInitRoute = null;
      didInitLoad = true;
      ensurePreload()
        .then(() => (route && route.feed === sourceId ? applyRoute(route, { autoplay: true }) : selectSource(sourceId, { preserveEpisode: true })))
        .catch((e) => {
          log.error(String(e?.message || e || "init load failed"));
        });
    }
  }

  async function playRandom() {
    if (!sources.length) return;
    const src = sources[Math.floor(Math.random() * sources.length)];
    await selectSource(src.id, { preserveEpisode: false, pickRandomEpisode: true, autoplay: true });
  }

  async function selectSourceAndEpisode(sourceId, episodeId, { autoplay = true, startAt } = {}) {
    await selectSource(sourceId, { preserveEpisode: false, skipAutoEpisode: true, autoplay });
    await selectEpisode(episodeId, { autoplay, startAt });
  }

  effect(() => {
    const v = playback.value;
    if (!videoEl) return;
    if (videoEl.muted !== v.muted) playback.value = { ...v, muted: !!videoEl.muted };
  });

  return {
    fmtTime,
    current,
    currentSourceId,
    currentEpisodeId,
    chapters,
    chaptersLoadError,
    captions,
    transcriptsLoadError,
    playback,
    sleep,
    shuffle,
    shuffleIntervals: SHUFFLE_INTERVALS,
    sourceEpisodes,
    setSources,
    attachVideo,
    teardownPlayer,
    fetchText,
    loadSourceEpisodes,
    selectSource,
    selectEpisode,
    selectSourceAndEpisode,
    applyRoute,
    play,
    pause,
    togglePlay,
    audioBlocked,
    loading,
    seekBy,
    seekToPct,
    seekToTime,
    rateUp,
    rateDown,
    toggleRate,
    volumeUp,
    volumeDown,
    toggleMute,
    toggleCaptions,
    subtitleBox,
    subtitleCue,
    setSubtitleBox,
    skip,
    setSkip,
    rateSteps,
    setRateSteps,
    resetRateSteps,
    setSleepTimerMins,
    clearSleepTimer,
    playRandom,
    toggleShuffle,
    setShuffleSettings,
    getProgressSec,
  };
}
