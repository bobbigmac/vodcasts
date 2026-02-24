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

  let sleepEndAt = null;
  let sleepTickId = null;

  const persisted = loadState();

  const current = signal({ source: null, episode: null });
  const chapters = signal([]);
  const playback = signal({
    paused: true,
    muted: true,
    time: 0,
    duration: NaN,
  });
  const captions = signal({ available: false, showing: false });
  const sleep = signal({ active: false, label: "Sleep" });
  const sourceEpisodes = signal({});

  const currentSourceId = computed(() => current.value.source?.id || null);
  const currentEpisodeId = computed(() => current.value.episode?.id || null);

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

  function fmtTime(s) {
    if (!Number.isFinite(s) || s < 0) return "00:00";
    const hh = Math.floor(s / 3600);
    const mm = Math.floor((s % 3600) / 60);
    const ss = Math.floor(s % 60);
    if (hh > 0) return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
    return `${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
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
    { preserveEpisode = true, pickRandomEpisode = false, skipAutoEpisode = false, autoplay = true } = {}
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
        if (pickRandomEpisode && playable.length) {
          wanted = playable[Math.floor(Math.random() * playable.length)].id;
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

  async function selectEpisode(episodeId, { autoplay = true, startAt: overrideStartAt } = {}) {
    const ep = episodes.find((e) => e.id === episodeId) || episodes.find((e) => e.media?.url);
    if (!ep || !currentSource) return;
    if (!ep.media?.url) return log.warn(`Episode "${(ep.title || "").slice(0, 40)}…": no media URL`);
    if (!videoEl) return log.error("Player: no <video> element attached");

    teardownPlayer();
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
        if (t.type === "application/x-subrip") txt = srtToWebVTT(txt);
        const blob = new Blob([txt], { type: "text/vtt" });
        const blobUrl = URL.createObjectURL(blob);
        transcriptBlobUrls.push(blobUrl);
        const track = document.createElement("track");
        track.kind = "subtitles";
        track.src = blobUrl;
        track.srclang = t.lang;
        track.label = t.lang === "en" ? "English" : t.lang;
        track.default = transcriptBlobUrls.length === 1;
        videoEl.appendChild(track);
        log.info(`Subtitles: loaded ${t.lang} (${t.type})`);
      } catch (_e) {
        log.warn(`Subtitles failed: ${t.url}`);
      }
    }

    if (transcriptBlobUrls.length) captions.value = { available: true, showing: false };
  }

  async function loadChapters(ep) {
    const list = await loadChaptersForEpisode({ env, episode: ep, fetchText });
    chapters.value = list;
  }

  function toggleCaptions() {
    if (!videoEl) return;
    const tracks = videoEl.textTracks;
    if (!tracks || !tracks.length) return;
    const anyShowing = [...tracks].some((t) => t.mode === "showing");
    for (const t of tracks) t.mode = anyShowing ? "disabled" : "hidden";
    if (!anyShowing) tracks[0].mode = "showing";
    captions.value = { available: true, showing: !anyShowing };
  }

  async function play({ userGesture = true } = {}) {
    if (!videoEl) return;
    userPaused = false;
    if (userGesture) {
      try {
        videoEl.muted = false;
      } catch {}
    }
    try {
      await videoEl.play();
    } catch {
      let recovered = false;
      try {
        videoEl.muted = true;
        await videoEl.play();
        recovered = true;
      } catch {}
      if (!recovered) log.warn("Autoplay blocked (press Play)");
    }
  }

  function pause() {
    if (!videoEl) return;
    userPaused = true;
    videoEl.pause();
  }

  function togglePlay() {
    if (!videoEl) return;
    if (videoEl.paused) play({ userGesture: true });
    else pause();
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

  function setSources(nextSources) {
    sources = Array.isArray(nextSources) ? nextSources : [];
    if (didInitLoad || !sources.length) return;
    const wantedSourceId = persisted.last?.sourceId || sources[0]?.id;
    if (!wantedSourceId) return;
    if (!videoEl) {
      pendingInitSourceId = wantedSourceId;
      return;
    }
    didInitLoad = true;
    selectSource(wantedSourceId, { preserveEpisode: true }).catch((e) => {
      log.error(String(e?.message || e || "init load failed"));
    });
  }

  function setSleepTimerMins(mins) {
    if (!videoEl) return;
    sleepEndAt = Date.now() + mins * 60 * 1000;
    sleep.value = { active: true, label: `Sleep ${fmtTime(mins * 60)}` };
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
      sleep.value = { active: true, label: `Sleep ${fmtTime(leftSec)}` };
    }, 400);
  }

  function clearSleepTimer() {
    sleepEndAt = null;
    if (sleepTickId) clearInterval(sleepTickId);
    sleepTickId = null;
    sleep.value = { active: false, label: "Sleep" };
  }

  function attachVideo(el) {
    videoEl = el;
    if (!videoEl) return;
    // Prefer muted until we have a user gesture (helps autoplay succeed).
    try {
      videoEl.muted = true;
    } catch {}

    videoEl.addEventListener("timeupdate", () => {
      const now = Date.now();
      const dur = videoEl.duration;
      const cur = videoEl.currentTime;
      playback.value = {
        paused: videoEl.paused,
        muted: !!videoEl.muted,
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

    window.addEventListener("beforeunload", () => history.finalize());

    if (!didInitLoad && pendingInitSourceId) {
      const sourceId = pendingInitSourceId;
      pendingInitSourceId = null;
      didInitLoad = true;
      selectSource(sourceId, { preserveEpisode: true }).catch((e) => {
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
    captions,
    playback,
    sleep,
    sourceEpisodes,
    setSources,
    attachVideo,
    teardownPlayer,
    fetchText,
    loadSourceEpisodes,
    selectSource,
    selectEpisode,
    selectSourceAndEpisode,
    play,
    pause,
    togglePlay,
    seekBy,
    seekToPct,
    seekToTime,
    toggleCaptions,
    setSleepTimerMins,
    clearSleepTimer,
    playRandom,
    getProgressSec,
  };
}
