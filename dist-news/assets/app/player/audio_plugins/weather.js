import { html } from "../../runtime/vendor.js";
import { refreshViz } from "./util.js";

export const WEATHER_KEY = "vodcasts_weather_v1";

function getOpt(k) {
  try {
    return JSON.parse(localStorage.getItem(WEATHER_KEY) || "{}")[k];
  } catch {}
  return null;
}

function setOpt(k, v) {
  try {
    const j = JSON.parse(localStorage.getItem(WEATHER_KEY) || "{}");
    j[k] = v;
    localStorage.setItem(WEATHER_KEY, JSON.stringify(j));
  } catch {}
}

/**
 * Weather animation (clouds + sun) for audio-only display.
 */
export function weather(container, opts = {}) {
  const media = opts.media;
  const canvas = document.createElement("canvas");
  canvas.className = "audioViz-canvas";
  canvas.setAttribute("aria-hidden", "true");
  container.appendChild(canvas);

  let clouds = [];
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
    clouds = [];
    for (let i = 0; i < 5; i++) {
      clouds.push({
        x: Math.random() * w,
        y: h * (0.2 + Math.random() * 0.4),
        r: 20 + Math.random() * 30,
        speed: 0.2 + Math.random() * 0.3,
      });
    }
  };

  const draw = () => {
    if (destroyed) return;
    const playing = media && !media.paused && !media.ended;
    const rate = playing ? (media?.playbackRate ?? 1) : 1;
    const speed = (playing ? 0.4 : 0.15) * rate;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const w = canvas.width;
    const h = canvas.height;

    const gradient = ctx.createLinearGradient(0, 0, 0, h);
    gradient.addColorStop(0, "rgba(60, 80, 120, 0.4)");
    gradient.addColorStop(1, "rgba(30, 45, 70, 0.5)");
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, w, h);

    ctx.fillStyle = "rgba(255, 220, 150, 0.5)";
    ctx.beginPath();
    ctx.arc(w * 0.75, h * 0.3, Math.min(w, h) * 0.12, 0, Math.PI * 2);
    ctx.fill();

    for (const c of clouds) {
      c.x += c.speed * speed;
      if (c.x > w + c.r * 2) c.x = -c.r * 2;
      ctx.fillStyle = "rgba(200, 220, 255, 0.35)";
      ctx.beginPath();
      ctx.arc(c.x, c.y, c.r * 0.6, 0, Math.PI * 2);
      ctx.arc(c.x + c.r * 0.5, c.y - c.r * 0.2, c.r * 0.8, 0, Math.PI * 2);
      ctx.arc(c.x + c.r, c.y, c.r * 0.6, 0, Math.PI * 2);
      ctx.fill();
    }

    const loc = getOpt("location");
    if (loc) {
      ctx.fillStyle = "rgba(138, 180, 248, 0.5)";
      ctx.font = `500 ${Math.min(w, h) * 0.06}px system-ui, sans-serif`;
      ctx.textAlign = "center";
      ctx.fillText(loc, w / 2, h - 16);
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

export function weatherSettings(player) {
  let refreshT = null;
  const set = (k, v) => {
    setOpt(k, v);
    clearTimeout(refreshT);
    refreshT = setTimeout(() => refreshViz(player), 400);
  };
  const location = getOpt("location") || "";
  return html`
    <div class="pluginSettings pluginSettingsWeather">
      <label class="pluginSettingsLabel">
        Location
        <input
          type="text"
          class="pluginSettingsInput"
          placeholder="City or coordinates"
          value=${location}
          oninput=${(e) => set("location", e.target.value)}
        />
      </label>
    </div>
  `;
}
