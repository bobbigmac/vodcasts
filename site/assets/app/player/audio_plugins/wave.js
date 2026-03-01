import { html } from "../../runtime/vendor.js";
import { refreshViz, numberPicker } from "./util.js";

export const WAVE_KEY = "vodcasts_wave_v1";

function getOpt(k, def) {
  try {
    const j = JSON.parse(localStorage.getItem(WAVE_KEY) || "{}");
    return j[k] ?? def;
  } catch {}
  return def;
}

function setOpt(k, v) {
  try {
    const j = JSON.parse(localStorage.getItem(WAVE_KEY) || "{}");
    j[k] = v;
    localStorage.setItem(WAVE_KEY, JSON.stringify(j));
  } catch {}
}

/**
 * Default wave animation for audio-only display.
 */
export function wave(container, opts = {}) {
  const media = opts.media;

  const canvas = document.createElement("canvas");
  canvas.className = "audioViz-canvas";
  canvas.setAttribute("aria-hidden", "true");
  container.appendChild(canvas);

  let phase = 0;
  let rafId = 0;
  let destroyed = false;

  const resize = () => {
    if (destroyed) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const w = container.clientWidth || 320;
    const h = container.clientHeight || 180;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = w + "px";
    canvas.style.height = h + "px";
  };

  const draw = () => {
    if (destroyed) return;
    const playing = media && !media.paused && !media.ended;
    const rate = playing ? (media?.playbackRate ?? 1) : 1;
    const t = media ? (media.currentTime || 0) : 0;
    const speedMult = 0.5 + (getOpt("speed", 0.5) || 0.5);
    phase += (playing ? 0.035 : 0.008) * speedMult * rate;
    const level = playing ? 0.22 + 0.08 * Math.sin(t * 0.8) + 0.04 * Math.sin(t * 2.1) : 0.06;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    const waveCount = Math.max(1, Math.min(6, getOpt("waveCount", 3) || 3));
    const color = "rgba(138, 180, 248, 0.35)";
    const amp = level * Math.min(h * 0.35, w * 0.15);
    const drift = Math.sin(t * 0.3) * 0.15;

    for (let k = 0; k < waveCount; k++) {
      const offset = (k / waveCount) * Math.PI * 2 + drift;
      const layerAmp = amp * (1 - k * 0.2);
      const opacity = 0.4 - k * 0.1;
      ctx.beginPath();
      ctx.strokeStyle = color.replace("0.35", String(opacity));
      ctx.lineWidth = 2;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      const pts = 64;
      for (let i = 0; i <= pts; i++) {
        const x = (i / pts) * w;
        const ti = (i / pts) * Math.PI * 4 + phase + offset + Math.sin(t * 0.5 + i * 0.1) * 0.2;
        const y = h / 2 + Math.sin(ti) * layerAmp;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }
    rafId = requestAnimationFrame(draw);
  };

  const start = () => {
    if (destroyed) return;
    resize();
    cancelAnimationFrame(rafId);
    draw();
  };

  const ro = new ResizeObserver(resize);
  ro.observe(container);
  resize();

  const destroy = () => {
    destroyed = true;
    cancelAnimationFrame(rafId);
    ro.disconnect();
    try {
      canvas.remove();
    } catch {}
  };

  return { start, destroy };
}

export function waveSettings(player) {
  const set = (k, v) => {
    setOpt(k, v);
    refreshViz(player);
  };
  const speed = getOpt("speed") ?? 0.5;
  const waveCount = getOpt("waveCount") ?? 3;
  return html`
    <div class="pluginSettings">
      <label class="pluginSettingsLabel">
        Speed
        <input type="range" min="0" max="100" value=${speed * 100} oninput=${(e) => set("speed", e.target.value / 100)} />
      </label>
      ${numberPicker("Waves", waveCount, 1, 6, 1, (v) => set("waveCount", v))}
    </div>
  `;
}
