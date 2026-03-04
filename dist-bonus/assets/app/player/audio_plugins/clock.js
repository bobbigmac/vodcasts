import { html } from "../../runtime/vendor.js";
import { getTimePalette } from "./time_of_day.js";
import { refreshViz } from "./util.js";

export const CLOCK_KEY = "vodcasts_clock_v1";

function getOpt(k) {
  try {
    return JSON.parse(localStorage.getItem(CLOCK_KEY) || "{}")[k];
  } catch {}
  return null;
}

function setOpt(k, v) {
  try {
    const j = JSON.parse(localStorage.getItem(CLOCK_KEY) || "{}");
    j[k] = v;
    localStorage.setItem(CLOCK_KEY, JSON.stringify(j));
  } catch {}
}

/**
 * Analog clock for audio-only display.
 * @param {HTMLElement} container
 * @param {{ media?: HTMLMediaElement }} opts
 */
export function clock(container, opts = {}) {
  const media = opts.media;
  const canvas = document.createElement("canvas");
  canvas.className = "audioViz-canvas";
  canvas.setAttribute("aria-hidden", "true");
  container.appendChild(canvas);

  let rafId = 0;
  let destroyed = false;

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
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const w = canvas.width;
    const h = canvas.height;
    const cx = w / 2;
    const cy = h / 2;
    const r = Math.min(w, h) * 0.38;

    const palette = getTimePalette();
    const gradient = ctx.createRadialGradient(cx, cy, 0, cx, cy, r * 2);
    gradient.addColorStop(0, palette.bg[0]);
    gradient.addColorStop(0.5, palette.bg[1]);
    gradient.addColorStop(1, palette.bg[2]);
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, w, h);

    const now = new Date();
    const sec = now.getSeconds() + now.getMilliseconds() / 1000;
    const min = now.getMinutes() + sec / 60;
    const hr = (now.getHours() % 12) + min / 60;

    ctx.strokeStyle = palette.accent.replace(/[\d.]+\)$/, "0.25)");
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.stroke();

    ctx.strokeStyle = palette.muted.replace(/[\d.]+\)$/, "0.15)");
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(cx, cy, r - 4, 0, Math.PI * 2);
    ctx.stroke();

    for (let i = 0; i < 12; i++) {
      const a = (i / 12) * Math.PI * 2 - Math.PI / 2;
      const isMajor = i % 3 === 0;
      const inner = r - (isMajor ? 14 : 10);
      const x1 = cx + Math.cos(a) * inner;
      const y1 = cy + Math.sin(a) * inner;
      const x2 = cx + Math.cos(a) * r;
      const y2 = cy + Math.sin(a) * r;
      ctx.strokeStyle = isMajor ? palette.accent.replace(/[\d.]+\)$/, "0.5)") : palette.muted.replace(/[\d.]+\)$/, "0.4)");
      ctx.lineWidth = isMajor ? 2.5 : 1.5;
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();
    }

    const setAlpha = (c, a) => c.replace(/[\d.]+(?=\)$)/, String(a));
    const drawHand = (angle, div, len, lw, alpha, color) => {
      const a = (angle / div) * Math.PI * 2 - Math.PI / 2;
      ctx.strokeStyle = color || setAlpha(palette.accent, alpha);
      ctx.lineWidth = lw;
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(cx + Math.cos(a) * len * r, cy + Math.sin(a) * len * r);
      ctx.stroke();
    };

    const showSeconds = getOpt("showSeconds") !== false;
    const show24h = getOpt("show24h") === true;
    const hrVal = show24h ? now.getHours() + min / 60 : hr;
    const hrDiv = show24h ? 24 : 12;

    drawHand(hrVal, hrDiv, 0.42, 5, 0.8);
    drawHand(min, 60, 0.62, 3.5, 0.9);
    if (showSeconds) drawHand(sec, 60, 0.72, 1.5, 1, "rgba(230, 120, 100, 0.9)");

    ctx.beginPath();
    ctx.arc(cx, cy, 4, 0, Math.PI * 2);
    ctx.fillStyle = palette.accent.replace(/[\d.]+\)$/, "0.9)");
    ctx.fill();
    ctx.strokeStyle = palette.muted.replace(/[\d.]+\)$/, "0.5)");
    ctx.lineWidth = 1;
    ctx.stroke();

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

export function clockSettings(player) {
  const set = (k, v) => {
    setOpt(k, v);
    refreshViz(player);
  };
  const showSeconds = getOpt("showSeconds") !== false;
  const show24h = getOpt("show24h") === true;
  return html`
    <div class="pluginSettings pluginSettingsClock">
      <label class="pluginSettingsLabel">
        <input type="checkbox" checked=${showSeconds} onchange=${(e) => set("showSeconds", e.target.checked)} />
        Show seconds
      </label>
      <label class="pluginSettingsLabel">
        <input type="checkbox" checked=${show24h} onchange=${(e) => set("show24h", e.target.checked)} />
        24-hour
      </label>
    </div>
  `;
}
