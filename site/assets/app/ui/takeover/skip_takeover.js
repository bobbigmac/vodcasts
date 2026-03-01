import { html } from "../../runtime/vendor.js";

function clamp(v, a, b) {
  return Math.min(b, Math.max(a, v));
}

export function SkipTakeover({ player, takeover }) {
  const skip = player.skip?.value || { back: 10, fwd: 30 };

  const setBack = (v) => player.setSkip({ ...skip, back: clamp(v, 5, 120) });
  const setFwd = (v) => player.setSkip({ ...skip, fwd: clamp(v, 5, 180) });
  const reset = () => player.setSkip({ back: 10, fwd: 30 });

  return html`
    <div class="guideBarTakeover" role="dialog" aria-label="Skip buttons" onPointerDownCapture=${() => takeover.bump()} onKeyDownCapture=${() => takeover.bump()}>
      <div class="guideBarTakeoverHeader">
        <div class="guideBarTakeoverTitle">Skip</div>
      </div>
      <div class="guideBarTakeoverBody">
        <div class="takeoverRow" title="Back skip">
          <span class="takeoverRowLabel">Back</span>
          <div class="speedControl" title="Back seconds">
            <button class="speedBtn speedDown" title="Back less" onClick=${() => setBack((skip.back || 10) - 5)}>−</button>
            <button class="speedBtn speedLevel" title="Back seconds">${Math.round(skip.back || 10)}s</button>
            <button class="speedBtn speedUp" title="Back more" onClick=${() => setBack((skip.back || 10) + 5)}>+</button>
          </div>
        </div>

        <div class="takeoverRow" title="Forward skip">
          <span class="takeoverRowLabel">Fwd</span>
          <div class="speedControl" title="Forward seconds">
            <button class="speedBtn speedDown" title="Forward less" onClick=${() => setFwd((skip.fwd || 30) - 5)}>−</button>
            <button class="speedBtn speedLevel" title="Forward seconds">${Math.round(skip.fwd || 30)}s</button>
            <button class="speedBtn speedUp" title="Forward more" onClick=${() => setFwd((skip.fwd || 30) + 5)}>+</button>
          </div>
        </div>

        <button class="guideBtn" title="Reset skip amounts" onClick=${reset}>Reset</button>
      </div>
    </div>
  `;
}

