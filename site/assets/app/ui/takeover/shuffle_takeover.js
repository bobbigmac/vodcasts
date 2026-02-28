import { html } from "../../runtime/vendor.js";

function clamp(v, a, b) {
  return Math.min(b, Math.max(a, v));
}

function loadFaveCount() {
  try {
    const raw = JSON.parse(localStorage.getItem("vodcasts_guide_prefs_v1") || "{}");
    const list = Array.isArray(raw?.faves) ? raw.faves : [];
    return list.filter((x) => typeof x === "string" && x).length;
  } catch {
    return 0;
  }
}

export function ShuffleTakeover({ player, takeover }) {
  const cfg = player.shuffle?.value || { active: false, intervalIdx: 4, changeFeed: true, changeEpisode: true, changeTime: true };
  const intervals = player.shuffleIntervals || [];
  const idx = clamp(Math.round(Number(cfg.intervalIdx) || 0), 0, Math.max(0, intervals.length - 1));
  const cur = intervals[idx] || { label: "5m", ms: 5 * 60 * 1000 };
  const curCat = player.current?.value?.source?.category ? String(player.current.value.source.category) : "";
  const baseCat = cfg.baseCategory ? String(cfg.baseCategory) : "";
  const catEnabled = !!cfg.sameCategory;
  const faveCount = loadFaveCount();
  const faveEnabled = !!cfg.favesOnly;

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

  const toggleCategory = () => {
    const next = !cfg.sameCategory;
    if (next) {
      const cat = baseCat || curCat;
      if (!cat) return;
      player.setShuffleSettings?.({ sameCategory: true, baseCategory: cat }, { resetNextAt: true });
      return;
    }
    player.setShuffleSettings?.({ sameCategory: false }, { resetNextAt: true });
  };

  const toggleFaves = () => {
    if (faveCount <= 0 && !faveEnabled) return;
    player.setShuffleSettings?.({ favesOnly: !faveEnabled }, { resetNextAt: true });
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

        <div class="takeoverRow" title="Restrict feed selection">
          <span class="takeoverRowLabel">Restrict</span>
          <div class="takeoverOpts">
            <button
              class=${"guideBtn" + (faveEnabled ? " active" : "")}
              disabled=${faveCount <= 0 && !faveEnabled}
              aria-disabled=${faveCount <= 0 && !faveEnabled ? "true" : "false"}
              title=${faveCount > 0 ? "Only favorite channels" : faveEnabled ? "No favorite channels left (turn off to clear)" : "No favorite channels yet"}
              onClick=${toggleFaves}
            >
              Faves
            </button>
            <button
              class=${"guideBtn" + (catEnabled ? " active" : "")}
              disabled=${!baseCat && !curCat}
              aria-disabled=${!baseCat && !curCat ? "true" : "false"}
              title=${baseCat || curCat ? `Only channels in category: ${baseCat || curCat}` : "No category for current channel"}
              onClick=${toggleCategory}
            >
              Category
            </button>
            ${catEnabled && (baseCat || curCat)
              ? html`<span class="takeoverHint" style=${{ marginLeft: "4px" }}>${baseCat || curCat}</span>`
              : ""}
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
