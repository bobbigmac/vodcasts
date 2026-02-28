import { html } from "../../runtime/vendor.js";

function loadFaveCount() {
  try {
    const raw = JSON.parse(localStorage.getItem("vodcasts_guide_prefs_v1") || "{}");
    const list = Array.isArray(raw?.faves) ? raw.faves : [];
    return list.filter((x) => typeof x === "string" && x).length;
  } catch {
    return 0;
  }
}

export function RandomTakeover({ player, takeover }) {
  const curSourceId = player.current.value.source?.id || null;
  const curTitle = player.current.value.source?.title || curSourceId || "—";
  const cfg = player.randomPrefs?.value || { favesOnly: false };
  const faveCount = loadFaveCount();
  const toggleFaves = () => {
    if (faveCount <= 0 && !cfg.favesOnly) return;
    player.setRandomSettings?.({ favesOnly: !cfg.favesOnly });
  };

  return html`
    <div class="guideBarTakeover" role="dialog" aria-label="Random options" onPointerDownCapture=${() => takeover.bump()} onKeyDownCapture=${() => takeover.bump()}>
      <div class="guideBarTakeoverHeader">
        <div class="guideBarTakeoverTitle">Random</div>
        <button class="guideBtn" title="Done" onClick=${() => takeover.close()}>Done</button>
      </div>
      <div class="guideBarTakeoverBody">
        <div class="takeoverRow" title="Restrict random selection">
          <span class="takeoverRowLabel">Restrict</span>
          <div class="takeoverOpts">
            <button
              class=${"guideBtn" + (cfg.favesOnly ? " active" : "")}
              disabled=${faveCount <= 0 && !cfg.favesOnly}
              aria-disabled=${faveCount <= 0 && !cfg.favesOnly ? "true" : "false"}
              title=${faveCount > 0 ? "Only favorite channels" : cfg.favesOnly ? "No favorite channels left (turn off to clear)" : "No favorite channels yet"}
              onClick=${toggleFaves}
            >
              Faves
            </button>
          </div>
        </div>
        <button
          class="guideBtn"
          title="Random episode from any channel"
          onClick=${async () => {
            await player.playRandom();
            takeover.close();
          }}
        >
          Any channel
        </button>
        <button
          class="guideBtn"
          disabled=${!curSourceId}
          aria-disabled=${curSourceId ? "false" : "true"}
          title=${curSourceId ? `Random episode from ${curTitle}` : "Pick a channel first"}
          onClick=${async () => {
            if (!curSourceId) return;
            await player.selectSource(curSourceId, { preserveEpisode: false, pickRandomEpisode: true, autoplay: true });
            takeover.close();
          }}
        >
          This channel
        </button>
      </div>
    </div>
  `;
}
