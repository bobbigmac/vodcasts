import { html, useEffect, useMemo, useSignal } from "../runtime/vendor.js";

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

export function GuidePanel({ isOpen, sources, player }) {
  const currentSourceId = player.currentSourceId.value;
  const currentEpisodeId = player.currentEpisodeId.value;
  const episodesBySource = player.sourceEpisodes.value || {};
  const sourcesFlat = useMemo(() => buildSourcesFlat(sources.value || []), [sources.value]);

  const focusSourceIdx = useSignal(Math.max(0, sourcesFlat.findIndex((s) => s.id === currentSourceId)));
  const focusEpIdx = useSignal(0);

  useEffect(() => {
    if (!isOpen.value) return;
    focusSourceIdx.value = Math.max(0, sourcesFlat.findIndex((s) => s.id === currentSourceId));
    focusEpIdx.value = 0;
    if (currentSourceId && !episodesBySource[currentSourceId]) {
      player.loadSourceEpisodes(currentSourceId).catch(() => {});
    }
  }, [isOpen.value, currentSourceId, sourcesFlat.length]);

  useEffect(() => {
    const onKey = (e) => {
      if (!isOpen.value) return;
      if (e.key === "Escape") isOpen.value = false;
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const currentSource = (sources.value || []).find((s) => s.id === currentSourceId) || null;
  const currentEpTitle = player.current.value.episode?.title || "—";

  return html`
    <div id="guidePanel" class="guidePanel" aria-hidden=${isOpen.value ? "false" : "true"}>
      <div class="guidePanel-inner">
        <div class="guidePanel-channels" id="guideFeeds">
          ${sourcesFlat.map((src, i) => {
            const eps = episodesBySource[src.id] || null;
            const feat = src.features || {};
            const ccLikely = !!feat.hasPlayableTranscript || (!!eps && eps.some((ep) => (ep.transcripts || []).length));
            const rowClass =
              "guideChannelRow" +
              (i === focusSourceIdx.value ? " focused" : "") +
              (currentSourceId === src.id ? " playing" : "");

            return html`
              <div
                class=${rowClass}
                data-source-idx=${String(i)}
                data-source-id=${src.id}
                role="button"
                tabIndex=${0}
                data-navitem="1"
                onClick=${(e) => {
                  if (e.target.closest(".guideEpBlock")) return;
                  focusSourceIdx.value = i;
                  focusEpIdx.value = 0;
                  if (!episodesBySource[src.id]) player.loadSourceEpisodes(src.id).catch(() => {});
                }}
                onKeyDown=${(e) => {
                  if (e.key === "Enter") {
                    focusSourceIdx.value = i;
                    focusEpIdx.value = 0;
                    if (!episodesBySource[src.id]) player.loadSourceEpisodes(src.id).catch(() => {});
                  }
                }}
              >
                <div class="guideChannelName">
                  <span class="guideChannelNameText">${src.title || src.id}</span>
                  <span class="guideChannelBadges">
                    ${ccLikely ? html`<span class="guideBadge guideBadge-cc" title="Captions likely available">CC</span>` : ""}
                  </span>
                </div>
                <div class="guideEpStrip">
                  ${eps
                    ? eps
                        .filter((ep) => ep.media?.url)
                        .map((ep, j) => {
                          const active = currentEpisodeId === ep.id;
                          const epHasCc = (ep.transcripts || []).length > 0;
                          const dur = fmtDuration(ep.durationSec) || (ep.dateText || "");
                          const pct =
                            ep.durationSec && ep.durationSec > 0
                              ? Math.min(100, (player.getProgressSec(src.id, ep.id) / ep.durationSec) * 100)
                              : 0;
                          return html`
                            <button
                              class=${"guideEpBlock" + (active ? " active" : "") + (i === focusSourceIdx.value && j === focusEpIdx.value ? " focused" : "")}
                              data-ep-idx=${String(j)}
                              data-ep-id=${ep.id}
                              data-source-id=${src.id}
                              data-navitem="1"
                              aria-label=${`${(ep.title || "Episode").slice(0, 40)}${epHasCc ? " (CC)" : ""}`}
                              onClick=${async () => {
                                await player.selectSource(src.id, { preserveEpisode: false, skipAutoEpisode: true, autoplay: true });
                                await player.selectEpisode(ep.id, { autoplay: true });
                                isOpen.value = false;
                              }}
                            >
                              <div class="guideEpBlockProgress" style=${{ width: `${pct}%` }}></div>
                              ${epHasCc ? html`<span class="guideEpBadge guideBadge guideBadge-cc" title="Captions available">CC</span>` : ""}
                              <span class="guideEpBlockTitle">
                                ${(ep.title || "Episode").slice(0, 24)}${(ep.title || "").length > 24 ? "…" : ""}
                              </span>
                              <span class="guideEpBlockMeta">${dur}</span>
                            </button>
                          `;
                        })
                    : html`
                        <button
                          class="guideEpBlock guideEpLoad"
                          onClick=${async () => {
                            await player.loadSourceEpisodes(src.id);
                          }}
                        >
                          …
                        </button>
                      `}
                </div>
              </div>
            `;
          })}
        </div>
        <div class="guidePanel-episodes" id="guideEpisodes">
          <div class="guideNowLabel">${currentSource ? currentSource.title || currentSource.id : "—"}</div>
          <div class="guideNowEp">
            ${String(currentEpTitle).slice(0, 60)}${String(currentEpTitle).length > 60 ? "…" : ""}
          </div>
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
