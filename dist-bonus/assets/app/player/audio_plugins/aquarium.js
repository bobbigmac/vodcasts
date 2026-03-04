import { html } from "../../runtime/vendor.js";
import { refreshViz, numberPicker } from "./util.js";

export const AQUA_KEY = "vodcasts_aquarium_v1";

function getOpt(k, def) {
  try {
    const j = JSON.parse(localStorage.getItem(AQUA_KEY) || "{}");
    return j[k] ?? def;
  } catch {}
  return def;
}

function setOpt(k, v) {
  try {
    const j = JSON.parse(localStorage.getItem(AQUA_KEY) || "{}");
    j[k] = v;
    localStorage.setItem(AQUA_KEY, JSON.stringify(j));
  } catch {}
}

/**
 * Aquarium animation for audio-only display.
 */
export function aquarium(container, opts = {}) {
  const media = opts.media;
  const canvas = document.createElement("canvas");
  canvas.className = "audioViz-canvas";
  canvas.setAttribute("aria-hidden", "true");
  container.appendChild(canvas);

  let fish = [];
  let bubbles = [];
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
    const scale = Math.min(w, h) / 400;
    const nFish = Math.max(8, Math.min(25, Math.floor((w * h) / 25000) + getOpt("fishCount", 0)));
    fish = [];
    for (let i = 0; i < nFish; i++) {
      const vx = (0.3 + Math.random() * 0.5) * (Math.random() > 0.5 ? 1 : -1);
      fish.push({
        x: Math.random() * w,
        y: h * (0.12 + Math.random() * 0.76),
        vx,
        vy: (Math.random() - 0.5) * 0.2,
        phase: Math.random() * Math.PI * 2,
        size: 0.6 + Math.random() * 0.7,
        flipProgress: 0,
      });
    }
    const nBubbles = Math.max(15, Math.min(40, Math.floor((w * h) / 8000) + getOpt("bubbleCount", 0)));
    bubbles = [];
    for (let i = 0; i < nBubbles; i++) {
      bubbles.push({
        x: Math.random() * w,
        y: h + Math.random() * 80,
        r: (2 + Math.random() * 5) * Math.min(1.5, scale),
        speed: 0.5 + Math.random() * 1,
      });
    }
  };

  const draw = () => {
    if (destroyed) return;
    const playing = media && !media.paused && !media.ended;
    const rate = playing ? (media?.playbackRate ?? 1) : 1;
    const speed = (playing ? 1 : 0.3) * rate;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const w = canvas.width;
    const h = canvas.height;

    const gradient = ctx.createLinearGradient(0, 0, 0, h);
    gradient.addColorStop(0, "rgba(20, 50, 80, 0.5)");
    gradient.addColorStop(1, "rgba(10, 30, 50, 0.6)");
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, w, h);

    for (const b of bubbles) {
      b.y -= b.speed * speed;
      if (b.y < -b.r * 2) {
        b.y = h + b.r * 2;
        b.x = Math.random() * w;
      }
      b.x += Math.sin(b.y * 0.04) * 0.4;
      ctx.fillStyle = "rgba(150, 200, 255, 0.3)";
      ctx.beginPath();
      ctx.arc(b.x, b.y, b.r, 0, Math.PI * 2);
      ctx.fill();
    }

    const scale = Math.min(w, h) / 350;
    const speedMult = 0.8 + (getOpt("speed", 0.5) || 0.5);
    for (const f of fish) {
      f.x += f.vx * speed * speedMult;
      f.y += f.vy * speed * speedMult;
      if (f.x < -60 || f.x > w + 60) {
        f.vx *= -1;
        f.flipProgress = 1;
      }
      if (f.y < 40 || f.y > h - 40) f.vy *= -1;
      if (Math.random() < 0.0012) {
        f.vx *= -1;
        f.flipProgress = 1;
      }
      f.phase += 0.06 * rate;

      const dir = f.vx > 0 ? 1 : -1;
      const flipScale = f.flipProgress > 0 ? 0.4 + 0.6 * (1 - f.flipProgress) : 1;
      f.flipProgress = Math.max(0, f.flipProgress - 0.18);

      const bodyLen = 18 * scale * f.size;
      const tailW = 8 * scale * f.size;
      ctx.save();
      ctx.translate(f.x, f.y);
      ctx.scale(dir * flipScale, 1);
      ctx.fillStyle = "rgba(255, 180, 100, 0.55)";
      ctx.beginPath();
      ctx.ellipse(0, 0, bodyLen, 5 * scale, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.beginPath();
      ctx.moveTo(-bodyLen, 0);
      ctx.lineTo(-bodyLen - tailW, -5 * scale);
      ctx.lineTo(-bodyLen - tailW, 5 * scale);
      ctx.closePath();
      ctx.fill();
      ctx.restore();
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

export function aquariumSettings(player) {
  const set = (k, v) => {
    setOpt(k, v);
    refreshViz(player);
  };
  const fishCount = getOpt("fishCount") ?? 0;
  const bubbleCount = getOpt("bubbleCount") ?? 0;
  const speed = getOpt("speed") ?? 0.5;
  return html`
    <div class="pluginSettings">
      ${numberPicker("Fish (±)", fishCount, -5, 15, 1, (v) => set("fishCount", v))}
      ${numberPicker("Bubbles (±)", bubbleCount, -10, 20, 1, (v) => set("bubbleCount", v))}
      <label class="pluginSettingsLabel">
        Speed
        <input type="range" min="0" max="100" value=${speed * 100} oninput=${(e) => set("speed", e.target.value / 100)} />
      </label>
    </div>
  `;
}
