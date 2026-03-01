import { html } from "../../runtime/vendor.js";
import { refreshViz, numberPicker } from "./util.js";

export const SLIDESHOW_KEY = "vodcasts_slideshow_v1";

function getOpt(k, def) {
  try {
    const j = JSON.parse(localStorage.getItem(SLIDESHOW_KEY) || "{}");
    return j[k] ?? def;
  } catch {}
  return def;
}

function setOpt(k, v) {
  try {
    const j = JSON.parse(localStorage.getItem(SLIDESHOW_KEY) || "{}");
    j[k] = v;
    localStorage.setItem(SLIDESHOW_KEY, JSON.stringify(j));
  } catch {}
}

/**
 * Random photo slideshow (Picsum) for audio-only display.
 */
export function slideshow(container, opts = {}) {
  const media = opts.media;
  const img = document.createElement("img");
  img.className = "audioViz-slideshow";
  img.setAttribute("aria-hidden", "true");
  img.alt = "";
  container.appendChild(img);

  let timeoutId = 0;
  let destroyed = false;

  const loadNext = () => {
    if (destroyed) return;
    const w = Math.max(800, Math.ceil((container.clientWidth || 320) * 1.5));
    const h = Math.max(600, Math.ceil((container.clientHeight || 180) * 1.5));
    const seed = Math.floor(Math.random() * 1e6);
    img.src = `https://picsum.photos/seed/${seed}/${w}/${h}`;
    const intervalSec = Math.max(5, Math.min(120, getOpt("interval", 18) || 18));
    const rate = media && !media.paused && !media.ended ? (media.playbackRate ?? 1) : 1;
    const delay = (intervalSec * 1000) / rate;
    timeoutId = setTimeout(loadNext, delay);
  };

  const start = () => {
    if (destroyed) return;
    loadNext();
  };

  const ro = new ResizeObserver(() => {
    if (destroyed) return;
    const w = container.clientWidth || 320;
    const h = container.clientHeight || 180;
    img.style.width = w + "px";
    img.style.height = h + "px";
  });
  ro.observe(container);
  img.style.width = (container.clientWidth || 320) + "px";
  img.style.height = (container.clientHeight || 180) + "px";

  const destroy = () => {
    destroyed = true;
    clearTimeout(timeoutId);
    ro.disconnect();
    img.src = "";
    try {
      img.remove();
    } catch {}
  };

  return { start, destroy };
}

export function slideshowSettings(player) {
  const set = (k, v) => {
    setOpt(k, v);
    refreshViz(player);
  };
  const interval = getOpt("interval") ?? 18;
  return html`
    <div class="pluginSettings">
      ${numberPicker("Interval (s)", interval, 5, 120, 1, (v) => set("interval", v), (v) => v + "s")}
    </div>
  `;
}
