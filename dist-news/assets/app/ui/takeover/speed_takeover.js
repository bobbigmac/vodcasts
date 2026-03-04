import { html } from "../../runtime/vendor.js";

const COMMON = [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2, 2.5, 3, 4, 5];

function fmtRate(r) {
  return (Math.round(r * 100) / 100).toString().replace(/\.0+$/, "").replace(/(\.\d)0$/, "$1") + "x";
}

export function SpeedTakeover({ player, takeover }) {
  const steps = (player.rateSteps?.value || []).slice();
  const stepSet = new Set(steps.map(Number));

  const toggle = (r) => {
    const cur = new Set((player.rateSteps.value || []).map(Number));
    if (r === 1) return;
    if (cur.has(r)) cur.delete(r);
    else cur.add(r);
    cur.add(1);
    player.setRateSteps([...cur]);
    takeover.bump();
  };

  const reset = () => {
    player.resetRateSteps?.();
    takeover.bump();
  };

  return html`
    <div class="guideBarTakeover" role="dialog" aria-label="Speed steps" onPointerDownCapture=${() => takeover.bump()} onKeyDownCapture=${() => takeover.bump()}>
      <div class="guideBarTakeoverHeader">
        <div class="guideBarTakeoverTitle">Speed Steps</div>
        <button class="guideBtn" title="Done" onClick=${() => takeover.close()}>Done</button>
      </div>

      <div class="guideBarTakeoverBody">
        <div class="takeoverGrid" aria-label="Speed options">
          ${COMMON.map((r) => {
            const on = stepSet.has(r);
            return html`
              <button
                class=${"guideBtn" + (on ? " active" : "")}
                title=${on ? "Disable" : "Enable"}
                disabled=${r === 1}
                aria-disabled=${r === 1 ? "true" : "false"}
                onClick=${() => toggle(r)}
              >
                ${fmtRate(r)}
              </button>
            `;
          })}
        </div>
        <button class="guideBtn" title="Reset speed steps" onClick=${reset}>Reset</button>
        <div class="takeoverHint">1x is always available</div>
      </div>
    </div>
  `;
}
