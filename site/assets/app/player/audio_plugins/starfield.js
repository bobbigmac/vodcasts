import { html } from "../../runtime/vendor.js";
import { refreshViz } from "./util.js";

export const STARFIELD_KEY = "vodcasts_starfield_v1";

function getOpt(k, def) {
  try {
    const j = JSON.parse(localStorage.getItem(STARFIELD_KEY) || "{}");
    return j[k] ?? def;
  } catch {}
  return def;
}

function setOpt(k, v) {
  try {
    const j = JSON.parse(localStorage.getItem(STARFIELD_KEY) || "{}");
    j[k] = v;
    localStorage.setItem(STARFIELD_KEY, JSON.stringify(j));
  } catch {}
}

/**
 * Starfield animation for audio-only display.
 */
export function starfield(container, opts = {}) {
  const media = opts.media;
  const canvas = document.createElement("canvas");
  canvas.className = "audioViz-canvas";
  canvas.setAttribute("aria-hidden", "true");
  container.appendChild(canvas);

  let stars = [];
  let rafId = 0;
  let destroyed = false;

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
    const density = 0.3 + (getOpt("density", 0.5) || 0.5) * 0.7;
    const n = Math.min(120, Math.floor((w * h) / 4000 * density));
    stars = [];
    for (let i = 0; i < n; i++) {
      stars.push({
        x: Math.random() * w,
        y: Math.random() * h,
        z: Math.random(),
        r: 0.5 + Math.random() * 1.5,
      });
    }
  };

  const draw = () => {
    if (destroyed) return;
    const playing = media && !media.paused && !media.ended;
    const rate = playing ? (media?.playbackRate ?? 1) : 1;
    const speedMult = 0.5 + (getOpt("speed", 0.5) || 0.5);
    const speed = (playing ? 0.008 : 0.002) * speedMult * rate;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const w = canvas.width;
    const h = canvas.height;
    ctx.fillStyle = "rgba(11, 12, 16, 0.4)";
    ctx.fillRect(0, 0, w, h);

    for (const s of stars) {
      s.z -= speed;
      if (s.z <= 0) s.z = 1;
      const x = (s.x - w / 2) / s.z + w / 2;
      const y = (s.y - h / 2) / s.z + h / 2;
      const alpha = 0.3 + (1 - s.z) * 0.6;
      ctx.beginPath();
      ctx.arc(x, y, s.r * (1 - s.z * 0.5), 0, Math.PI * 2);
      ctx.fillStyle = `rgba(200, 220, 255, ${alpha})`;
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

export function starfieldSettings(player) {
  const set = (k, v) => {
    setOpt(k, v);
    refreshViz(player);
  };
  const speed = getOpt("speed") ?? 0.5;
  const density = getOpt("density") ?? 0.5;
  return html`
    <div class="pluginSettings">
      <label class="pluginSettingsLabel">
        Speed
        <input type="range" min="0" max="100" value=${speed * 100} oninput=${(e) => set("speed", e.target.value / 100)} />
      </label>
      <label class="pluginSettingsLabel">
        Density
        <input type="range" min="0" max="100" value=${density * 100} oninput=${(e) => set("density", e.target.value / 100)} />
      </label>
    </div>
  `;
}
