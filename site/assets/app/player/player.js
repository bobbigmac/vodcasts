import { fetchCached } from "../vod/feed_cache.js";
import { parseFeedXml } from "../vod/feed_parse.js";
import { loadChaptersForEpisode, renderChapters } from "../ui/chapters.js";

export function createPlayer({ env, store, els, log, history }) {
  const STORAGE_KEY = "vodcasts_state_v1";
  const FEED_PROXY = env.feedProxy;

  let sources = [];
  let currentSource = null;
  let episodes = [];
  let episodesBySource = {};
  let currentEp = null;

  let hls = null;
  let transcriptBlobUrls = [];
  let lastPersistMs = 0;
  let userPaused = false;
  let didInitLoad = false;
  let sleepEndAt = null;
  let sleepTickId = null;

  const state = loadState();

  store.subscribe((s) => {
    sources = s.sources || [];
    if (!didInitLoad && sources.length) {
      didInitLoad = true;
      const wantedSourceId = state.last?.sourceId || sources[0]?.id;
      if (wantedSourceId) {
        loadSource(wantedSourceId, { preserveEpisode: true }).catch((e) => {
          log.error(String(e?.message || e || "init load failed"));
        });
      }
    }
  });

  function loadState() {
    try {
      const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
      return raw && typeof raw === "object" ? raw : {};
    } catch {
      return {};
    }
  }
  function saveState() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
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
    const v = state.progress?.[episodeKey(sourceId, episodeId)];
    return Number.isFinite(v) ? v : 0;
  }
  function setProgressSec(sourceId, episodeId, t) {
    state.progress ||= {};
    state.progress[episodeKey(sourceId, episodeId)] = Math.max(0, t || 0);
    state.last = { sourceId, episodeId, at: Date.now() };
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
    const can = els.video?.canPlayType("application/vnd.apple.mpegurl") || els.video?.canPlayType("application/x-mpegURL");
    return can === "probably" || can === "maybe";
  }

  function teardownPlayer() {
    transcriptBlobUrls.forEach((u) => URL.revokeObjectURL(u));
    transcriptBlobUrls = [];
    [...(els.video?.querySelectorAll?.("track") || [])].forEach((t) => t.remove());
    if (hls) {
      try {
        hls.destroy();
      } catch {}
      hls = null;
    }
    els.video?.pause?.();
    els.video?.removeAttribute?.("src");
    try {
      els.video?.load?.();
    } catch {}
    if (els.btnCC) els.btnCC.style.display = "none";
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
    return parsed.episodes;
  }

  async function loadSource(sourceId, { preserveEpisode = true, pickRandomEpisode = false, skipAutoEpisode = false } = {}) {
    const src = sources.find((s) => s.id === sourceId) || sources[0];
    if (!src) return;

    currentSource = src;
    try {
      log.info(`Fetching feed: ${src.title || src.id}`);
      const xmlText = await fetchText(src.feed_url, src.fetch_via || "auto", { useCache: true });
      const parsed = parseFeedXml(xmlText, src);
      episodes = parsed.episodes;
      episodesBySource[src.id] = episodes;

      const playable = episodes.filter((e) => e.media?.url && e.media?.pickedIsVideo);
      const playableAny = episodes.filter((e) => e.media?.url);
      log.info(`${parsed.channelTitle}: ${playable.length} video (of ${episodes.length})`);

      let wanted;
      if (!skipAutoEpisode) {
        if (pickRandomEpisode && playable.length) {
          wanted = playable[Math.floor(Math.random() * playable.length)].id;
        } else {
          const lastId = state.lastBySource?.[src.id] || (preserveEpisode && state.last?.sourceId === src.id ? state.last?.episodeId : null);
          const lastIsVideo = lastId && playable.some((e) => e.id === lastId);
          wanted = (lastIsVideo ? lastId : null) || playable[0]?.id || playableAny[0]?.id || null;
        }
      }
      if (wanted) await loadEpisode(wanted, { autoplay: !userPaused });

      store.update((s) => ({ ...s, current: { sourceId: src.id, episodeId: currentEp?.id || null } }));
    } catch (e) {
      episodes = [];
      log.error(`Feed error: ${String(e?.message || e)} — ${src.feed_url}`);
    }
  }

  async function loadEpisode(episodeId, { autoplay = true, startAt: overrideStartAt } = {}) {
    const ep = episodes.find((e) => e.id === episodeId) || episodes.find((e) => e.media?.url);
    if (!ep) return;
    if (!ep.media?.url) return log.warn(`Episode "${(ep.title || "").slice(0, 40)}…": no media URL`);
    if (!ep.media.pickedIsVideo) return log.info("Skipping audio-only episode");

    teardownPlayer();
    currentEp = ep;

    const startAt = overrideStartAt ?? getProgressSec(currentSource.id, ep.id) ?? 0;
    history.startSegment({
      sourceId: currentSource.id,
      episodeId: ep.id,
      episodeTitle: ep.title,
      channelTitle: ep.channelTitle || currentSource.title,
      startTime: startAt,
    });
    state.last = { sourceId: currentSource.id, episodeId: ep.id, at: Date.now() };
    state.lastBySource ||= {};
    state.lastBySource[currentSource.id] = ep.id;
    saveState();

    if (els.epTitle) els.epTitle.textContent = ep.title || "Episode";
    if (els.epSub) els.epSub.textContent = `${ep.channelTitle || currentSource.title}${ep.dateText ? " · " + ep.dateText : ""}`;
    if (els.epDesc) els.epDesc.innerHTML = ep.descriptionHtml || "";
    if (els.chapters) els.chapters.innerHTML = "";

    const mediaUrl = ep.media.url;
    const mediaType = ep.media.type || "";
    const shouldUseHls = isProbablyHls(mediaUrl, mediaType);
    const usingNative = shouldUseHls && isNativeHls();
    const usingHlsJs = shouldUseHls && !usingNative && window.Hls && Hls.isSupported();

    if (shouldUseHls && !usingNative && !usingHlsJs) {
      log.error("HLS not supported");
      return;
    }

    if (usingNative) {
      els.video.src = mediaUrl;
    } else if (usingHlsJs) {
      hls = new Hls({ enableWorker: true });
      hls.on(Hls.Events.ERROR, (_evt, data) => {
        if (data?.fatal) log.error(`HLS error: ${data?.type || "fatal"}`);
      });
      hls.loadSource(mediaUrl);
      hls.attachMedia(els.video);
    } else {
      els.video.src = mediaUrl;
    }

    els.video.addEventListener(
      "loadedmetadata",
      () => {
        const dur = els.video.duration;
        if (Number.isFinite(dur) && dur > 2) {
          const safe = startAt > dur - 20 ? 0 : clamp(startAt, 0, Math.max(0, dur - 0.25));
          if (safe > 0.25) els.video.currentTime = safe;
        }
        if (autoplay) {
          userPaused = false;
          els.video.muted = false;
          els.video.play().catch(() => {
            els.video.muted = true;
            els.video.play().catch(() => {});
          });
        }
      },
      { once: true }
    );

    await loadTranscripts(ep);
    await loadAndRenderChapters(ep);
    store.update((s) => ({ ...s, current: { sourceId: currentSource.id, episodeId: ep.id } }));
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
    if (!list.length || !els.video) return;

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
        els.video.appendChild(track);
        log.info(`Subtitles: loaded ${t.lang} (${t.type})`);
      } catch (_e) {
        log.warn(`Subtitles failed: ${t.url}`);
      }
    }

    if (transcriptBlobUrls.length && els.btnCC) els.btnCC.style.display = "";
  }

  async function loadAndRenderChapters(ep) {
    const chapters = await loadChaptersForEpisode({ env, episode: ep, fetchText });
    renderChapters(els.chapters, chapters, {
      fmtTime,
      onJump: (t) => {
        els.video.currentTime = t;
        els.video.play().catch(() => {});
      },
    });
  }

  function updateProgressUi() {
    const dur = els.video.duration;
    const cur = els.video.currentTime;
    if (els.guideTime) els.guideTime.textContent = `${fmtTime(cur)}${Number.isFinite(dur) ? " / " + fmtTime(dur) : ""}`;

    if (Number.isFinite(dur) && dur > 0) {
      const pct = Math.min(100, (cur / dur) * 100);
      if (els.progressFill) els.progressFill.style.width = `${pct}%`;
      if (els.guideSeekFill) els.guideSeekFill.style.width = `${pct}%`;
    }
  }

  function attachUiHandlers() {
    els.btnPlay?.addEventListener("click", () => {
      if (els.video.paused) {
        userPaused = false;
        els.video.play().catch(() => {});
      } else {
        userPaused = true;
        els.video.pause();
      }
    });
    els.btnSeekBack?.addEventListener("click", () => {
      els.video.currentTime = Math.max(0, (els.video.currentTime || 0) - 10);
    });
    els.btnSeekFwd?.addEventListener("click", () => {
      els.video.currentTime = Math.max(0, (els.video.currentTime || 0) + 30);
    });

    els.btnCC?.addEventListener("click", () => {
      if (!els.video) return;
      const tracks = els.video.textTracks;
      if (!tracks || !tracks.length) return;
      const anyShowing = [...tracks].some((t) => t.mode === "showing");
      for (const t of tracks) t.mode = anyShowing ? "disabled" : "hidden";
      if (!anyShowing) tracks[0].mode = "showing";
      els.btnCC.classList.toggle("active", !anyShowing);
    });

    const closeSleepMenu = () => {
      if (els.sleepMenu) els.sleepMenu.setAttribute("aria-hidden", "true");
    };

    const clearSleepTimer = () => {
      sleepEndAt = null;
      if (sleepTickId) clearInterval(sleepTickId);
      sleepTickId = null;
      if (els.btnSleep) els.btnSleep.textContent = "Sleep";
      closeSleepMenu();
    };

    const setSleepTimerMins = (mins) => {
      sleepEndAt = Date.now() + mins * 60 * 1000;
      closeSleepMenu();
      if (sleepTickId) clearInterval(sleepTickId);
      sleepTickId = setInterval(() => {
        if (!sleepEndAt) return;
        const leftMs = sleepEndAt - Date.now();
        if (leftMs <= 0) {
          clearSleepTimer();
          history.markCurrentHadSleep();
          els.video.pause();
          return;
        }
        const leftSec = Math.ceil(leftMs / 1000);
        if (els.btnSleep) els.btnSleep.textContent = `Sleep ${fmtTime(leftSec)}`;
      }, 400);
    };

    els.btnSleep?.addEventListener("click", (e) => {
      e.stopPropagation();
      if (sleepEndAt) return clearSleepTimer();
      const open = els.sleepMenu?.getAttribute("aria-hidden") === "false";
      els.sleepMenu?.setAttribute("aria-hidden", open ? "true" : "false");
    });

    els.sleepMenu?.addEventListener("click", (e) => {
      const opt = e.target.closest?.(".sleepOpt");
      const mins = parseInt(opt?.dataset?.mins || "", 10);
      if (Number.isFinite(mins) && mins > 0) setSleepTimerMins(mins);
    });

    document.addEventListener("click", () => closeSleepMenu());
    const onSeekBar = (ev, el) => {
      const r = el.getBoundingClientRect();
      const x = ev.clientX - r.left;
      const pct = Math.min(1, Math.max(0, x / r.width));
      const dur = els.video.duration;
      if (Number.isFinite(dur) && dur > 0) els.video.currentTime = pct * dur;
    };
    els.progress?.addEventListener("click", (e) => onSeekBar(e, els.progress));
    els.guideSeek?.addEventListener("click", (e) => onSeekBar(e, els.guideSeek));

    els.video.addEventListener("timeupdate", () => {
      updateProgressUi();
      const now = Date.now();
      if (!currentSource || !currentEp) return;
      history.updateEnd(els.video.currentTime || 0);
      if (now - lastPersistMs > 2000) {
        lastPersistMs = now;
        setProgressSec(currentSource.id, currentEp.id, els.video.currentTime || 0);
      }
    });
    els.video.addEventListener("pause", () => {
      userPaused = true;
      if (els.btnPlay) els.btnPlay.textContent = "▶";
    });
    els.video.addEventListener("play", () => {
      userPaused = false;
      if (els.btnPlay) els.btnPlay.textContent = "❚❚";
    });
    window.addEventListener("beforeunload", () => history.finalize());
  }

  async function loadSourceAndEpisode(sourceId, episodeId, { autoplay = true, startAt } = {}) {
    await loadSource(sourceId, { preserveEpisode: false, skipAutoEpisode: true });
    if (!currentSource) return;
    await loadEpisode(episodeId, { autoplay, startAt });
  }

  attachUiHandlers();

  return {
    fmtTime,
    loadSource,
    loadEpisode,
    loadSourceEpisodes,
    loadSourceAndEpisode,
    getCurrent: () => ({ source: currentSource, episode: currentEp, episodes, episodesBySource }),
  };
}
