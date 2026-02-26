import { html } from "../../runtime/vendor.js";

function clamp(v, a, b) {
  return Math.min(b, Math.max(a, v));
}

export function ShuffleTakeover({ player, takeover }) {
  const cfg = player.shuffle?.value || { active: false, intervalIdx: 4, changeFeed: true, changeEpisode: true, changeTime: true };
  const intervals = player.shuffleIntervals || [];
  const idx = clamp(Math.round(Number(cfg.intervalIdx) || 0), 0, Math.max(0, intervals.length - 1));
  const cur = intervals[idx] || { label: "5m", ms: 5 * 60 * 1000 };

  const setIdx = (nextIdx) => {
    const n = clamp(nextIdx, 0, Math.max(0, intervals.length - 1));
    player.setShuffleSettings?.({ intervalIdx: n }, { resetNextAt: true });
  };

  const toggle = (k) => {
    const next = { ...cfg, [k]: !cfg[k] };
    const any = !!next.changeFeed || !!next.changeEpisode || !!next.changeTime;
    if (!any) return;
    player.setShuffleSettings?.({ [k]: !cfg[k] }, { resetNextAt: true });
  };

  return html`
    <div class="guideBarTakeover" role="dialog" aria-label="Shuffle" onPointerDownCapture=${() => takeover.bump()} onKeyDownCapture=${() => takeover.bump()}>
      <div class="guideBarTakeoverHeader">
        <div class="guideBarTakeoverTitle">Shuffle</div>
        <button class="guideBtn" title="Done" onClick=${() => takeover.close()}>Done</button>
      </div>
      <div class="guideBarTakeoverBody">
        <div class="takeoverRow" title="Shuffle interval">
          <span class="takeoverRowLabel">Every</span>
          <div class="speedControl" title="Shuffle interval">
            <button class="speedBtn speedDown" title="Less often" onClick=${() => setIdx(idx - 1)}>−</button>
            <button class="speedBtn speedLevel" title="Shuffle interval">${cur.label}</button>
            <button class="speedBtn speedUp" title="More often" onClick=${() => setIdx(idx + 1)}>+</button>
          </div>
        </div>

        <div class="takeoverRow" title="Shuffle changes">
          <span class="takeoverRowLabel">Change</span>
          <div class="takeoverOpts">
            <button class=${"guideBtn" + (cfg.changeFeed ? " active" : "")} title="Change channel/feed" onClick=${() => toggle("changeFeed")}>
              Feed
            </button>
            <button
              class=${"guideBtn" + (cfg.changeEpisode ? " active" : "")}
              title="Change episode"
              onClick=${() => toggle("changeEpisode")}
            >
              Entry
            </button>
            <button class=${"guideBtn" + (cfg.changeTime ? " active" : "")} title="Change timestamp" onClick=${() => toggle("changeTime")}>
              Time
            </button>
          </div>
        </div>

        <button
          class=${"guideBtn" + (cfg.active ? " active" : "")}
          title=${cfg.active ? "Turn shuffle off" : "Turn shuffle on"}
          onClick=${() => {
            player.toggleShuffle?.();
          }}
        >
          ${cfg.active ? "On" : "Off"}
        </button>
      </div>
    </div>
  `;
}

