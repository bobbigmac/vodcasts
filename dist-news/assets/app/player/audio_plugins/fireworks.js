import { html } from "../../runtime/vendor.js";
import { refreshViz } from "./util.js";

export const FIREWORKS_KEY = "vodcasts_fireworks_v1";

function getOpt(k, def) {
  try {
    const j = JSON.parse(localStorage.getItem(FIREWORKS_KEY) || "{}");
    return j[k] ?? def;
  } catch {}
  return def;
}

function setOpt(k, v) {
  try {
    const j = JSON.parse(localStorage.getItem(FIREWORKS_KEY) || "{}");
    j[k] = v;
    localStorage.setItem(FIREWORKS_KEY, JSON.stringify(j));
  } catch {}
}

const COLORS = [
  "#ff4444", "#ff8844", "#ffcc44", "#44ff44", "#44ffcc",
  "#4488ff", "#8844ff", "#ff44ff", "#ffffff", "#ffaa88",
];

function randColor() {
  return COLORS[Math.floor(Math.random() * COLORS.length)];
}

/**
 * Fireworks animation for audio-only display.
 */
export function fireworks(container, opts = {}) {
  const media = opts.media;
  const canvas = document.createElement("canvas");
  canvas.className = "audioViz-canvas";
  canvas.setAttribute("aria-hidden", "true");
  container.appendChild(canvas);

  let rockets = [];
  let particles = [];
  let rafId = 0;
  let destroyed = false;
  let lastLaunch = 0;

  const resize = () => {
    if (destroyed) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const cw = container.clientWidth || 320;
    const ch = container.clientHeight || 180;
    canvas.width = cw * dpr;
    canvas.height = ch * dpr;
    canvas.style.width = `${cw}px`;
    canvas.style.height = `${ch}px`;
    rockets = [];
    particles = [];
  };

  const launchRocket = (w, h) => {
    const x = w * (0.15 + Math.random() * 0.7);
    rockets.push({
      x,
      y: h,
      vx: (Math.random() - 0.5) * 0.3,
      vy: -4 - Math.random() * 3,
      color: randColor(),
      trail: [],
    });
  };

  const explode = (rocket, w, h) => {
    const n = 40 + Math.floor(Math.random() * 30);
    const color = rocket.color;
    for (let i = 0; i < n; i++) {
      const a = (Math.PI * 2 * i) / n + Math.random() * 0.5;
      const v = 2 + Math.random() * 4;
      particles.push({
        x: rocket.x,
        y: rocket.y,
        vx: Math.cos(a) * v,
        vy: Math.sin(a) * v,
        color,
        life: 1,
        decay: 0.015 + Math.random() * 0.02,
        r: 1.5 + Math.random() * 1.5,
      });
    }
  };

  const draw = () => {
    if (destroyed) return;
    const playing = media && !media.paused && !media.ended;
    const rate = playing ? (media?.playbackRate ?? 1) : 1;
    const speedMult = 0.6 + (getOpt("speed", 0.5) || 0.5);
    const freqMult = playing ? 1 : 0.3;
    const launchRate = (0.8 + (getOpt("frequency", 0.5) || 0.5) * 1.2) * freqMult * rate;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const w = canvas.width;
    const h = canvas.height;

    ctx.fillStyle = "rgba(8, 12, 24, 0.35)";
    ctx.fillRect(0, 0, w, h);

    const now = performance.now() / 1000;
    if (now - lastLaunch > 2 / launchRate) {
      launchRocket(w, h);
      lastLaunch = now;
    }

    const g = 0.12 * speedMult * rate;
    const drag = 0.98;

    for (let i = rockets.length - 1; i >= 0; i--) {
      const r = rockets[i];
      r.vy += g * 0.1;
      r.x += r.vx * speedMult;
      r.y += r.vy * speedMult;
      r.trail.push({ x: r.x, y: r.y });
      if (r.trail.length > 12) r.trail.shift();

      ctx.strokeStyle = r.color;
      ctx.lineWidth = 2;
      ctx.beginPath();
      for (let t = 0; t < r.trail.length; t++) {
        const p = r.trail[t];
        if (t === 0) ctx.moveTo(p.x, p.y);
        else ctx.lineTo(p.x, p.y);
      }
      ctx.stroke();

      ctx.fillStyle = r.color;
      ctx.beginPath();
      ctx.arc(r.x, r.y, 2, 0, Math.PI * 2);
      ctx.fill();

      if (r.vy >= 0) {
        explode(r, w, h);
        rockets.splice(i, 1);
      }
    }

    for (let i = particles.length - 1; i >= 0; i--) {
      const p = particles[i];
      p.vy += g;
      p.x += p.vx * speedMult;
      p.y += p.vy * speedMult;
      p.vx *= drag;
      p.vy *= drag;
      p.life -= p.decay;

      if (p.life <= 0) {
        particles.splice(i, 1);
        continue;
      }

      const alpha = p.life;
      const hex = p.color.slice(1);
      const rr = parseInt(hex.slice(0, 2), 16);
      const gg = parseInt(hex.slice(2, 4), 16);
      const bb = parseInt(hex.slice(4, 6), 16);
      ctx.fillStyle = `rgba(${rr},${gg},${bb},${alpha})`;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r * p.life, 0, Math.PI * 2);
      ctx.fill();
    }

    rafId = requestAnimationFrame(draw);
  };

  const start = () => {
    if (destroyed) return;
    resize();
    cancelAnimationFrame(rafId);
    lastLaunch = 0;
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

export function fireworksSettings(player) {
  const set = (k, v) => {
    setOpt(k, v);
    refreshViz(player);
  };
  const speed = getOpt("speed") ?? 0.5;
  const frequency = getOpt("frequency") ?? 0.5;
  return html`
    <div class="pluginSettings">
      <label class="pluginSettingsLabel">
        Speed
        <input type="range" min="0" max="100" value=${speed * 100} oninput=${(e) => set("speed", e.target.value / 100)} />
      </label>
      <label class="pluginSettingsLabel">
        Frequency
        <input type="range" min="0" max="100" value=${frequency * 100} oninput=${(e) => set("frequency", e.target.value / 100)} />
      </label>
    </div>
  `;
}
