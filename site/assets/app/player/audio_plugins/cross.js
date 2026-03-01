/**
 * Stained-glass light for audio-only display.
 * Soft colored bands that shift and pulse; colors vary by time of day.
 */
import { html } from "../../runtime/vendor.js";
import { getTimePalette } from "./time_of_day.js";
import { refreshViz, numberPicker } from "./util.js";

export const CROSS_KEY = "vodcasts_cross_v1";

function getOpt(k, def) {
  try {
    const j = JSON.parse(localStorage.getItem(CROSS_KEY) || "{}");
    return j[k] ?? def;
  } catch {}
  return def;
}

function setOpt(k, v) {
  try {
    const j = JSON.parse(localStorage.getItem(CROSS_KEY) || "{}");
    j[k] = v;
    localStorage.setItem(CROSS_KEY, JSON.stringify(j));
  } catch {}
}

export function cross(container, opts = {}) {
  const media = opts.media;
  const canvas = document.createElement("canvas");
  canvas.className = "audioViz-canvas";
  canvas.setAttribute("aria-hidden", "true");
  container.appendChild(canvas);

  let rafId = 0;
  let destroyed = false;
  let phase = 0;

  const resize = () => {
    if (destroyed) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const w = container.clientWidth || 320;
    const h = container.clientHeight || 180;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;
  };

  const draw = () => {
    if (destroyed) return;
    const playing = media && !media.paused && !media.ended;
    const rate = playing ? (media?.playbackRate ?? 1) : 1;
    phase += (playing ? 0.018 : 0.006) * rate;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const w = canvas.width;
    const h = canvas.height;
    const cx = w / 2;
    const cy = h / 2;
    const minDim = Math.min(w, h);
    const bandCount = Math.max(6, Math.min(14, getOpt("bandCount", 10)));
    const intensity = 0.4 + (getOpt("intensity", 0.5) || 0.5) * 0.5;

    const palette = getTimePalette();
    const gradient = ctx.createRadialGradient(cx, cy, 0, cx, cy, minDim * 0.9);
    gradient.addColorStop(0, palette.bg[0]);
    gradient.addColorStop(0.35, palette.bg[1]);
    gradient.addColorStop(1, palette.bg[2]);
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, w, h);

    const pulse = 0.5 + 0.5 * Math.sin(phase * 0.8);
    const bandWidth = (Math.PI * 2) / bandCount;

    for (let i = 0; i < bandCount; i++) {
      const baseAngle = (i / bandCount) * Math.PI * 2 + phase * 0.12;
      const wobble = Math.sin(phase * 1.2 + i * 0.7) * 0.08;
      const startAngle = baseAngle - bandWidth * 0.5 + wobble;
      const endAngle = baseAngle + bandWidth * 0.5 + wobble;

      const hueShift = (i / bandCount) * 0.08 + Math.sin(phase * 0.5 + i) * 0.02;
      const alpha = (0.12 + 0.1 * pulse + 0.04 * Math.sin(phase + i * 0.5)) * intensity;

      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.arc(cx, cy, minDim * 0.7, startAngle, endAngle);
      ctx.closePath();

      const midAngle = (startAngle + endAngle) / 2;
      const bandGrad = ctx.createRadialGradient(cx, cy, 0, cx + Math.cos(midAngle) * minDim * 0.5, cy + Math.sin(midAngle) * minDim * 0.5, minDim);
      const r = Math.min(1, 0.6 + hueShift);
      const gVal = Math.min(1, 0.7 + hueShift * 0.5);
      const bVal = Math.min(1, 0.95 + hueShift);
      bandGrad.addColorStop(0, `rgba(${Math.round(r * 255)}, ${Math.round(gVal * 255)}, ${Math.round(bVal * 255)}, ${alpha * 1.5})`);
      bandGrad.addColorStop(0.4, `rgba(200, 220, 255, ${alpha})`);
      bandGrad.addColorStop(1, "rgba(180, 200, 240, 0)");
      ctx.fillStyle = bandGrad;
      ctx.fill();
    }

    const centerGlow = ctx.createRadialGradient(cx, cy, 0, cx, cy, minDim * 0.25);
    centerGlow.addColorStop(0, palette.accent.replace(/[\d.]+\)$/, `${0.15 * pulse * intensity})`));
    centerGlow.addColorStop(0.5, palette.muted.replace(/[\d.]+\)$/, `${0.06 * intensity})`));
    centerGlow.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = centerGlow;
    ctx.beginPath();
    ctx.arc(cx, cy, minDim * 0.25, 0, Math.PI * 2);
    ctx.fill();

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

export function crossSettings(player) {
  const set = (k, v) => {
    setOpt(k, v);
    refreshViz(player);
  };
  const bandCount = getOpt("bandCount") ?? 10;
  const intensity = getOpt("intensity") ?? 0.5;
  return html`
    <div class="pluginSettings">
      ${numberPicker("Bands", bandCount, 6, 14, 1, (v) => set("bandCount", v))}
      <label class="pluginSettingsLabel">
        Intensity
        <input type="range" min="0" max="100" value=${intensity * 100} oninput=${(e) => set("intensity", e.target.value / 100)} />
      </label>
    </div>
  `;
}
