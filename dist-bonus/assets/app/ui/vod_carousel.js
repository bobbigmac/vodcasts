import { html, useEffect, useRef, useState } from "../runtime/vendor.js";

export function seededIndex(seed, mod = 8) {
  const s = String(seed || "");
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  const u = h >>> 0;
  return mod > 0 ? u % mod : 0;
}

export function titlePosClass(seed) {
  return `vodTitlePos-${seededIndex(seed, 8)}`;
}

function seededU32(seed) {
  const s = String(seed || "");
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function clamp(n, a, b) {
  return Math.min(b, Math.max(a, n));
}

export function thumbFallbackStyle(seed) {
  const u = seededU32(seed);
  const hue = u % 360;
  const hue2 = (hue + 35 + ((u >>> 8) % 70)) % 360;
  const pat = seededIndex(seed, 8);
  const sat = 62 + ((u >>> 16) % 10); // 62–71
  const lit1 = 22 + ((u >>> 20) % 10); // 22–31
  const lit2 = clamp(lit1 - 10, 10, 26);
  const c1 = `hsl(${hue}, ${sat}%, ${lit1}%)`;
  const c2 = `hsl(${hue2}, ${sat + 6}%, ${lit2}%)`;
  const base = `linear-gradient(135deg, ${c1}, ${c2})`;

  const overlayA = "rgba(255,255,255,0.07)";
  const overlayB = "rgba(255,255,255,0)";
  const overlayC = "rgba(0,0,0,0.22)";

  let bg = base;
  if (pat === 0) bg = `radial-gradient(circle at 20% 20%, ${overlayA}, ${overlayB} 55%), ${base}`;
  else if (pat === 1) bg = `radial-gradient(circle at 80% 10%, ${overlayA}, ${overlayB} 50%), ${base}`;
  else if (pat === 2) bg = `radial-gradient(circle at 30% 80%, ${overlayA}, ${overlayB} 55%), ${base}`;
  else if (pat === 3) bg = `repeating-linear-gradient(45deg, ${overlayA} 0 10px, ${overlayB} 10px 22px), ${base}`;
  else if (pat === 4) bg = `repeating-linear-gradient(135deg, ${overlayA} 0 9px, ${overlayB} 9px 20px), ${base}`;
  else if (pat === 5) bg = `linear-gradient(180deg, ${overlayB}, ${overlayC}), ${base}`;
  else if (pat === 6) bg = `radial-gradient(circle at 60% 65%, ${overlayA}, ${overlayB} 52%), ${base}`;
  else bg = `radial-gradient(circle at 40% 40%, ${overlayA}, ${overlayB} 52%), ${base}`;

  return { "--vod-fallback-bg": bg };
}

export function fallbackInitials(title) {
  const t = String(title || "").trim();
  if (!t) return "";
  const words = t.split(/\s+/).filter(Boolean);
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0].slice(0, 1) + words[1].slice(0, 1)).toUpperCase();
}

export function VodCarouselRow({ rowId, title, children, className = "" }) {
  const stripRef = useRef(null);
  const [canLeft, setCanLeft] = useState(false);
  const [canRight, setCanRight] = useState(false);

  const updateArrows = () => {
    const el = stripRef.current;
    if (!el) return;
    const left = el.scrollLeft || 0;
    const max = Math.max(0, el.scrollWidth - el.clientWidth);
    setCanLeft(left > 2);
    setCanRight(left < max - 2);
  };

  const scrollByViewport = (dir) => {
    const el = stripRef.current;
    if (!el) return;
    const dx = Math.max(120, Math.round(el.clientWidth * 0.82)) * (dir < 0 ? -1 : 1);
    try {
      el.scrollBy({ left: dx, behavior: "smooth" });
    } catch {
      el.scrollLeft += dx;
    }
  };

  useEffect(() => {
    updateArrows();
    const el = stripRef.current;
    if (!el) return;
    const onScroll = () => updateArrows();
    el.addEventListener("scroll", onScroll, { passive: true });
    const onResize = () => updateArrows();
    window.addEventListener("resize", onResize, { passive: true });
    return () => {
      try {
        el.removeEventListener("scroll", onScroll);
      } catch {}
      try {
        window.removeEventListener("resize", onResize);
      } catch {}
    };
  }, []);

  return html`
    <section class=${"vodCarouselRow " + className} data-carousel-rowroot=${rowId}>
      ${title ? html`<h3 class="vodCarouselTitle">${title}</h3>` : ""}
      <div class="vodCarouselViewport">
        <button
          class=${"vodCarouselArrow vodCarouselArrowLeft" + (canLeft ? "" : " disabled")}
          type="button"
          aria-label="Scroll left"
          data-navitem="1"
          data-carousel-arrow="left"
          disabled=${!canLeft}
          onClick=${() => scrollByViewport(-1)}
        >
          ‹
        </button>
        <div class="vodCarouselStrip" ref=${stripRef}>
          <div class="vodCarouselStripInner" data-carousel-row=${rowId}>${children}</div>
        </div>
        <button
          class=${"vodCarouselArrow vodCarouselArrowRight" + (canRight ? "" : " disabled")}
          type="button"
          aria-label="Scroll right"
          data-navitem="1"
          data-carousel-arrow="right"
          disabled=${!canRight}
          onClick=${() => scrollByViewport(1)}
        >
          ›
        </button>
      </div>
    </section>
  `;
}
