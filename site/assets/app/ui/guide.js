import { html, useEffect, useMemo, useRef, useSignal } from "../runtime/vendor.js";
import { episodeSearchHaystack, matchesAllTokens, splitQuery } from "./search.js";
import { HeadphonesIcon } from "./icons.js";

const CATEGORY_ORDER = ["church", "university", "fitness", "bible", "twit", "podcastindex", "other", "needs-rss"];
const MS_PER_MIN = 60 * 1000;
const MS_PER_DAY = 24 * 60 * 60 * 1000;
const NEW_WITHIN_DAYS = 30;

// Fixed guide scale (no compression).
const PX_PER_MIN = 6;
const VIRTUAL_HOURS = 24;
const VIRTUAL_MIN = VIRTUAL_HOURS * 60;
const HORIZON_PX = VIRTUAL_MIN * PX_PER_MIN;

const GUIDE_ROW_H_PX = 56;
const ROW_OVERSCAN = 6;
const TIME_BUFFER_MIN = 90;
const NARROW_GUIDE_MAX_W_PX = 720;
const GUIDE_PREFS_KEY = "vodcasts_guide_prefs_v1";

function loadGuidePrefs() {
  try {
    const raw = JSON.parse(localStorage.getItem(GUIDE_PREFS_KEY) || "{}");
    const fav = Array.isArray(raw?.faves) ? raw.faves.filter((x) => typeof x === "string" && x) : [];
    const favesOnly = raw?.favesOnly === true;
    return { faves: new Set(fav), favesOnly };
  } catch {
    return { faves: new Set(), favesOnly: false };
  }
}

function saveGuidePrefs({ faves, favesOnly }) {
  try {
    const list = [...(faves instanceof Set ? faves : new Set())].filter((x) => typeof x === "string" && x).slice(0, 5000);
    localStorage.setItem(GUIDE_PREFS_KEY, JSON.stringify({ faves: list, favesOnly: !!favesOnly }));
  } catch {}
}

function fmtDuration(sec) {
  if (!Number.isFinite(sec) || sec < 0) return null;
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (h > 0) return `${h}h${m}m`;
  if (m > 0) return `${m}m`;
  return `${Math.floor(sec)}s`;
}

function episodeDateMs(ep) {
  const d = ep?.date;
  if (d instanceof Date && !Number.isNaN(d.valueOf())) return d.getTime();
  if (typeof d === "number" && Number.isFinite(d)) return d;
  if (typeof d === "string" && d) {
    const t = Date.parse(d);
    if (Number.isFinite(t)) return t;
  }
  const dt = String(ep?.dateText || "").trim();
  if (dt) {
    const t = Date.parse(dt);
    if (Number.isFinite(t)) return t;
  }
  return null;
}

function isEpisodeNew(ep, nowMs) {
  const t = episodeDateMs(ep);
  if (!Number.isFinite(t)) return false;
  const age = nowMs - t;
  if (age < 0) return false;
  return age <= NEW_WITHIN_DAYS * MS_PER_DAY;
}

function isPlayableVideoEp(ep) {
  const m = ep?.media || null;
  const url = String(m?.url || "").trim();
  if (!url) return false;
  if (m?.pickedIsVideo === true) return true;
  const t = String(m?.type || "").toLowerCase();
  const u = url.toLowerCase();
  if (t.startsWith("video/")) return true;
  if (t.startsWith("audio/")) return true;
  if (m?.pickedIsVideo === false) return true;
  if (u.includes(".m3u8")) return true;
  if (u.match(/\.(mp4|m4v|mov|webm)(\?|$)/)) return true;
  if (u.match(/\.(mp3|m4a|aac|ogg|opus)(\?|$)/)) return true;
  return false;
}

function fmtPubDateShort(ep, nowMs = Date.now()) {
  const t = episodeDateMs(ep);
  if (!Number.isFinite(t)) return "";
  const d = new Date(t);
  const now = new Date(nowMs);
  const sameYear = d.getFullYear() === now.getFullYear();
  try {
    const fmt = new Intl.DateTimeFormat(
      undefined,
      sameYear ? { month: "short", day: "numeric" } : { month: "short", day: "numeric", year: "2-digit" }
    );
    return fmt.format(d);
  } catch {
    const m = d.getMonth() + 1;
    const day = d.getDate();
    const y = String(d.getFullYear()).slice(-2);
    return sameYear ? `${m}/${day}` : `${m}/${day}/${y}`;
  }
}

function buildSourcesFlat(sources) {
  const groups = new Map();
  for (const s of sources || []) {
    const cat = s.category || "other";
    if (!groups.has(cat)) groups.set(cat, []);
    groups.get(cat).push(s);
  }
  const cats = [...groups.keys()].sort(
    (a, b) => (CATEGORY_ORDER.indexOf(a) - CATEGORY_ORDER.indexOf(b)) || a.localeCompare(b)
  );
  const flat = [];
  for (const cat of cats) {
    const list = groups
      .get(cat)
      .slice()
      .sort((a, b) => (a.title || a.id).localeCompare(b.title || b.id));
    flat.push(...list);
  }
  return flat;
}

function clamp(v, a, b) {
  return Math.min(b, Math.max(a, v));
}

function mod(a, b) {
  const m = a % b;
  return m < 0 ? m + b : m;
}

function roundToHalfHour(ts) {
  const d = new Date(Number(ts) || Date.now());
  d.setSeconds(0);
  d.setMilliseconds(0);
  const m = d.getMinutes();
  d.setMinutes(Math.floor(m / 30) * 30);
  return d.getTime();
}

function fmtClock(ts) {
  try {
    return new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(new Date(ts));
  } catch {
    const d = new Date(ts);
    return `${d.getHours()}:${String(d.getMinutes()).padStart(2, "0")}`;
  }
}

