/**
 * Americana / country inspired scene for audio-only display.
 * Sky and ambience vary by time of day (local time).
 */
import { html } from "../../runtime/vendor.js";
import { getTimePalette } from "./time_of_day.js";
import { refreshViz, numberPicker } from "./util.js";

export const AMERICANA_KEY = "vodcasts_americana_v1";

function getOpt(k, def) {
  try {
    const j = JSON.parse(localStorage.getItem(AMERICANA_KEY) || "{}");
    return j[k] ?? def;
  } catch {}
  return def;
}

function setOpt(k, v) {
  try {
    const j = JSON.parse(localStorage.getItem(AMERICANA_KEY) || "{}");
    j[k] = v;
    localStorage.setItem(AMERICANA_KEY, JSON.stringify(j));
  } catch {}
}

export function americana(container, opts = {}) {
  const media = opts.media;
  const canvas = document.createElement("canvas");
  canvas.className = "audioViz-canvas";
  canvas.setAttribute("aria-hidden", "true");
  container.appendChild(canvas);

  let rafId = 0;
  let destroyed = false;
  let phase = 0;
  let windPhase = 0;
  let wheat = [];
  let fireflies = [];

  const resize = () => {
    if (destroyed) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const cw = container.clientWidth || 320;
    const ch = container.clientHeight || 180;
    canvas.width = cw * dpr;
    canvas.height = ch * dpr;
    canvas.style.width = `${cw}px`;
    canvas.style.height = `${ch}px`;
    const w = canvas.width;
    const h = canvas.height;
    const n = Math.max(24, Math.min(80, getOpt("stalkCount", 48) || 48));
    wheat = [];
    for (let i = 0; i < n; i++) {
      wheat.push({
        x: (i / n) * w + (Math.random() - 0.5) * (w / n * 0.8),
        h: h * (0.45 + Math.random() * 0.5),
        sway: Math.random() * Math.PI * 2,
        speed: 0.02 + Math.random() * 0.05,
        windPhase: Math.random() * Math.PI * 2,
      });
    }
    const nFireflies = Math.max(6, Math.min(18, Math.floor((w * h) / 15000)));
    fireflies = [];
    for (let i = 0; i < nFireflies; i++) {
      fireflies.push({
        x: Math.random() * w,
        y: h * (0.2 + Math.random() * 0.7),
        vx: (Math.random() - 0.5) * 0.4,
        vy: (Math.random() - 0.5) * 0.3,
        phase: Math.random() * Math.PI * 2,
        speed: 0.5 + Math.random() * 1,
      });
    }
  };

  const draw = () => {
    if (destroyed) return;
    const playing = media && !media.paused && !media.ended;
    const rate = playing ? (media?.playbackRate ?? 1) : 1;
    phase += (playing ? 0.02 : 0.008) * rate;
    windPhase += (playing ? 0.015 : 0.006) * rate;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const w = canvas.width;
    const h = canvas.height;
    const minDim = Math.min(w, h);
    const scale = minDim / 400;
    const windStr = 0.3 + (getOpt("windStrength", 0.5) || 0.5) * 1.2;
    const baseBend = 12 * windStr * scale;
    const windWave = Math.sin(windPhase) * 0.4 + Math.sin(windPhase * 2.3) * 0.2;

    const palette = getTimePalette();
    const skyGrad = ctx.createLinearGradient(0, 0, 0, h);
    skyGrad.addColorStop(0, palette.bg[0]);
    skyGrad.addColorStop(0.4, palette.bg[1]);
    skyGrad.addColorStop(0.7, palette.bg[2]);
    skyGrad.addColorStop(1, palette.bg[2]);
    ctx.fillStyle = skyGrad;
    ctx.fillRect(0, 0, w, h);

    for (const s of wheat) {
      s.sway += s.speed * (playing ? 1 : 0.4) * rate;
      s.windPhase += 0.02 * rate;
      const bend = (baseBend + baseBend * windWave * 0.5) * (0.8 + 0.4 * Math.sin(s.windPhase));
      const bendX = bend * (0.7 + 0.3 * Math.sin(s.sway));
      ctx.strokeStyle = `rgba(200, 170, 100, ${0.5 + 0.12 * Math.sin(s.sway * 2)})`;
      ctx.lineWidth = Math.max(1.5, 2.5 * scale);
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.moveTo(s.x, h);
      ctx.quadraticCurveTo(s.x + bendX, h - s.h * 0.5, s.x + bendX * 1.2, h - s.h);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(s.x + bendX * 1.2, h - s.h, Math.max(3, 5 * scale), 0, Math.PI * 2);
      ctx.fillStyle = "rgba(220, 190, 120, 0.65)";
      ctx.fill();
    }

    const starAlpha = 0.3 + 0.1 * Math.sin(phase);
    for (let i = 0; i < 6; i++) {
      const sx = w * (0.1 + (i * 0.16) % 0.8);
      const sy = h * (0.08 + (i * 0.12) % 0.28);
      ctx.fillStyle = palette.accent.replace(/[\d.]+\)$/, `${starAlpha})`);
      ctx.beginPath();
      ctx.moveTo(sx, sy - 4);
      ctx.lineTo(sx + 1.2, sy);
      ctx.lineTo(sx, sy + 4);
      ctx.lineTo(sx - 1.2, sy);
      ctx.closePath();
      ctx.fill();
    }

    const moveMult = (playing ? 1 : 0.3) * rate;
    for (const ff of fireflies) {
      ff.phase += 0.08 * rate;
      ff.x += (ff.vx + Math.sin(ff.phase) * 0.15) * moveMult;
      ff.y += (ff.vy + Math.cos(ff.phase * 1.3) * 0.1) * moveMult;
      if (ff.x < 0 || ff.x > w) ff.vx *= -1;
      if (ff.y < h * 0.15 || ff.y > h - 10) ff.vy *= -1;
      const pulse = 0.4 + 0.6 * Math.abs(Math.sin(ff.phase * ff.speed));
      const glow = Math.min(w, h) * 0.04 * pulse;
      const g = ctx.createRadialGradient(ff.x, ff.y, 0, ff.x, ff.y, glow);
      g.addColorStop(0, `rgba(255, 255, 180, ${0.9 * pulse})`);
      g.addColorStop(0.4, `rgba(220, 255, 150, ${0.4 * pulse})`);
      g.addColorStop(1, "rgba(180, 220, 100, 0)");
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(ff.x, ff.y, glow, 0, Math.PI * 2);
      ctx.fill();
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

export function americanaSettings(player) {
  const set = (k, v) => {
    setOpt(k, v);
    refreshViz(player);
  };
  const stalkCount = getOpt("stalkCount") ?? 48;
  const windStrength = getOpt("windStrength") ?? 0.5;
  return html`
    <div class="pluginSettings">
      ${numberPicker("Wheat stalks", stalkCount, 24, 80, 4, (v) => set("stalkCount", v))}
      <label class="pluginSettingsLabel">
        Wind
        <input type="range" min="0" max="100" value=${windStrength * 100} oninput=${(e) => set("windStrength", e.target.value / 100)} />
      </label>
    </div>
  `;
}
