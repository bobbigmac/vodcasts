import { html } from "../runtime/vendor.js";

function titleShort(s, n) {
  const t = String(s || "Episode");
  return t.slice(0, n) + (t.length > n ? "…" : "");
}

function clamp(v, a, b) {
  return Math.min(b, Math.max(a, v));
}

export function HistoryPanel({ isOpen, history, player }) {
  const all = history.all.value || [];

  return html`
    <div id="historyPanel" class="historyPanel" aria-hidden=${isOpen.value ? "false" : "true"}>
      <div id="historyPanelContent" class="historyPanelContent">
        <div class="historyHeader">
          <span>History</span>
          <div class="historyActions">
            <button class="historyBtn" title="Combine same video" onClick=${() => history.combine()}>Combine</button>
            <button class="historyBtn" title="Remove short segments" onClick=${() => history.clearShort()}>Clear short</button>
            <button class="historyBtn" title="Clear all" onClick=${() => history.clear()}>Clear</button>
            <button class="historyBtn historyBtnClose" onClick=${() => (isOpen.value = false)}>✕</button>
          </div>
        </div>

	        <div class="historyList">
	          ${all.map((e, idx) => {
	            const isCurrent = idx === 0 && history.current.value;
	            const cls =
	              "historyEntry" +
	              (isCurrent ? " historyEntryCurrent" : "") +
	              (e.hadSleep ? " historyEntryHadSleep" : "");
	            const start = Number(e.start) || 0;
	            const end = Number(e.end) || 0;
	            const dur0 = Number(e.dur);
	            const dur = Number.isFinite(dur0) && dur0 > 0 ? Math.max(dur0, end, start) : Math.max(end, start, 1);
	            const startPct = clamp((start / dur) * 100, 0, 100);
	            const endPct = clamp((end / dur) * 100, 0, 100);
	            const range = `${player.fmtTime(start)} → ${player.fmtTime(end)}`;

	            const onBarClick = (ev) => {
	              ev.stopPropagation();
	              const bar = ev.currentTarget;
	              const r = bar.getBoundingClientRect?.();
	              if (!r || r.width <= 0) return;
	              const x = clamp((ev.clientX - r.left) / r.width, 0, 1);
	              const pct = x * 100;

	              // Three regions:
	              // - before watched segment: restart at 0
	              // - watched segment: resume from segment start
	              // - after watched segment: resume near segment end
	              let startAt = 0;
	              if (pct < startPct) startAt = 0;
	              else if (pct <= endPct) startAt = start;
	              else startAt = Math.max(0, end - 5);

	              player.selectSourceAndEpisode(e.sourceId, e.episodeId, { autoplay: true, startAt });
	              isOpen.value = false;
	            };
	            return html`
	              <div
	                class=${cls}
	                onClick=${(ev) => {
	                  player.selectSourceAndEpisode(e.sourceId, e.episodeId, { autoplay: true, startAt: Math.max(0, end - 5) });
	                  isOpen.value = false;
	                }}
	              >
	                <div class="historyEntryTitle">${titleShort(e.episodeTitle, 50)}</div>
	                <div class="historyEntrySub">${titleShort(e.channelTitle, 30)} · ${range}</div>
	                <div
	                  class="historySegBar"
	                  role="button"
	                  title="Click left: restart · middle: resume from segment start · right: resume near segment end"
	                  style=${{ "--hs-start": `${startPct}%`, "--hs-end": `${endPct}%` }}
	                  onClick=${onBarClick}
	                >
	                  <span class="historySegIcon" aria-hidden="true">↺</span>
	                  <span class="historySegRange mono" aria-hidden="true">${range}</span>
	                </div>
	              </div>
	            `;
	          })}
	        </div>
      </div>
    </div>
  `;
}
