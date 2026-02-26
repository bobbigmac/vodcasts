import { html, useEffect, useMemo, useRef, useSignal } from "../runtime/vendor.js";

const CATEGORY_ORDER = ["church", "university", "fitness", "bible", "twit", "podcastindex", "other", "needs-rss"];

function fmtDuration(sec) {
  if (!Number.isFinite(sec) || sec < 0) return null;
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (h > 0) return `${h}h${m}m`;
  if (m > 0) return `${m}m`;
  return `${Math.floor(sec)}s`;
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

export function GuidePanel({ isOpen, sources, player }) {
  const currentSourceId = player.currentSourceId.value;
  const currentEpisodeId = player.currentEpisodeId.value;
  const episodesBySource = player.sourceEpisodes.value || {};
  const sourcesFlat = useMemo(() => buildSourcesFlat(sources.value || []), [sources.value]);

  const focusSourceIdx = useSignal(Math.max(0, sourcesFlat.findIndex((s) => s.id === currentSourceId)));
  const focusEpIdx = useSignal(0);
  const guideStartTs = useSignal(roundToHalfHour(Date.now()));
  const scrollRef = useRef(null);

  const PX_PER_MIN = 6;
  const HORIZON_HOURS = 6;
  const HORIZON_SEC = HORIZON_HOURS * 3600;
  const HORIZON_PX = Math.round((HORIZON_SEC / 60) * PX_PER_MIN);
  const DEFAULT_EP_SEC = 30 * 60;
  const MIN_BLOCK_PX = Math.round(8 * PX_PER_MIN);

  const playableFor = (sourceId) => {
    const eps = sourceId ? episodesBySource[sourceId] || null : null;
    return (eps || []).filter((ep) => ep.media?.url);
  };

  const horizonBlocksFor = (playable) => {
    let curSec = 0;
    let count = 0;
    for (let j = 0; j < (playable || []).length; j++) {
      const ep = playable[j];
      const durSec = Number(ep?.durationSec) > 0 ? Number(ep.durationSec) : DEFAULT_EP_SEC;
      if (curSec >= HORIZON_SEC) break;
      curSec += durSec;
      count++;
    }
    return count;
  };

  useEffect(() => {
    if (!isOpen.value) return;
    guideStartTs.value = roundToHalfHour(Date.now());
    focusSourceIdx.value = Math.max(0, sourcesFlat.findIndex((s) => s.id === currentSourceId));
    const srcId = sourcesFlat[focusSourceIdx.value]?.id;
    const playable0 = playableFor(srcId);
    const curIdx = currentEpisodeId ? playable0.findIndex((ep) => ep.id === currentEpisodeId) : -1;
    focusEpIdx.value = Math.max(0, Math.min(horizonBlocksFor(playable0) - 1, curIdx >= 0 ? curIdx : 0));
    if (currentSourceId && !episodesBySource[currentSourceId]) {
      player.loadSourceEpisodes(currentSourceId).catch(() => {});
    }
  }, [isOpen.value, currentSourceId, sourcesFlat.length]);

  // Ensure focused row is loaded (lazy load as the user navigates).
  useEffect(() => {
    if (!isOpen.value) return;
    const src = sourcesFlat[focusSourceIdx.value];
    if (src && !episodesBySource[src.id]) player.loadSourceEpisodes(src.id).catch(() => {});
    const playable = playableFor(src?.id);
    const maxIdx = Math.max(0, horizonBlocksFor(playable) - 1);
    if (focusEpIdx.value > maxIdx) focusEpIdx.value = maxIdx;
  }, [isOpen.value, focusSourceIdx.value, sourcesFlat.length]);

  useEffect(() => {
    const onKey = (e) => {
      if (!isOpen.value) return;
      if (e.key === "Escape") {
        isOpen.value = false;
        return;
      }
      if (e.altKey || e.ctrlKey || e.metaKey) return;

      const k = String(e.key || "");
      const isArrow = k === "ArrowUp" || k === "ArrowDown" || k === "ArrowLeft" || k === "ArrowRight";
      const isSelect = k === "Enter" || k === "OK" || k === "Select";
      if (!isArrow && !isSelect) return;

      e.preventDefault();

      if (k === "ArrowUp") {
        focusSourceIdx.value = Math.max(0, focusSourceIdx.value - 1);
        focusEpIdx.value = Math.max(0, focusEpIdx.value);
        return;
      }
      if (k === "ArrowDown") {
        focusSourceIdx.value = Math.min(Math.max(0, sourcesFlat.length - 1), focusSourceIdx.value + 1);
        focusEpIdx.value = Math.max(0, focusEpIdx.value);
        return;
      }

      const src = sourcesFlat[focusSourceIdx.value];
      const playable = playableFor(src?.id);
      const maxIdx = Math.max(0, horizonBlocksFor(playable) - 1);
      if (k === "ArrowLeft") {
        focusEpIdx.value = Math.max(0, focusEpIdx.value - 1);
        return;
      }
      if (k === "ArrowRight") {
        focusEpIdx.value = Math.min(maxIdx, focusEpIdx.value + 1);
        return;
      }

      if (isSelect) {
        if (!src || !playable.length) return;
        const ep = playable[Math.min(maxIdx, Math.max(0, focusEpIdx.value))];
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

  // Scroll the focused cell into view.
  useEffect(() => {
    if (!isOpen.value) return;
    const src = sourcesFlat[focusSourceIdx.value];
    if (!src) return;
    const root = scrollRef.current;
    if (!root) return;
    const q = `.guideGridEp[data-source-id="${escSel(src.id)}"][data-ep-idx="${String(focusEpIdx.value)}"]`;
    const el = root.querySelector(q);
    if (!el) return;
    try {
      el.scrollIntoView({ block: "nearest", inline: "nearest" });
    } catch {}
  }, [isOpen.value, focusSourceIdx.value, focusEpIdx.value, sourcesFlat.length]);

  // Drag-to-pan inside the guide grid (touch + mouse).
  useEffect(() => {
    const el = scrollRef.current;
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

  const currentSource = (sources.value || []).find((s) => s.id === currentSourceId) || null;
  const currentEpTitle = player.current.value.episode?.title || "—";

  const focusedSource = sourcesFlat[focusSourceIdx.value] || null;
  const focusedPlayable = playableFor(focusedSource?.id);
  const focusedEp = focusedPlayable[Math.max(0, Math.min(focusedPlayable.length - 1, focusEpIdx.value))] || null;
  const focusedTimeRange = useMemo(() => {
    if (!focusedEp) return "";
    let startSec = 0;
    for (let i = 0; i < Math.max(0, focusEpIdx.value); i++) {
      const ep = focusedPlayable[i];
      if (!ep) break;
      const durSec = Number(ep.durationSec) > 0 ? Number(ep.durationSec) : DEFAULT_EP_SEC;
      startSec += durSec;
    }
    const durSec = Number(focusedEp.durationSec) > 0 ? Number(focusedEp.durationSec) : DEFAULT_EP_SEC;
    const a = fmtClock(guideStartTs.value + startSec * 1000);
    const b = fmtClock(guideStartTs.value + (startSec + durSec) * 1000);
    return `${a} – ${b}`;
  }, [focusedEp?.id, focusEpIdx.value, focusedPlayable.length, guideStartTs.value]);

  const timeTicks = useMemo(() => {
    const out = [];
    const start = guideStartTs.value;
    for (let m = 0; m <= HORIZON_HOURS * 60; m += 30) {
      const x = Math.round(m * PX_PER_MIN);
      out.push({ m, x, label: fmtClock(start + m * 60 * 1000) });
    }
    return out;
  }, [guideStartTs.value]);

  return html`
    <div id="guidePanel" class="guidePanel" aria-hidden=${isOpen.value ? "false" : "true"}>
      <div class="guidePanel-inner">
        <div
          class="guideGridScroll"
          id="guideGrid"
          ref=${scrollRef}
          style=${{ "--guide-horizon": `${HORIZON_PX}px` }}
          role="application"
          aria-label="TV guide"
        >
          <div class="guideGridHeaderRow">
            <div class="guideGridCorner">
              <div class="guideGridCornerTop">All Channels</div>
              <div class="guideGridCornerSub">Today ${fmtClock(guideStartTs.value)}</div>
            </div>
            <div class="guideGridTimeAxis" style=${{ width: `${HORIZON_PX}px` }}>
              ${timeTicks.map((t) => {
                return html`
                  <div class="guideGridTick" style=${{ left: `${t.x}px` }}>
                    <span class="guideGridTickLabel">${t.label}</span>
                  </div>
                `;
              })}
            </div>
          </div>

          <div class="guideGridBody">
            ${sourcesFlat.map((src, i) => {
              const eps = episodesBySource[src.id] || null;
              const playable = (eps || []).filter((ep) => ep.media?.url);
              const feat = src.features || {};
              const ccLikely = !!feat.hasPlayableTranscript || (!!eps && eps.some((ep) => (ep.transcripts || []).length));

              let curSec = 0;
              const blocks = [];
              for (let j = 0; j < playable.length; j++) {
                const ep = playable[j];
                if (curSec >= HORIZON_SEC) break;

                const durSecRaw = Number(ep.durationSec);
                const maxSec =
                  typeof player.getProgressMaxSec === "function"
                    ? player.getProgressMaxSec(src.id, ep.id)
                    : typeof player.getProgressSec === "function"
                      ? player.getProgressSec(src.id, ep.id)
                      : 0;
                const durSec =
                  Number.isFinite(durSecRaw) && durSecRaw > 0
                    ? durSecRaw
                    : Math.max(DEFAULT_EP_SEC, Number.isFinite(maxSec) && maxSec > 0 ? Math.ceil(maxSec) + 60 : DEFAULT_EP_SEC);

                const x = Math.round((curSec / 60) * PX_PER_MIN);
                const w0 = Math.round((durSec / 60) * PX_PER_MIN);
                const w = Math.max(MIN_BLOCK_PX, Math.min(w0, Math.max(32, HORIZON_PX - x)));
                const endX = x + w;
                blocks.push({ ep, j, x, w, endX, durSec });
                curSec += durSec;
              }

              const rowClass =
                "guideGridRow" +
                (i === focusSourceIdx.value ? " focused" : "") +
                (currentSourceId === src.id ? " playing" : "");

              const chanNo = String(101 + i).padStart(3, "0");

              return html`
                <div class=${rowClass} data-source-id=${src.id}>
                  <div
                    class="guideGridChannelCell"
                    role="button"
                    tabIndex=${0}
                    data-navitem="1"
                    onClick=${() => {
                      focusSourceIdx.value = i;
                      if (!episodesBySource[src.id]) player.loadSourceEpisodes(src.id).catch(() => {});
                    }}
                    onKeyDown=${(e) => {
                      if (e.key === "Enter") {
                        focusSourceIdx.value = i;
                        if (!episodesBySource[src.id]) player.loadSourceEpisodes(src.id).catch(() => {});
                      }
                    }}
                  >
                    <div class="guideGridChanNo mono">${chanNo}</div>
                    <div class="guideGridChanMeta">
                      <div class="guideGridChanName">${src.title || src.id}</div>
                      <div class="guideGridChanBadges">
                        ${ccLikely ? html`<span class="guideBadge guideBadge-cc" title="Captions likely available">CC</span>` : ""}
                      </div>
                    </div>
                  </div>
                  <div class="guideGridTrack" style=${{ width: `${HORIZON_PX}px` }}>
                    ${eps
                      ? blocks.map((b) => {
                          const ep = b.ep;
                          const active = currentEpisodeId === ep.id;
                          const epHasCc = (ep.transcripts || []).length > 0;
                          const maxSec =
                            typeof player.getProgressMaxSec === "function"
                              ? player.getProgressMaxSec(src.id, ep.id)
                              : typeof player.getProgressSec === "function"
                                ? player.getProgressSec(src.id, ep.id)
                                : 0;
                          const durSec = Number(ep.durationSec) > 0 ? Number(ep.durationSec) : 0;
                          const pct = durSec > 0 && maxSec > 0 ? Math.min(100, (Math.max(0, maxSec) / durSec) * 100) : 0;
                          const isFocused = i === focusSourceIdx.value && b.j === focusEpIdx.value;
                          const dur = fmtDuration(ep.durationSec) || (ep.dateText || "");
                          return html`
                            <button
                              class=${"guideGridEp" + (active ? " active" : "") + (isFocused ? " focused" : "")}
                              style=${{ left: `${b.x}px`, width: `${b.w}px` }}
                              data-ep-idx=${String(b.j)}
                              data-ep-id=${ep.id}
                              data-source-id=${src.id}
                              data-navitem="1"
                              aria-label=${`${ep.title || "Episode"}${epHasCc ? " (CC)" : ""}`}
                              onPointerEnter=${() => {
                                focusSourceIdx.value = i;
                                focusEpIdx.value = b.j;
                              }}
                              onClick=${async () => {
                                await player.selectSource(src.id, { preserveEpisode: false, skipAutoEpisode: true, autoplay: true });
                                await player.selectEpisode(ep.id, { autoplay: true });
                                isOpen.value = false;
                              }}
                            >
                              <div class="guideGridEpProgress" style=${{ width: `${pct}%` }} aria-hidden="true"></div>
                              <div class="guideGridEpTop">
                                <span class="guideGridEpTitle">${ep.title || "Episode"}</span>
                                ${epHasCc ? html`<span class="guideGridEpBadge guideBadge guideBadge-cc" title="Captions available">CC</span>` : ""}
                              </div>
                              <div class="guideGridEpMeta">
                                <span class="guideGridEpDur">${dur}</span>
                              </div>
                            </button>
                          `;
                        })
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
          </div>
        </div>
        <div class="guidePanel-episodes" id="guideEpisodes">
          <div class="guideNowLabel">
            ${focusedSource ? focusedSource.title || focusedSource.id : "—"} ${focusedTimeRange ? html`<span class="guideNowSep">•</span>` : ""}
            ${focusedTimeRange}
          </div>
          <div class="guideNowEp">${focusedEp ? focusedEp.title || "—" : "—"}</div>
          <div class="guideNowSub">${currentSource ? `Playing: ${currentEpTitle}` : ""}</div>
        </div>
      </div>
      <button
        id="btnCloseGuide"
        class="guidePanel-close"
        title="Close"
        data-navitem="1"
        data-keyhint="G — Close"
        onClick=${() => (isOpen.value = false)}
      >
        ✕
      </button>
    </div>
  `;
}
