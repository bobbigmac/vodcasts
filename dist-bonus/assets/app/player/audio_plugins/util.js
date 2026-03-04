import { html } from "../../runtime/vendor.js";

/**
 * Shared util for audio plugins.
 */
export function refreshViz(player) {
  player.attachAudioViz?.(null);
  const vis = document.querySelector(".audioViz-vis");
  if (vis) player.attachAudioViz?.(vis);
}

/** Number picker matching speed/volume design: [−] value [+] */
export function numberPicker(label, value, min, max, step, set, fmt = (v) => String(v)) {
  const v = Math.max(min, Math.min(max, Number(value)));
  return html`
    <div class="takeoverRow" title=${label}>
      <span class="takeoverRowLabel">${label}</span>
      <div class="speedControl">
        <button class="speedBtn speedDown" title="Decrease" onClick=${() => set(Math.max(min, v - step))} disabled=${v <= min}>−</button>
        <span class="speedBtn speedLevel" title=${label}>${fmt(v)}</span>
        <button class="speedBtn speedUp" title="Increase" onClick=${() => set(Math.min(max, v + step))} disabled=${v >= max}>+</button>
      </div>
    </div>
  `;
}