function escSel(v) {
  const s = String(v || "");
  try {
    return globalThis.CSS?.escape ? globalThis.CSS.escape(s) : s.replace(/["\\]/g, "\\$&");
  } catch {
    return s.replace(/["\\]/g, "\\$&");
  }
}

function bsearchCum(cum, off) {
  // `cum` length is n+1, monotonic, cum[0]=0, cum[n]=cycleSec.
  let lo = 0;
  let hi = cum.length - 2;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const a = cum[mid];
    const b = cum[mid + 1];
    if (off < a) hi = mid - 1;
    else if (off >= b) lo = mid + 1;
    else return mid;
  }
  return clamp(lo, 0, Math.max(0, cum.length - 2));
}

export function GuidePanel({ isOpen, sources, player }) {
  const currentSourceId = player.currentSourceId.value;
  const currentEpisodeId = player.currentEpisodeId.value;
  const episodesBySource = player.sourceEpisodes.value || {};
  const sourcesFlatAll = useMemo(() => buildSourcesFlat(sources.value || []), [sources.value]);
  const sourcesById = useMemo(() => {
    const m = new Map();
    for (const s of sources.value || []) m.set(s.id, s);
    return m;
  }, [sources.value]);

  const prefsInitRef = useRef(null);
  if (!prefsInitRef.current) prefsInitRef.current = loadGuidePrefs();
  const faveIds = useSignal(prefsInitRef.current.faves);
  const favesOnly = useSignal(!!prefsInitRef.current.favesOnly);

  const faveCount = useMemo(() => {
    const set = faveIds.value instanceof Set ? faveIds.value : new Set();
    let n = 0;
    for (const s of sources.value || []) if (set.has(s.id)) n += 1;
    return n;
  }, [sources.value, faveIds.value]);

  useEffect(() => {
    if (faveCount > 0) return;
    if (!favesOnly.value) return;
    favesOnly.value = false;
    saveGuidePrefs({ faves: faveIds.value, favesOnly: false });
  }, [faveCount, favesOnly.value]);

  const filterText = useSignal("");
  const filterKey = useMemo(() => String(filterText.value || "").trim(), [filterText.value]);
  const filterTokens = useMemo(() => splitQuery(filterKey), [filterKey]);

  const sourcesFlatFiltered = useMemo(() => {
    if (!filterTokens.length) return sourcesFlatAll;
    const out = [];
    for (const s of sourcesFlatAll) {
      const eps = episodesBySource[s.id];
      if (!Array.isArray(eps) || !eps.length) continue;
      const playable = eps.filter((ep) => isPlayableVideoEp(ep));
      if (!playable.length) continue;
      const srcObj = sourcesById.get(s.id) || s;
      if (playable.some((ep) => matchesAllTokens(filterTokens, episodeSearchHaystack(srcObj, ep)))) out.push(s);
    }
    return out;
  }, [sourcesFlatAll, sourcesById, filterKey, episodesBySource]);

  // Exclude feeds once we know they have no playable videos.
  // (If a feed isn't loaded yet, keep it around so it can be lazy-loaded.)
  const sourcesFlat0 = useMemo(() => {
    const out = [];
    for (const s of sourcesFlatFiltered) {
      const eps = episodesBySource[s.id];
      if (!Array.isArray(eps)) {
        out.push(s);
        continue;
      }
      if (eps.some((ep) => isPlayableVideoEp(ep))) out.push(s);
    }
    return out;
  }, [sourcesFlatFiltered, episodesBySource]);

  const sourcesFlatPlayable = useMemo(() => {
    const out = [];
    for (const s of sourcesFlatAll) {
      const eps = episodesBySource[s.id];
      if (!Array.isArray(eps)) {
        out.push(s);
        continue;
      }
      if (eps.some((ep) => isPlayableVideoEp(ep))) out.push(s);
    }
    return out;
  }, [sourcesFlatAll, episodesBySource]);

  const sourcesFlat = useMemo(() => {
    if (!favesOnly.value || faveCount <= 0) return sourcesFlat0;
    const set = faveIds.value instanceof Set ? faveIds.value : new Set();
    return sourcesFlat0.filter((s) => set.has(s.id));
  }, [sourcesFlat0, favesOnly.value, faveCount, faveIds.value]);

  const chanNoById = useMemo(() => {
    const m = new Map();
    for (let i = 0; i < sourcesFlatAll.length; i++) m.set(sourcesFlatAll[i].id, i);
    return m;
  }, [sourcesFlatAll]);

  const totalChanCount = sourcesFlatPlayable.length;
  const selectedChanCount = sourcesFlat.length;
  const cornerTitle = favesOnly.value ? "Faves Only" : "All Channels";

  const focusSourceIdx = useSignal(Math.max(0, sourcesFlat.findIndex((s) => s.id === currentSourceId)));
  const sourcesFlatRef = useRef([]);
  const sourcesByIdRef = useRef(new Map());
  const filterTokensRef = useRef([]);
  sourcesFlatRef.current = sourcesFlat;
  sourcesByIdRef.current = sourcesById;
  filterTokensRef.current = filterTokens;
  const focusTs = useSignal(Date.now());
  // Guide "epoch" for schedules; stays fixed while the panel is open.
  const guideZeroTs = useSignal(roundToHalfHour(Date.now()));
  const trackStartTs = useSignal(roundToHalfHour(Date.now()));
  const tracksRef = useRef(null);
  const loadingIdsRef = useRef(new Set());
  const lastScrollAtRef = useRef(0);
  const lastPointerMoveAtRef = useRef(0);
  const focusModeRef = useRef("init"); // init | keys | hover
  const focusSourceIdRef = useRef(null);
  const keyNavAtRef = useRef(0);
  const keyScrollRafRef = useRef(0);
  const sidebarHidden = useSignal(false);
  const sidebarHideOnNextScrollRef = useRef(false);
  const sidebarLastUserIntentAtRef = useRef(0);
  const marqueeRef = useRef({ el: null, anim: null, key: "" });
  const chanMarqueeRef = useRef({ el: null, anim: null, key: "" });

  const isNarrowGuide = () => {
    try {
      if (globalThis.matchMedia) return !!globalThis.matchMedia(`(max-width: ${NARROW_GUIDE_MAX_W_PX}px)`)?.matches;
    } catch {}
    try {
      return (globalThis.innerWidth || 0) <= NARROW_GUIDE_MAX_W_PX;
    } catch {}
    return false;
  };

  const isEditableEl = (el) => {
    if (!el) return false;
    const tag = String(el.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") return true;
    if (el.isContentEditable) return true;
    return false;
  };

  useEffect(() => {
    const src = sourcesFlat[focusSourceIdx.value] || null;
    focusSourceIdRef.current = src?.id || null;
  }, [focusSourceIdx.value, filterKey, sourcesFlat.length]);

  useEffect(() => {
    if (!sourcesFlat.length) {
      focusSourceIdx.value = 0;
      return;
    }
    const wanted = focusSourceIdRef.current || currentSourceId || null;
    if (wanted) {
      const idx = sourcesFlat.findIndex((s) => s.id === wanted);
      if (idx >= 0) {
        focusSourceIdx.value = idx;
        return;
      }
    }
    focusSourceIdx.value = clamp(focusSourceIdx.value, 0, Math.max(0, sourcesFlat.length - 1));
  }, [filterKey, sourcesFlat.length, currentSourceId]);

  const shouldAllowHoverFocus = () => {
    const last = Number(lastScrollAtRef.current) || 0;
    const scrolling = Date.now() - last < 140;
    const dragging = !!tracksRef.current?.classList?.contains?.("dragging");
    const lastKeys = Number(keyNavAtRef.current) || 0;
    // If the user just used keyboard nav, don't let hover immediately steal focus.
    if (Date.now() - lastKeys < 900) return false;
    // Pointer-enter can fire when content moves under a stationary cursor during programmatic scroll,
    // which can create a focus/scroll feedback loop. Require recent mouse movement to accept hover focus.
    const pm = Number(lastPointerMoveAtRef.current) || 0;
    // Also require that the mouse moved after the last keyboard nav action.
    if (pm <= lastKeys) return false;
    const pointerMovedRecently = Date.now() - pm < 250;
    return !scrolling && !dragging && pointerMovedRecently;
  };

  const ensureFocusVisible = () => {
    const tracksEl = tracksRef.current;
    if (!tracksEl) return;
    if (!isOpen.value) return;
    if (focusModeRef.current !== "keys") return;
    if (Date.now() - (Number(keyNavAtRef.current) || 0) > 900) return;
    if (tracksEl.classList?.contains?.("dragging")) return;

    const vw = tracksEl.clientWidth || 0;
    const vh = tracksEl.clientHeight || 0;
    if (vw <= 4 || vh <= 4) return;

    const x = ((focusTs.value - trackStartTs.value) / MS_PER_MIN) * PX_PER_MIN;
    const y = focusSourceIdx.value * GUIDE_ROW_H_PX;

    const sl = tracksEl.scrollLeft || 0;
    const st = tracksEl.scrollTop || 0;

    const padX = Math.round(vw * 0.22);
    const padY = Math.round(vh * 0.28);

    let nextLeft = sl;
    let nextTop = st;

    if (x < sl + padX) nextLeft = Math.max(0, Math.round(x - padX));
    else if (x > sl + vw - padX) nextLeft = Math.round(x - (vw - padX));

    if (y < st + padY) nextTop = Math.max(0, Math.round(y - padY));
    else if (y > st + vh - GUIDE_ROW_H_PX - padY) nextTop = Math.round(y - (vh - GUIDE_ROW_H_PX - padY));

    if (nextLeft !== sl) {
      const max = Math.max(0, (tracksEl.scrollWidth || 0) - vw);
      tracksEl.scrollLeft = clamp(nextLeft, 0, max);
    }
    if (nextTop !== st) {
      const max = Math.max(0, (tracksEl.scrollHeight || 0) - vh);
      tracksEl.scrollTop = clamp(nextTop, 0, max);
    }
  };

  const queueEnsureFocusVisible = () => {
    if (keyScrollRafRef.current) cancelAnimationFrame(keyScrollRafRef.current);
    keyScrollRafRef.current = requestAnimationFrame(() => {
      keyScrollRafRef.current = 0;
      try {
        ensureFocusVisible();
      } catch {}
    });
  };

  const DEFAULT_EP_SEC = 30 * 60;
  // For timeline readability: even very short videos should occupy a useful width.
  // Treat anything shorter than 20 minutes as 20 minutes when rendering the guide.
  const MIN_EP_SEC = 20 * 60;
  const MAX_EP_SEC = 9 * 3600;

  const estimateDurSec = (sourceId, ep) => {
    const ds = Number(ep?.durationSec);
    // Some feeds publish bogus tiny durations (e.g. 5s), which makes the guide try to
    // render thousands of blocks and the UI gets janky. Clamp to a sane minimum.
    if (Number.isFinite(ds) && ds > 0) return clamp(ds, MIN_EP_SEC, MAX_EP_SEC);
    // We intentionally do NOT use learned durations here to avoid twitchy relayout.
    return DEFAULT_EP_SEC;
  };

  const scheduleCacheRef = useRef(new Map());
  const getSchedule = (sourceId) => {
    if (!sourceId) return null;
    const tokens = filterTokensRef.current || [];
    const epsMap = player.sourceEpisodes.value || {};
    const epsRef = epsMap[sourceId] || null;
    if (!epsRef) return null;
    const cacheKey = `${sourceId}::${tokens.join(" ")}`;
    const prev = scheduleCacheRef.current.get(cacheKey) || null;
    if (prev && prev.epsRef === epsRef) return prev.schedule;

    const srcObj = sourcesByIdRef.current.get(sourceId) || null;
    const playable0 = (epsRef || []).filter((ep) => isPlayableVideoEp(ep));
    const playable = tokens.length
      ? playable0.filter((ep) => matchesAllTokens(tokens, episodeSearchHaystack(srcObj, ep)))
      : playable0;
    if (!playable.length) {
      scheduleCacheRef.current.set(cacheKey, { epsRef, schedule: null });
      return null;
    }
    const dursSec = playable.map((ep) => estimateDurSec(sourceId, ep));
    const cum = [0];
    for (let i = 0; i < dursSec.length; i++) cum.push(cum[cum.length - 1] + dursSec[i]);
    const cycleSec = cum[cum.length - 1] || 0;
    const schedule = cycleSec > 0 ? { playable, dursSec, cum, cycleSec } : null;
    scheduleCacheRef.current.set(cacheKey, { epsRef, schedule });
    return schedule;
  };

  const programAt = (schedule, ts) => {
    if (!schedule || !Number.isFinite(ts)) return null;
    const cycleSec = schedule.cycleSec;
    if (!Number.isFinite(cycleSec) || cycleSec <= 0) return null;
    const relSec = (ts - guideZeroTs.value) / 1000;
    const off = mod(relSec, cycleSec);
    const cycleBaseSec = relSec - off;
    const idx = bsearchCum(schedule.cum, off);
    const startRelSec = cycleBaseSec + schedule.cum[idx];
    const startTs = guideZeroTs.value + startRelSec * 1000;
    const durSec = schedule.dursSec[idx];
    const endTs = startTs + durSec * 1000;
    return { idx, ep: schedule.playable[idx], startTs, endTs, durSec };
  };

  const pickBestProgForRange = (schedule, rangeStartTs, rangeEndTs) => {
    if (!schedule) return null;
    const a0 = Number(rangeStartTs);
    const b0 = Number(rangeEndTs);
    if (!Number.isFinite(a0) || !Number.isFinite(b0)) return null;
    const a = Math.min(a0, b0);
    const b = Math.max(a0, b0);
    const mid = a + (b - a) / 2;

    const candidates = [];
    const seen = new Set();
    const add = (p) => {
      if (!p?.ep?.id) return;
      const key = `${p.ep.id}::${Math.round(p.startTs)}`;
      if (seen.has(key)) return;
      seen.add(key);
      candidates.push(p);
    };

    const samples = [mid, a + 1000, b - 1000].filter((t) => Number.isFinite(t));
    for (const t of samples) {
      const p = programAt(schedule, t);
      if (!p) continue;
      add(p);
      // Also consider adjacent programs in case the range crosses a boundary.
      add(programAt(schedule, p.startTs - 1000));
      add(programAt(schedule, p.endTs + 1000));
    }

    if (!candidates.length) return programAt(schedule, mid);

    let best = candidates[0];
    let bestOverlap = -1;
    let bestDist = Infinity;
    for (const p of candidates) {
      const overlap = Math.max(0, Math.min(p.endTs, b) - Math.max(p.startTs, a));
      const dist = Math.abs((p.startTs + p.endTs) / 2 - mid);
      if (overlap > bestOverlap || (overlap === bestOverlap && dist < bestDist)) {
        best = p;
        bestOverlap = overlap;
        bestDist = dist;
      }
    }
    return best;
  };

  const blocksForRange = (schedule, startTs, endTs) => {
    const out = [];
    if (!schedule) return out;
    const first = programAt(schedule, startTs);
    if (!first) return out;
    let idx = first.idx;
    let curTs = first.startTs;
    let guard = 0;
    // Safety: avoid pathological rows generating massive DOM.
    while (curTs < endTs && guard < 800) {
      const ep = schedule.playable[idx];
      const durSec = schedule.dursSec[idx];
      const nextTs = curTs + durSec * 1000;
      out.push({ idx, ep, durSec, startTs: curTs, endTs: nextTs });
      curTs = nextTs;
      idx = (idx + 1) % schedule.playable.length;
      guard++;
    }
    return out;
  };

  // Scroll state (virtualization).
  const viewportW = useSignal(0);
  const viewportH = useSignal(0);
  const scrollLeftPx = useSignal(0);
  const scrollTopPx = useSignal(0);

  const wheelToTracks = (e) => {
    const el = tracksRef.current;
    if (!el) return;
    const dx = Number(e?.deltaX || 0);
    const dy = Number(e?.deltaY || 0);
    if (!dx && !dy) return;
    el.scrollLeft += dx;
    el.scrollTop += dy;
    try {
      e.preventDefault();
    } catch {}
  };

  const jumpToPlaying = async ({ alignNow = true } = {}) => {
    focusModeRef.current = "keys";
    const srcId = player.current.value.source?.id || currentSourceId || null;
    if (!srcId) return;
    const srcIdx = Math.max(0, sourcesFlat.findIndex((s) => s.id === srcId));
    focusSourceIdx.value = srcIdx;

    const epsMap0 = player.sourceEpisodes.value || {};
    if (!epsMap0[srcId]) {
      try {
        await player.loadSourceEpisodes(srcId);
      } catch {}
    }

    const schedule = getSchedule(srcId);
    const epId = player.current.value.episode?.id || currentEpisodeId || null;
    const tSec = Number(player.playback?.value?.time || 0);
    const nowTs = Date.now();

    if (alignNow && schedule && epId) {
      const idx = schedule.playable.findIndex((ep) => ep?.id === epId);
      if (idx >= 0) {
        const durSec = schedule.dursSec[idx] || 0;
        const posSec = clamp(Number.isFinite(tSec) ? tSec : 0, 0, Math.max(0, durSec - 0.25));
        const offSec = (schedule.cum[idx] || 0) + posSec;
        guideZeroTs.value = nowTs - offSec * 1000;
        trackStartTs.value = nowTs - (VIRTUAL_MIN / 2) * MS_PER_MIN;
        focusTs.value = nowTs;
      } else {
        trackStartTs.value = nowTs - (VIRTUAL_MIN / 2) * MS_PER_MIN;
        focusTs.value = nowTs;
      }
    } else {
      trackStartTs.value = nowTs - (VIRTUAL_MIN / 2) * MS_PER_MIN;
      focusTs.value = nowTs;
    }

    const tracksEl = tracksRef.current;
    if (!tracksEl) return;
    requestAnimationFrame(() => {
      try {
        const x = ((focusTs.value - trackStartTs.value) / MS_PER_MIN) * PX_PER_MIN;
        const targetLeft = Math.round(x - (tracksEl.clientWidth || 1) * 0.28);
        const max = Math.max(0, tracksEl.scrollWidth - tracksEl.clientWidth);
        tracksEl.scrollLeft = clamp(targetLeft, 0, max);

        const rowTop = srcIdx * GUIDE_ROW_H_PX;
        const maxTop = Math.max(0, tracksEl.scrollHeight - tracksEl.clientHeight);
        tracksEl.scrollTop = clamp(Math.round(rowTop - (tracksEl.clientHeight || 1) * 0.35), 0, maxTop);
      } catch {}
    });
  };

  useEffect(() => {
    if (!isOpen.value) return;
    // Start "at" what is currently playing (doesn't need to live-update).
    guideZeroTs.value = roundToHalfHour(Date.now());
    trackStartTs.value = guideZeroTs.value;
    focusSourceIdx.value = Math.max(0, sourcesFlat.findIndex((s) => s.id === currentSourceId));
    focusTs.value = Date.now();
    if (currentSourceId && !episodesBySource[currentSourceId]) {
      player.loadSourceEpisodes(currentSourceId).catch(() => {});
    }
  }, [isOpen.value, currentSourceId, sourcesFlat.length]);

  useEffect(() => {
    if (isOpen.value) return;
    sidebarHidden.value = false;
    sidebarHideOnNextScrollRef.current = false;
    sidebarLastUserIntentAtRef.current = 0;
    const prev = marqueeRef.current || null;
    if (prev?.anim) {
      try {
        prev.anim.cancel();
      } catch {}
    }
    if (prev?.el) {
      try {
        prev.el.style.transform = "";
      } catch {}
    }
    marqueeRef.current = { el: null, anim: null, key: "" };
    const prevChan = chanMarqueeRef.current || null;
    if (prevChan?.anim) {
      try {
        prevChan.anim.cancel();
      } catch {}
    }
    if (prevChan?.el) {
      try {
        prevChan.el.style.transform = "";
      } catch {}
    }
    chanMarqueeRef.current = { el: null, anim: null, key: "" };
  }, [isOpen.value]);

  const toggleFave = (sourceId) => {
    const id = String(sourceId || "");
    if (!id) return;
    const cur = faveIds.value instanceof Set ? faveIds.value : new Set();
    const next = new Set(cur);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    faveIds.value = next;
    saveGuidePrefs({ faves: next, favesOnly: favesOnly.value });
  };

  const toggleFavesOnly = () => {
    if (faveCount <= 0 && !favesOnly.value) return;
    const next = !favesOnly.value;
    favesOnly.value = next;
    saveGuidePrefs({ faves: faveIds.value, favesOnly: next });
  };

  useEffect(() => {
    if (!isOpen.value) return;
    const onResize = () => {
      if (!isNarrowGuide()) sidebarHidden.value = false;
    };
    window.addEventListener("resize", onResize, { passive: true });
    return () => {
      try {
        window.removeEventListener("resize", onResize);
      } catch {}
    };
  }, [isOpen.value]);

  // Ensure focused row is loaded (lazy load as the user navigates).
  useEffect(() => {
    if (!isOpen.value) return;
    const src = sourcesFlat[focusSourceIdx.value];
    if (src && !episodesBySource[src.id]) player.loadSourceEpisodes(src.id).catch(() => {});
  }, [isOpen.value, focusSourceIdx.value, sourcesFlat.length]);

  useEffect(() => {
    const onKey = (e) => {
      if (!isOpen.value) return;
      if (isEditableEl(e?.target) || isEditableEl(document.activeElement)) return;
      if (e.key === "Escape") {
        isOpen.value = false;
        return;
      }
      if (e.altKey || e.ctrlKey || e.metaKey) return;

      const sourcesNow = sourcesFlatRef.current || [];

      const k = String(e.key || "");
      const isArrow = k === "ArrowUp" || k === "ArrowDown" || k === "ArrowLeft" || k === "ArrowRight";
      const isSelect = k === "Enter" || k === "OK" || k === "Select";
      if (!isArrow && !isSelect) return;

      e.preventDefault();
      try {
        e.stopPropagation();
      } catch {}
      focusModeRef.current = "keys";
      keyNavAtRef.current = Date.now();

      if (k === "ArrowUp") {
        if (!sourcesNow.length) return;
        const curSrc = sourcesNow[focusSourceIdx.value] || null;
        const curSchedule = getSchedule(curSrc?.id);
        const curProg = curSchedule ? programAt(curSchedule, focusTs.value) : null;
        const refA = curProg?.startTs ?? (focusTs.value - 15 * MS_PER_MIN);
        const refB = curProg?.endTs ?? (focusTs.value + 15 * MS_PER_MIN);

        const lastIdx = Math.max(0, sourcesNow.length - 1);
        const nextIdx = focusSourceIdx.value <= 0 ? lastIdx : Math.max(0, focusSourceIdx.value - 1);
        focusSourceIdx.value = nextIdx;

        const nextSrc = sourcesNow[nextIdx] || null;
        const nextSchedule = getSchedule(nextSrc?.id);
        if (nextSchedule) {
          const p = pickBestProgForRange(nextSchedule, refA, refB);
          if (p) {
            const mid = Math.min(refA, refB) + (Math.abs(refB - refA) / 2);
            const pad = 1000;
            const t = (p.endTs - p.startTs > pad * 2)
              ? clamp(mid, p.startTs + pad, p.endTs - pad)
              : (p.startTs + p.endTs) / 2;
            focusTs.value = t;
          }
        }
        return;
      }
      if (k === "ArrowDown") {
        if (!sourcesNow.length) return;
        const curSrc = sourcesNow[focusSourceIdx.value] || null;
        const curSchedule = getSchedule(curSrc?.id);
        const curProg = curSchedule ? programAt(curSchedule, focusTs.value) : null;
        const refA = curProg?.startTs ?? (focusTs.value - 15 * MS_PER_MIN);
        const refB = curProg?.endTs ?? (focusTs.value + 15 * MS_PER_MIN);

        const lastIdx = Math.max(0, sourcesNow.length - 1);
        const nextIdx = focusSourceIdx.value >= lastIdx ? 0 : Math.min(lastIdx, focusSourceIdx.value + 1);
        focusSourceIdx.value = nextIdx;

        const nextSrc = sourcesNow[nextIdx] || null;
        const nextSchedule = getSchedule(nextSrc?.id);
        if (nextSchedule) {
          const p = pickBestProgForRange(nextSchedule, refA, refB);
          if (p) {
            const mid = Math.min(refA, refB) + (Math.abs(refB - refA) / 2);
            const pad = 1000;
            const t = (p.endTs - p.startTs > pad * 2)
              ? clamp(mid, p.startTs + pad, p.endTs - pad)
              : (p.startTs + p.endTs) / 2;
            focusTs.value = t;
          }
        }
        return;
      }

      if (k === "ArrowLeft") {
        const src = sourcesNow[focusSourceIdx.value];
        const schedule = getSchedule(src?.id);
        if (!schedule) {
          focusTs.value = focusTs.value - 30 * MS_PER_MIN;
          return;
        }
        const cur = programAt(schedule, focusTs.value);
        focusTs.value = (cur?.startTs || focusTs.value) - 1000;
        return;
      }
      if (k === "ArrowRight") {
        const src = sourcesNow[focusSourceIdx.value];
        const schedule = getSchedule(src?.id);
        if (!schedule) {
          focusTs.value = focusTs.value + 30 * MS_PER_MIN;
          return;
        }
        const cur = programAt(schedule, focusTs.value);
        focusTs.value = (cur?.endTs || focusTs.value) + 1000;
        return;
      }

      if (isSelect) {
        const src = sourcesNow[focusSourceIdx.value];
        if (!src) return;
        const schedule = getSchedule(src.id);
        const prog = schedule ? programAt(schedule, focusTs.value) : null;
        const ep = prog?.ep || null;
        if (!ep?.id) return;
        (async () => {
          await player.selectSource(src.id, { preserveEpisode: false, skipAutoEpisode: true, autoplay: true });
          await player.selectEpisode(ep.id, { autoplay: true });
          isOpen.value = false;
        })();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  // Note: only auto-scroll in response to keyboard navigation inside the guide.
  useEffect(() => {
    if (!isOpen.value) return;
    if (focusModeRef.current !== "keys") return;
    queueEnsureFocusVisible();
  }, [isOpen.value, focusSourceIdx.value, focusTs.value, sourcesFlat.length]);

  // Drag-to-pan inside the guide grid (touch + mouse).
  useEffect(() => {
    const el = tracksRef.current;
    if (!el) return;
    let down = null;
    const onDown = (e) => {
      if (!isOpen.value) return;
      if (e.pointerType && e.pointerType !== "mouse") return; // touch devices already pan natively
      if (e.button != null && e.button !== 0) return;
      if (e.target?.closest?.(".guideGridEp")) return;
      down = { id: e.pointerId, x: e.clientX, y: e.clientY, sl: el.scrollLeft, st: el.scrollTop };
      try {
        el.setPointerCapture(e.pointerId);
      } catch {}
      el.classList.add("dragging");
      try {
        e.preventDefault();
      } catch {}
    };
    const onMove = (e) => {
      if (!down || e.pointerId !== down.id) return;
      const dx = e.clientX - down.x;
      const dy = e.clientY - down.y;
      el.scrollLeft = down.sl - dx;
      el.scrollTop = down.st - dy;
    };
    const onUp = (e) => {
      if (!down || e.pointerId !== down.id) return;
      down = null;
      el.classList.remove("dragging");
      try {
        el.releasePointerCapture(e.pointerId);
      } catch {}
    };
    el.addEventListener("pointerdown", onDown);
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerup", onUp);
    el.addEventListener("pointercancel", onUp);
    return () => {
      el.removeEventListener("pointerdown", onDown);
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerup", onUp);
      el.removeEventListener("pointercancel", onUp);
    };
  }, []);

  // Narrow viewports: hide the channels sidebar when the user starts scrolling the schedule panel.
  useEffect(() => {
    const el = tracksRef.current;
    if (!el) return;
    const onPointerDown = (e) => {
      if (!isOpen.value) return;
      if (!isNarrowGuide()) return;
      if (sidebarHidden.value) return;
      if (e?.target?.closest?.(".guideGridEp")) return;
      if (e?.target?.closest?.(".guideSidebarToggle")) return;
      sidebarHideOnNextScrollRef.current = true;
      sidebarLastUserIntentAtRef.current = Date.now();
    };
    const onWheel = (e) => {
      if (!isOpen.value) return;
      if (!isNarrowGuide()) return;
      if (sidebarHidden.value) return;
      const dx = Number(e?.deltaX || 0);
      const dy = Number(e?.deltaY || 0);
      if (!dx && !dy) return;
      sidebarHideOnNextScrollRef.current = true;
      sidebarLastUserIntentAtRef.current = Date.now();
    };
    const onTouchStart = (e) => {
      if (!isOpen.value) return;
      if (!isNarrowGuide()) return;
      if (sidebarHidden.value) return;
      if (e?.target?.closest?.(".guideGridEp")) return;
      if (e?.target?.closest?.(".guideSidebarToggle")) return;
      sidebarHideOnNextScrollRef.current = true;
      sidebarLastUserIntentAtRef.current = Date.now();
    };
    el.addEventListener("pointerdown", onPointerDown, { passive: true });
    el.addEventListener("wheel", onWheel, { passive: true });
    el.addEventListener("touchstart", onTouchStart, { passive: true });
    return () => {
      el.removeEventListener("pointerdown", onPointerDown);
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("touchstart", onTouchStart);
    };
  }, [isOpen.value]);

  // Track real mouse movement so hover focus doesn't trigger from programmatic scrolling.
  useEffect(() => {
    if (!isOpen.value) return;
    const onMove = (e) => {
      if (e?.pointerType && e.pointerType !== "mouse") return;
      lastPointerMoveAtRef.current = Date.now();
    };
    document.addEventListener("pointermove", onMove, { passive: true });
    document.addEventListener("mousemove", onMove, { passive: true });
    return () => {
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("mousemove", onMove);
    };
  }, [isOpen.value]);

  const currentSource = (sources.value || []).find((s) => s.id === currentSourceId) || null;
  const currentEpTitle = player.current.value.episode?.title || "—";

  const focusedSource = sourcesFlat[focusSourceIdx.value] || null;
  const focusedSchedule = getSchedule(focusedSource?.id);
  const focusedProg = focusedSchedule ? programAt(focusedSchedule, focusTs.value) : null;
  const focusedEp = focusedProg?.ep || null;
  const focusedTimeRange = focusedProg ? `${fmtClock(focusedProg.startTs)} – ${fmtClock(focusedProg.endTs)}` : "";

  const timeTicks = useMemo(() => {
    const out = [];
    const start = trackStartTs.value;
    // Tick density: aim for <= ~140 ticks.
    let tickStepMin = 30;
    while ((VIRTUAL_MIN / tickStepMin) > 140) tickStepMin *= 2;
    for (let m = 0; m <= VIRTUAL_MIN; m += tickStepMin) {
      const x = Math.round(m * PX_PER_MIN);
      out.push({ m, x, label: fmtClock(start + m * MS_PER_MIN) });
    }
    return out;
  }, [trackStartTs.value]);

  const viewStartTs = useMemo(() => trackStartTs.value + (scrollLeftPx.value / PX_PER_MIN) * MS_PER_MIN, [trackStartTs.value, scrollLeftPx.value]);
  const viewEndTs = useMemo(() => viewStartTs + ((viewportW.value || 0) / PX_PER_MIN) * MS_PER_MIN, [viewStartTs, viewportW.value]);
  const renderStartTs = viewStartTs - TIME_BUFFER_MIN * MS_PER_MIN;
  const renderEndTs = viewEndTs + TIME_BUFFER_MIN * MS_PER_MIN;

  const visibleRange = useMemo(() => {
    const top = scrollTopPx.value || 0;
    const startRow = clamp(Math.floor(top / GUIDE_ROW_H_PX) - ROW_OVERSCAN, 0, Math.max(0, sourcesFlat.length - 1));
    const rowsVisible = Math.ceil(((viewportH.value || 0) + GUIDE_ROW_H_PX) / GUIDE_ROW_H_PX) + ROW_OVERSCAN * 2;
    const endRow = clamp(startRow + rowsVisible, 0, sourcesFlat.length);
    return { startRow, endRow };
  }, [scrollTopPx.value, viewportH.value, sourcesFlat.length]);

  const visibleSources = useMemo(
    () => sourcesFlat.slice(visibleRange.startRow, visibleRange.endRow),
    [sourcesFlat, visibleRange.startRow, visibleRange.endRow]
  );

  // Keep scroll state up to date (read-only; no pane sync and no focus-follow scrolling).
  useEffect(() => {
    const tracksEl = tracksRef.current;
    if (!tracksEl) return;
    let raf = 0;
    let ro = null;

    const update = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        viewportW.value = tracksEl.clientWidth || 0;
        viewportH.value = tracksEl.clientHeight || 0;
        scrollLeftPx.value = tracksEl.scrollLeft || 0;
        scrollTopPx.value = tracksEl.scrollTop || 0;
      });
    };

    const onScroll = () => {
      lastScrollAtRef.current = Date.now();
      if (isOpen.value && isNarrowGuide() && !sidebarHidden.value) {
        const pending = !!sidebarHideOnNextScrollRef.current;
        const intentAt = Number(sidebarLastUserIntentAtRef.current) || 0;
        const recentIntent = Date.now() - intentAt < 1500;
        const lastKeys = Number(keyNavAtRef.current) || 0;
        const recentKeys = Date.now() - lastKeys < 700;
        if (pending && recentIntent && !recentKeys) {
          sidebarHidden.value = true;
          sidebarHideOnNextScrollRef.current = false;
        }
      }
      update();
    };

    update();
    tracksEl.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", update);

    if (typeof ResizeObserver !== "undefined") {
      ro = new ResizeObserver(() => update());
      try {
        ro.observe(tracksEl);
      } catch {}
    }

    return () => {
      try {
        tracksEl.removeEventListener("scroll", onScroll);
      } catch {}
      try {
        window.removeEventListener("resize", update);
      } catch {}
      if (ro) {
        try {
          ro.disconnect();
        } catch {}
      }
      if (raf) cancelAnimationFrame(raf);
    };
  }, []);

  // When filtering changes the scrollable content, re-sample scroll state (read-only).
  useEffect(() => {
    const tracksEl = tracksRef.current;
    if (!tracksEl) return;
    requestAnimationFrame(() => {
      viewportW.value = tracksEl.clientWidth || 0;
      viewportH.value = tracksEl.clientHeight || 0;
      scrollLeftPx.value = tracksEl.scrollLeft || 0;
      scrollTopPx.value = tracksEl.scrollTop || 0;
    });
  }, [filterKey, sourcesFlat.length]);

  useEffect(() => {
    return () => {
      if (keyScrollRafRef.current) cancelAnimationFrame(keyScrollRafRef.current);
      keyScrollRafRef.current = 0;
    };
  }, []);

  // Focused episode title: marquee shortly after highlight (E.P.G. style).
  useEffect(() => {
    if (!isOpen.value) return;
    const key = `${focusSourceIdx.value}::${Math.round((Number(focusTs.value) || 0) / 1000)}`;
    const prev = marqueeRef.current || null;
    if (prev?.key === key) return;

    if (prev?.anim) {
      try {
        prev.anim.cancel();
      } catch {}
    }
    if (prev?.el) {
      try {
        prev.el.style.transform = "";
      } catch {}
    }
    marqueeRef.current = { el: null, anim: null, key };

    const t = setTimeout(() => {
      try {
        const titleEl = document.querySelector(".guideGridEp.focused .guideGridEpTitle");
        const textEl = document.querySelector(".guideGridEp.focused .guideGridEpTitleText");
        if (!titleEl || !textEl) return;
        const overflow = Math.max(0, (textEl.scrollWidth || 0) - (titleEl.clientWidth || 0));
        if (!Number.isFinite(overflow) || overflow < 18) return;
        if (typeof textEl.animate !== "function") return;

        const pxPerMs = 0.045;
        const moveMs = clamp(Math.round(overflow / pxPerMs), 1800, 11000);
        const totalMs = clamp(moveMs + 1700, 3200, 14000);
        const anim = textEl.animate(
          [
            { transform: "translateX(0px)", offset: 0 },
            { transform: "translateX(0px)", offset: 0.18 },
            { transform: `translateX(${-overflow}px)`, offset: 0.82 },
            { transform: `translateX(${-overflow}px)`, offset: 1 },
          ],
          { duration: totalMs, delay: 650, iterations: Infinity, easing: "linear" }
        );
        marqueeRef.current = { el: textEl, anim, key };
      } catch {}
    }, 0);

    return () => {
      clearTimeout(t);
      const cur = marqueeRef.current || null;
      if (cur?.key !== key) return;
      if (cur?.anim) {
        try {
          cur.anim.cancel();
        } catch {}
      }
      if (cur?.el) {
        try {
          cur.el.style.transform = "";
        } catch {}
      }
      marqueeRef.current = { el: null, anim: null, key: "" };
    };
  }, [isOpen.value, focusSourceIdx.value, focusTs.value]);

  // Focused channel title: marquee shortly after highlight.
  useEffect(() => {
    if (!isOpen.value) return;
    const src = sourcesFlat[focusSourceIdx.value] || null;
    const key = String(src?.id || focusSourceIdx.value);
    const prev = chanMarqueeRef.current || null;
    if (prev?.key === key) return;

    if (prev?.anim) {
      try {
        prev.anim.cancel();
      } catch {}
    }
    if (prev?.el) {
      try {
        prev.el.style.transform = "";
      } catch {}
    }
    chanMarqueeRef.current = { el: null, anim: null, key };

    const t = setTimeout(() => {
      try {
        const nameEl = document.querySelector(".guideGridChanRow.focused .guideGridChanName");
        const textEl = document.querySelector(".guideGridChanRow.focused .guideGridChanNameText");
        if (!nameEl || !textEl) return;
        const overflow = Math.max(0, (textEl.scrollWidth || 0) - (nameEl.clientWidth || 0));
        if (!Number.isFinite(overflow) || overflow < 18) return;
        if (typeof textEl.animate !== "function") return;

        const pxPerMs = 0.045;
        const moveMs = clamp(Math.round(overflow / pxPerMs), 1600, 9000);
        const totalMs = clamp(moveMs + 1600, 3000, 12000);
        const anim = textEl.animate(
          [
            { transform: "translateX(0px)", offset: 0 },
            { transform: "translateX(0px)", offset: 0.18 },
            { transform: `translateX(${-overflow}px)`, offset: 0.82 },
            { transform: `translateX(${-overflow}px)`, offset: 1 },
          ],
          { duration: totalMs, delay: 650, iterations: Infinity, easing: "linear" }
        );
        chanMarqueeRef.current = { el: textEl, anim, key };
      } catch {}
    }, 0);

    return () => {
      clearTimeout(t);
      const cur = chanMarqueeRef.current || null;
      if (cur?.key !== key) return;
      if (cur?.anim) {
        try {
          cur.anim.cancel();
        } catch {}
      }
      if (cur?.el) {
        try {
          cur.el.style.transform = "";
        } catch {}
      }
      chanMarqueeRef.current = { el: null, anim: null, key: "" };
    };
  }, [isOpen.value, focusSourceIdx.value, sourcesFlat.length, filterKey]);

  // Lazy-load episodes for channels as they come into view (slow/steady).
  useEffect(() => {
    if (!isOpen.value) return;
    const loadingRef = loadingIdsRef.current;
    let canceled = false;
    const pump = async () => {
      const missing = [];
      for (let i = visibleRange.startRow; i < visibleRange.endRow; i++) {
        const src = sourcesFlat[i];
        if (!src) continue;
        if (episodesBySource[src.id]) continue;
        if (loadingRef.has(src.id)) continue;
        missing.push(src.id);
        if (missing.length >= 3) break;
      }
      for (const id of missing) {
        if (canceled) return;
        loadingRef.add(id);
        try {
          await player.loadSourceEpisodes(id);
        } catch {
          loadingRef.delete(id);
        }
      }
    };
    const t = setTimeout(pump, 120);
    return () => {
      canceled = true;
      clearTimeout(t);
    };
  }, [isOpen.value, visibleRange.startRow, visibleRange.endRow, sourcesFlat, Object.keys(episodesBySource).length]);

  return html`
    <div id="guidePanel" class="guidePanel" aria-hidden=${isOpen.value ? "false" : "true"}>
      <div class="guidePanel-inner">
        <div
          class=${"guideGridShell" + (sidebarHidden.value ? " sidebarHidden" : "")}
          style=${{ "--guide-row-h": `${GUIDE_ROW_H_PX}px` }}
          role="application"
          aria-label="TV guide"
        >
          <button
            class="guideSidebarToggle"
            title="Show channels"
            aria-label="Show channels"
            onClick=${() => (sidebarHidden.value = false)}
            onPointerDown=${(e) => e.stopPropagation()}
          >
            Channels
          </button>
          <div class="guideGridHeaderRow">
            <div
              class="guideGridCorner"
              role="button"
              tabIndex=${0}
              title="Jump to what's playing"
              onClick=${() => jumpToPlaying({ alignNow: true })}
              onKeyDown=${(e) => {
                if (e.key === "Enter") jumpToPlaying({ alignNow: true });
              }}
            >
              <div class="guideGridCornerTop">
                ${cornerTitle} <span class="guideGridCornerTopCount">${selectedChanCount}/${totalChanCount}</span>
              </div>
              <div class="guideGridCornerSub">
                <div class="guideGridFilterRow">
                  <input
                    class="guideFilterInput"
                    type="text"
                    placeholder="Filter channels/episodes…"
                    value=${filterText.value}
                    onInput=${(e) => (filterText.value = e?.target?.value ?? "")}
                    onClick=${(e) => e.stopPropagation()}
                    onPointerDown=${(e) => e.stopPropagation()}
                    onKeyDown=${(e) => e.stopPropagation()}
                    aria-label="Filter guide"
                  />
                  ${filterKey
                    ? html`<button
                        class="guideFilterClear"
                        title="Clear filter"
                        onClick=${(e) => {
                          e.stopPropagation();
                          filterText.value = "";
                        }}
                        onPointerDown=${(e) => e.stopPropagation()}
                      >
                        ✕
                      </button>`
                    : ""}
                </div>
              </div>
            </div>
            <div class="guideGridHeaderScroll" aria-hidden="true" onWheel=${wheelToTracks}>
              <div class="guideGridTimeAxis" style=${{ width: `${HORIZON_PX}px`, transform: `translateX(${-scrollLeftPx.value}px)` }}>
                ${timeTicks.map((t) => {
                  return html`
                    <div class="guideGridTick" style=${{ left: `${t.x}px` }}>
                      <span class="guideGridTickLabel">${t.label}</span>
                    </div>
                  `;
                })}
              </div>
            </div>
            <div class="guideGridHeaderActions">
              <button
                class=${"guideGridHeaderBtn guideGridHeaderBtnFaves" + (favesOnly.value ? " active" : "")}
                disabled=${faveCount <= 0 && !favesOnly.value}
                aria-disabled=${faveCount <= 0 && !favesOnly.value ? "true" : "false"}
                title=${faveCount > 0
                  ? favesOnly.value
                    ? "Show all channels"
                    : "Show favorites only"
                  : favesOnly.value
                    ? "No favorite channels left (turn off to clear)"
                    : "No favorite channels yet"}
                aria-pressed=${favesOnly.value ? "true" : "false"}
                data-navitem="1"
                onClick=${(e) => {
                  e.stopPropagation?.();
                  toggleFavesOnly();
                }}
                onPointerDown=${(e) => e.stopPropagation()}
              >
                ${favesOnly.value ? "Show All" : "Faves Only"}
              </button>
              <button
                class="guideGridHeaderBtn guideGridHeaderBtnClose"
                title="Close guide"
                aria-label="Close guide"
                data-navitem="1"
                onClick=${(e) => {
                  e.stopPropagation?.();
                  isOpen.value = false;
                }}
                onPointerDown=${(e) => e.stopPropagation()}
              >
                ✕
              </button>
            </div>
          </div>

          <div class="guideGridBodyRow">
            <div class="guideGridChannelsScroll" aria-label="Channels" onWheel=${wheelToTracks}>
              <div class="guideGridChannelsInner" style=${{ transform: `translateY(${-scrollTopPx.value}px)` }}>
                <div class="guideGridSpacer" style=${{ height: `${visibleRange.startRow * GUIDE_ROW_H_PX}px` }} aria-hidden="true"></div>
                ${visibleSources.map((src, vi) => {
                  const i = visibleRange.startRow + vi;
                  const eps = episodesBySource[src.id] || null;
                  const feat = src.features || {};
                  const ccLikely = !!feat.hasPlayableTranscript || (!!eps && eps.some((ep) => (ep.transcripts || []).length));
                  const isAudioOnly =
                    feat.hasVideo === false ||
                    (!!eps &&
                      eps.length > 0 &&
                      eps.filter(isPlayableVideoEp).every((ep) => ep?.media?.pickedIsVideo === false));

                  const rowClass =
                    "guideGridChanRow" +
                    (i === focusSourceIdx.value ? " focused" : "") +
                    (currentSourceId === src.id ? " playing" : "");
                  const chanIdx = chanNoById.get(src.id) ?? i;
                  const chanNo = String(101 + chanIdx).padStart(3, "0");
                  const isFave = faveIds.value instanceof Set ? faveIds.value.has(src.id) : false;
                  return html`
                    <div class=${rowClass} data-source-id=${src.id}>
                      <div
                        class="guideGridChannelCell"
                        role="button"
                        tabIndex=${0}
                        data-navitem="1"
                        onPointerEnter=${() => {
                          if (!shouldAllowHoverFocus()) return;
                          focusModeRef.current = "hover";
                          focusSourceIdx.value = i;
                        }}
                        onClick=${() => {
                          focusModeRef.current = "keys";
                          focusSourceIdx.value = i;
                          if (!episodesBySource[src.id]) player.loadSourceEpisodes(src.id).catch(() => {});
                        }}
                        onKeyDown=${(e) => {
                          if (e.key === "Enter") {
                            focusModeRef.current = "keys";
                            focusSourceIdx.value = i;
                            if (!episodesBySource[src.id]) player.loadSourceEpisodes(src.id).catch(() => {});
                          }
                        }}
                      >
                        <button
                          class=${"guideGridChanFave" + (isFave ? " on" : "")}
                          title=${isFave ? "Unfavorite channel" : "Favorite channel"}
                          aria-label=${isFave ? "Unfavorite channel" : "Favorite channel"}
                          aria-pressed=${isFave ? "true" : "false"}
                          onClick=${(e) => {
                            e.preventDefault?.();
                            e.stopPropagation?.();
                            toggleFave(src.id);
                          }}
                          onPointerDown=${(e) => {
                            e.preventDefault?.();
                            e.stopPropagation?.();
                          }}
                        >
                          ${isFave ? "★" : "☆"}
                        </button>
                        <div class="guideGridChanMeta">
                          <div class="guideGridChanName">
                            <span class="guideGridChanNameText">${src.title || src.id}</span>
                          </div>
                          <div class="guideGridChanSub">
                            <span class="guideGridChanBadges">
                              ${ccLikely ? html`<span class="guideBadge guideBadge-cc" title="Captions likely available">CC</span>` : ""}
                            </span>
                            <span class="guideGridChanNo mono" aria-hidden="true">
                              ${chanNo}
                              ${isAudioOnly ? html`<span class="guideGridChanAudioIcon" title="Audio only"><${HeadphonesIcon} size=${12} /></span>` : ""}
                            </span>
                          </div>
                        </div>
                      </div>
                    </div>
                  `;
                })}
                <div
                  class="guideGridSpacer"
                  style=${{ height: `${Math.max(0, (sourcesFlat.length - visibleRange.endRow) * GUIDE_ROW_H_PX)}px` }}
                  aria-hidden="true"
                ></div>
              </div>
            </div>

            <div class="guideGridTracksScroll" ref=${tracksRef} aria-label="Schedule">
              <div class="guideGridSpacer" style=${{ height: `${visibleRange.startRow * GUIDE_ROW_H_PX}px` }} aria-hidden="true"></div>
              ${visibleSources.map((src, vi) => {
                const i = visibleRange.startRow + vi;
                const eps = episodesBySource[src.id] || null;
                const schedule = getSchedule(src.id);
                const blocks = schedule ? blocksForRange(schedule, renderStartTs, renderEndTs) : [];
                let newBadgesShown = 0;
                const nowMs = Date.now();
                const baseCycleNo =
                  schedule?.cycleSec
                    ? Math.floor(((Number(viewStartTs) - guideZeroTs.value) / 1000) / schedule.cycleSec)
                    : 0;

                const rowClass =
                  "guideGridTrackRow" +
                  (i === focusSourceIdx.value ? " focused" : "") +
                  (currentSourceId === src.id ? " playing" : "");

                return html`
                  <div class=${rowClass} data-source-id=${src.id}>
                    <div class="guideGridTrack" style=${{ width: `${HORIZON_PX}px` }}>
                      ${eps
                        ? schedule
                          ? blocks.map((b) => {
                              const ep = b.ep;
                              const durSec = b.durSec;
                              const x = Math.round(((b.startTs - trackStartTs.value) / MS_PER_MIN) * PX_PER_MIN);
                              const w0 = Math.round((durSec / 60) * PX_PER_MIN);
                              const w = Math.max(28, w0);
                              const active = currentSourceId === src.id && currentEpisodeId === ep.id;
                              const relSec = (Number(b.startTs) - guideZeroTs.value) / 1000;
                              const cycleNo =
                                schedule?.cycleSec && Number.isFinite(relSec) ? Math.floor(relSec / schedule.cycleSec) : 0;
                              const isRepeat = cycleNo !== baseCycleNo;
                              const epHasCc = (ep.transcripts || []).length > 0;
                              const showNew = newBadgesShown < 2 && isEpisodeNew(ep, nowMs);
                              if (showNew) newBadgesShown += 1;
                              const maxSec =
                                typeof player.getProgressMaxSec === "function"
                                  ? player.getProgressMaxSec(src.id, ep.id)
                                  : typeof player.getProgressSec === "function"
                                    ? player.getProgressSec(src.id, ep.id)
                                    : 0;
                              const pct = durSec > 0 && maxSec > 0 ? Math.min(100, (Math.max(0, maxSec) / durSec) * 100) : 0;
                              const isFocused =
                                i === focusSourceIdx.value &&
                                focusedProg &&
                                Math.abs(Number(focusedProg.startTs) - Number(b.startTs)) < 500 &&
                                focusedProg.ep?.id === ep.id;
                              const dur = fmtDuration(Number(ep.durationSec) > 0 ? Number(ep.durationSec) : durSec) || "";
                              const pub = fmtPubDateShort(ep, nowMs);
                              return html`
                                <button
                                  class=${"guideGridEp" + (active ? " active" : "") + (isFocused ? " focused" : "") + (isRepeat ? " repeat" : "")}
                                  style=${{ left: `${x}px`, width: `${w}px` }}
                                  data-ep-id=${ep.id}
                                  data-prog-start=${String(b.startTs)}
                                  data-source-id=${src.id}
                                  data-navitem="1"
                                  aria-label=${`${ep.title || "Episode"}${epHasCc ? " (CC)" : ""}${showNew ? " (New)" : ""}${isRepeat ? " (Repeat)" : ""}`}
                                  onPointerEnter=${() => {
                                    if (!shouldAllowHoverFocus()) return;
                                    focusModeRef.current = "hover";
                                    focusSourceIdx.value = i;
                                    focusTs.value = Number(b.startTs) + 1000;
                                  }}
                                  onClick=${async () => {
                                    focusModeRef.current = "keys";
                                    await player.selectSource(src.id, { preserveEpisode: false, skipAutoEpisode: true, autoplay: true });
                                    await player.selectEpisode(ep.id, { autoplay: true });
                                  isOpen.value = false;
                                  }}
                                >
                                  <div class="guideGridEpProgress" style=${{ width: `${pct}%` }} aria-hidden="true"></div>
                                  <div class="guideGridEpTop">
                                    <span class="guideGridEpTitle"><span class="guideGridEpTitleText">${ep.title || "Episode"}</span></span>
                                  </div>
                                  <div class="guideGridEpMeta">
                                    <span class="guideGridEpMetaLeft">
                                      <span class="guideGridEpDur">${dur}</span>
                                      ${pub ? html`<span class="guideGridEpPub">• ${pub}</span>` : ""}
                                    </span>
                                    <span class="guideGridEpMetaRight">
                                      ${showNew
                                        ? html`<span class="guideGridEpBadge guideBadge guideBadge-new guideGridEpMiniBadge" title="New (released within the last 30 days)">!</span>`
                                        : ""}
                                      ${epHasCc
                                        ? html`<span class="guideGridEpBadge guideBadge guideBadge-cc guideGridEpMiniBadge" title="Captions available">CC</span>`
                                        : ""}
                                    </span>
                                  </div>
                                </button>
                              `;
                            })
                          : html`
                              <button class="guideGridEp guideGridEpLoad" style=${{ left: "0px", width: "260px" }} disabled>
                                No playable videos
                              </button>
                            `
                        : html`
                            <button
                              class="guideGridEp guideGridEpLoad"
                              style=${{ left: "0px", width: "220px" }}
                              onClick=${async () => {
                                await player.loadSourceEpisodes(src.id);
                              }}
                            >
                              Loading…
                            </button>
                          `}
                    </div>
                  </div>
                `;
              })}
              <div
                class="guideGridSpacer"
                style=${{ height: `${Math.max(0, (sourcesFlat.length - visibleRange.endRow) * GUIDE_ROW_H_PX)}px` }}
                aria-hidden="true"
              ></div>
            </div>
          </div>
        </div>
        <div class="guidePanel-episodes" id="guideEpisodes">
          <button
            class="guideNowBack"
            title="Close guide"
            aria-label="Close guide"
            data-navitem="1"
            data-keyhint="Esc — Close"
            onClick=${() => (isOpen.value = false)}
          >
            ←
          </button>
          <div class="guideNowContent">
            <div class="guideNowLabel">
              ${focusedSource ? focusedSource.title || focusedSource.id : "—"} ${focusedTimeRange ? html`<span class="guideNowSep">•</span>` : ""}
              ${focusedTimeRange}
            </div>
            <div class="guideNowEp">${focusedEp ? focusedEp.title || "—" : "—"}</div>
            <div class="guideNowSub">${currentSource ? `Playing: ${currentEpTitle}` : ""}</div>
          </div>
        </div>
      </div>
    </div>
  `;
}
