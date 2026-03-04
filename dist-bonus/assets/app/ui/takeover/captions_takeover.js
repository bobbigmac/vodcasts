import { html, useEffect, useMemo } from "../../runtime/vendor.js";

const DEFAULT_CAPTIONS = { x: 50, y: 78, w: 92, opacity: 1, scale: 1 };

function clamp(v, a, b) {
  return Math.min(b, Math.max(a, v));
}

function getBox(player) {
  const b = player.subtitleBox?.value || null;
  if (!b) return { ...DEFAULT_CAPTIONS };
  return {
    x: Number.isFinite(Number(b.x)) ? Number(b.x) : DEFAULT_CAPTIONS.x,
    y: Number.isFinite(Number(b.y)) ? Number(b.y) : DEFAULT_CAPTIONS.y,
    w: Number.isFinite(Number(b.w)) ? Number(b.w) : DEFAULT_CAPTIONS.w,
    opacity: Number.isFinite(Number(b.opacity)) ? Number(b.opacity) : DEFAULT_CAPTIONS.opacity,
    scale: Number.isFinite(Number(b.scale)) ? Number(b.scale) : DEFAULT_CAPTIONS.scale,
  };
}

export function CaptionsTakeover({ player, takeover }) {
  const box = useMemo(() => getBox(player), [player.subtitleBox.value]);
  const posLabel = `${Math.round(box.x)}%, ${Math.round(box.y)}%`;
  const sizeLabel = `${Math.round((box.scale || 1) * 100)}%`;

  const apply = (next) => {
    takeover.bump();
    player.setSubtitleBox(next);
  };

  const moveBy = (dx, dy) => {
    const cur = getBox(player);
    apply({ ...cur, x: clamp(cur.x + dx, 0, 100), y: clamp(cur.y + dy, 0, 100) });
  };

  const scaleBy = (d) => {
    const cur = getBox(player);
    const nextScale = clamp((Number(cur.scale) || 1) + d, 0.6, 2.4);
    apply({ ...cur, scale: Math.round(nextScale * 100) / 100 });
  };

  const reset = () => apply({ ...DEFAULT_CAPTIONS });

  useEffect(() => {
    const onKey = (e) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const step = e.shiftKey ? 6 : 2;
      let handled = false;
      if (e.key === "ArrowUp") {
        moveBy(0, -step);
        handled = true;
      } else if (e.key === "ArrowDown") {
        moveBy(0, step);
        handled = true;
      } else if (e.key === "ArrowLeft") {
        moveBy(-step, 0);
        handled = true;
      } else if (e.key === "ArrowRight") {
        moveBy(step, 0);
        handled = true;
      } else if (e.key === "+" || e.key === "=" || e.key === "PageUp" || e.key === "]") {
        scaleBy(0.1);
        handled = true;
      } else if (e.key === "-" || e.key === "_" || e.key === "PageDown" || e.key === "[") {
        scaleBy(-0.1);
        handled = true;
      } else if (e.key === "0") {
        reset();
        handled = true;
      } else if (e.key === "c" || e.key === "C") {
        apply({ ...getBox(player), x: 50, y: 78 });
        handled = true;
      }
      if (!handled) return;
      takeover.bump();
      e.preventDefault();
      e.stopPropagation();
    };
    window.addEventListener("keydown", onKey, { capture: true });
    return () => window.removeEventListener("keydown", onKey, { capture: true });
  }, []);

  return html`
    <div
      class="guideBarTakeover"
      role="dialog"
      aria-label="Captions settings"
      data-navmode="arrows"
      onPointerDownCapture=${() => takeover.bump()}
      onKeyDownCapture=${() => takeover.bump()}
    >
      <div class="guideBarTakeoverHeader">
        <div class="guideBarTakeoverTitle">Captions</div>
        <button class="guideBtn" title="Done" onClick=${() => takeover.close()}>Done</button>
      </div>

      <div class="guideBarTakeoverBody">
        <div class="padControl" aria-label="Caption position">
          <button class="padBtn padUp" title="Up" onClick=${() => moveBy(0, -2)}>↑</button>
          <span class="padSpacer" aria-hidden="true"></span>
          <button class="padBtn padLeft" title="Left" onClick=${() => moveBy(-2, 0)}>←</button>
          <div class="padVal" title="X, Y">${posLabel}</div>
          <button class="padBtn padRight" title="Right" onClick=${() => moveBy(2, 0)}>→</button>
          <span class="padSpacer" aria-hidden="true"></span>
          <button class="padBtn padDown" title="Down" onClick=${() => moveBy(0, 2)}>↓</button>
        </div>

        <div class="scaleControl" aria-label="Caption size">
          <button class="scaleBtn" title="Bigger" onClick=${() => scaleBy(0.1)}>↑</button>
          <div class="scaleVal" title="Size">${sizeLabel}</div>
          <button class="scaleBtn" title="Smaller" onClick=${() => scaleBy(-0.1)}>↓</button>
        </div>

        <button class="guideBtn" title="Center" onClick=${() => apply({ ...getBox(player), x: 50, y: 78 })}>Center</button>
        <button class="guideBtn" title="Reset captions position and size" onClick=${reset}>Reset</button>
      </div>
    </div>
  `;
}
