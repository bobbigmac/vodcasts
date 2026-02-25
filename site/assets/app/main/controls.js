// Keyboard + remote-control navigation and shortcuts for vodcasts.
// Self-contained: relies only on `data-keyhint` / `data-navitem` attributes in the DOM.

const STYLE_ID = "vodcasts-controls-style-v1";

function ensureStyle() {
  if (document.getElementById(STYLE_ID)) return;
  const el = document.createElement("style");
  el.id = STYLE_ID;
  el.textContent = `
.vodKeyHintBubble {
  position: fixed;
  z-index: 9999;
  padding: 2px 6px;
  font: 600 11px/1.2 var(--sans, system-ui);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  border-radius: 8px;
  border: 1px solid var(--edge, rgba(255,255,255,.2));
  background: color-mix(in srgb, var(--panel, rgba(0,0,0,.7)) 80%, transparent);
  color: var(--text, #fff);
  box-shadow: 0 4px 18px rgba(0,0,0,.35);
  pointer-events: none;
  user-select: none;
  opacity: 0;
  transform: translateY(-4px);
  transition: opacity 0.12s ease, transform 0.12s ease;
}
.vodKeyHintBubble.show { opacity: 1; transform: translateY(0) }
.vodKeyHintBubble .k {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 1px 5px;
  margin-right: 4px;
  border-radius: 6px;
  border: 1px solid color-mix(in srgb, var(--edge, rgba(255,255,255,.2)) 70%, transparent);
  background: rgba(255,255,255,.03);
  font-variant-numeric: tabular-nums;
}
.vodKeyHintBubble .lbl { color: var(--muted, rgba(255,255,255,.85)); font-weight: 650; letter-spacing: 0.02em; text-transform: none }
`;
  document.head.appendChild(el);
}

function isEditableEl(el) {
  if (!el) return false;
  const tag = (el.tagName || "").toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select") return true;
  if (el.isContentEditable) return true;
  return false;
}

function isTypingInComments() {
  const el = document.activeElement;
  if (!el) return false;
  if (!isEditableEl(el)) return false;
  // Narrow: only suppress shortcuts if typing in the comments UI.
  return !!el.closest?.(".commentsPanel, .commentsForm");
}

function isVisible(el) {
  if (!el) return false;
  if (el.disabled) return false;
  if (el.closest?.('[aria-hidden="true"]')) return false;
  if (el.closest?.(".commentsPanel")) return false;
  const r = el.getBoundingClientRect?.();
  if (!r) return false;
  if (r.width <= 0 || r.height <= 0) return false;
  if (r.bottom < 4 || r.top > window.innerHeight - 4) return false;
  if (r.right < 4 || r.left > window.innerWidth - 4) return false;
  // offsetParent is null for fixed elements; treat them as visible.
  const st = window.getComputedStyle(el);
  if (st.display === "none" || st.visibility === "hidden" || st.opacity === "0") return false;
  return true;
}

function getNavItems() {
  const out = new Set();
  const add = (els) => {
    for (const el of els) if (isVisible(el)) out.add(el);
  };
  add(document.querySelectorAll("[data-navitem]"));

  // Fallback: any focusable buttons inside visible UI panels/guide bar.
  const containers = [".guideBar", "#guidePanel", "#detailsPanel", "#historyPanel"];
  for (const sel of containers) {
    const c = document.querySelector(sel);
    if (!c || c.getAttribute?.("aria-hidden") === "true") continue;
    add(c.querySelectorAll("button, [role='button'][tabindex], .speedBtn, .volumeBtn"));
  }

  return [...out];
}

function focusFirstNavItem() {
  const items = getNavItems();
  const first = items[0];
  if (first && typeof first.focus === "function") first.focus();
}

function pickNextByDirection(items, fromEl, dir) {
  if (!fromEl) return null;
  const fr = fromEl.getBoundingClientRect();
  const fx = fr.left + fr.width / 2;
  const fy = fr.top + fr.height / 2;
  let best = null;
  let bestScore = Infinity;

  for (const el of items) {
    if (el === fromEl) continue;
    const r = el.getBoundingClientRect();
    const cx = r.left + r.width / 2;
    const cy = r.top + r.height / 2;
    const dx = cx - fx;
    const dy = cy - fy;

    if (dir === "left" && dx >= -2) continue;
    if (dir === "right" && dx <= 2) continue;
    if (dir === "up" && dy >= -2) continue;
    if (dir === "down" && dy <= 2) continue;

    const primary = dir === "left" || dir === "right" ? Math.abs(dx) : Math.abs(dy);
    const secondary = dir === "left" || dir === "right" ? Math.abs(dy) : Math.abs(dx);
    const dist = Math.hypot(dx, dy);
    const score = primary * 1000 + secondary * 4 + dist;
    if (score < bestScore) {
      bestScore = score;
      best = el;
    }
  }

  return best;
}

function clickEl(el) {
  if (!el) return false;
  if (!isVisible(el)) return false;
  try {
    el.click();
    return true;
  } catch {
    return false;
  }
}

function clickIfVisible(sel) {
  return clickEl(document.querySelector(sel));
}

function toggleFullscreen() {
  const playerEl = document.getElementById("player") || document.querySelector(".player") || document.querySelector("video");
  if (!playerEl) return;
  const doc = document;
  const fsEl = doc.fullscreenElement;
  if (!fsEl) {
    try {
      playerEl.requestFullscreen?.();
    } catch {}
  } else {
    try {
      doc.exitFullscreen?.();
    } catch {}
  }
}

function normalizeKey(e) {
  if (!e || typeof e.key !== "string") return "";
  const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
  return k;
}

function isMediaKey(e) {
  const k = String(e?.key || "");
  return (
    k.startsWith("Media") ||
    k.startsWith("AudioVolume") ||
    k === "Play" ||
    k === "Pause" ||
    k === "Stop" ||
    k === "NextTrack" ||
    k === "PreviousTrack"
  );
}

function buildHints() {
  const els = [...document.querySelectorAll("[data-keyhint]")].filter(isVisible);
  return els.map((target) => {
    const raw = String(target.getAttribute("data-keyhint") || "").trim();
    if (!raw) return null;
    const bubble = document.createElement("div");
    bubble.className = "vodKeyHintBubble";
    const [keyPart, ...rest] = raw.split(/\s+—\s+|\s+-\s+/);
    const labelPart = rest.join(" - ").trim();
    bubble.innerHTML = `<span class="k">${escapeHtml(keyPart || raw)}</span>${labelPart ? `<span class="lbl">${escapeHtml(labelPart)}</span>` : ""}`;
    document.body.appendChild(bubble);
    return { target, bubble };
  }).filter(Boolean);
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function positionHints(hints) {
  for (const h of hints) {
    const r = h.target.getBoundingClientRect();
    const b = h.bubble;
    const pad = 6;
    const x = Math.min(window.innerWidth - pad, Math.max(pad, r.right));
    const y = Math.min(window.innerHeight - pad, Math.max(pad, r.top));
    b.style.left = `${x}px`;
    b.style.top = `${y}px`;
    b.classList.add("show");
  }
}

export function installControls() {
  ensureStyle();

  let altHeld = false;
  let hints = [];
  let hintRaf = null;

  const stopHints = () => {
    if (hintRaf) cancelAnimationFrame(hintRaf);
    hintRaf = null;
    for (const h of hints) {
      try {
        h.bubble.remove();
      } catch {}
    }
    hints = [];
  };

  const startHints = () => {
    stopHints();
    hints = buildHints();
    const tick = () => {
      if (!altHeld) return;
      positionHints(hints);
      hintRaf = requestAnimationFrame(tick);
    };
    tick();
  };

  const onKeyDown = (e) => {
    const k = normalizeKey(e);

    // Alt-held "legend" overlay.
    if (e.key === "Alt") {
      if (!altHeld) {
        altHeld = true;
        startHints();
      }
      e.preventDefault();
      e.stopPropagation();
      return;
    }

    const typingComments = isTypingInComments();
    if (typingComments && !isMediaKey(e) && e.key !== "Escape") return;

    // Remote-style activation.
    if (e.key === "Enter" || e.key === "NumpadEnter" || e.key === "Select" || e.key === "Accept") {
      if (typingComments) return;
      const a = document.activeElement;
      if (a && a !== document.body && clickEl(a)) {
        e.preventDefault();
        e.stopPropagation();
      }
      return;
    }

    // D-pad navigation (TV remotes + keyboard arrows).
    if (e.key === "ArrowLeft" || e.key === "ArrowRight" || e.key === "ArrowUp" || e.key === "ArrowDown") {
      if (typingComments) return;
      const takeover = document.querySelector(".guideBarTakeover[data-navmode]");
      if (takeover && isVisible(takeover) && takeover.getAttribute("data-navmode") === "arrows") {
        return; // allow takeover (e.g. captions) to use arrows for adjustments
      }
      const items = getNavItems();
      if (!items.length) return;
      const cur = items.includes(document.activeElement) ? document.activeElement : null;
      const dir = e.key === "ArrowLeft" ? "left" : e.key === "ArrowRight" ? "right" : e.key === "ArrowUp" ? "up" : "down";
      const from = cur || items[0];
      const next = pickNextByDirection(items, from, dir) || null;
      if (next && typeof next.focus === "function") {
        next.focus();
        e.preventDefault();
        e.stopPropagation();
        return;
      }
      // If nothing focused yet, seed focus.
      if (!cur) {
        focusFirstNavItem();
        e.preventDefault();
        e.stopPropagation();
      }
      return;
    }

    // Browser-back / remote back.
    if (e.key === "BrowserBack" || e.key === "GoBack") {
      if (typingComments) return;
      if (clickIfVisible("#btnCloseGuide") || clickIfVisible("#btnDetails") || clickIfVisible("#btnHistory")) {
        e.preventDefault();
        e.stopPropagation();
      }
      return;
    }

    // Media keys (hardware buttons).
    if (e.key === "MediaPlayPause" || e.key === "Play" || e.key === "Pause") {
      if (clickIfVisible("#btnPlay")) {
        e.preventDefault();
        e.stopPropagation();
      }
      return;
    }
    if (e.key === "MediaTrackPrevious" || e.key === "PreviousTrack") {
      if (clickIfVisible("#btnSeekBack")) {
        e.preventDefault();
        e.stopPropagation();
      }
      return;
    }
    if (e.key === "MediaTrackNext" || e.key === "NextTrack") {
      if (clickIfVisible("#btnSeekFwd")) {
        e.preventDefault();
        e.stopPropagation();
      }
      return;
    }
    if (e.key === "AudioVolumeMute") {
      if (clickIfVisible(".volumeBtn.volumeLevel")) {
        e.preventDefault();
        e.stopPropagation();
      }
      return;
    }
    if (e.key === "AudioVolumeUp") {
      if (clickIfVisible(".volumeBtn.volumeUp")) {
        e.preventDefault();
        e.stopPropagation();
      }
      return;
    }
    if (e.key === "AudioVolumeDown") {
      if (clickIfVisible(".volumeBtn.volumeDown")) {
        e.preventDefault();
        e.stopPropagation();
      }
      return;
    }

    // Single-key shortcuts (ignored when typing comments).
    if (e.altKey || e.metaKey || e.ctrlKey) return;
    if (!k) return;

    if (k === " " || k === "k") {
      if (typingComments) return;
      if (clickIfVisible("#btnPlay")) {
        e.preventDefault();
        e.stopPropagation();
      }
      return;
    }
    if (k === "j") {
      if (typingComments) return;
      if (clickIfVisible("#btnSeekBack")) {
        e.preventDefault();
        e.stopPropagation();
      }
      return;
    }
    if (k === "l") {
      if (typingComments) return;
      if (clickIfVisible("#btnSeekFwd")) {
        e.preventDefault();
        e.stopPropagation();
      }
      return;
    }
    if (k === "m") {
      if (typingComments) return;
      if (clickIfVisible(".volumeBtn.volumeLevel")) {
        e.preventDefault();
        e.stopPropagation();
      }
      return;
    }
    if (k === "c") {
      if (typingComments) return;
      if (clickIfVisible("#btnCC")) {
        e.preventDefault();
        e.stopPropagation();
      }
      return;
    }
    if (k === "r") {
      if (typingComments) return;
      if (clickIfVisible("#btnRandom")) {
        e.preventDefault();
        e.stopPropagation();
      }
      return;
    }
    if (k === "[") {
      if (typingComments) return;
      if (clickIfVisible(".speedBtn.speedDown")) {
        e.preventDefault();
        e.stopPropagation();
      }
      return;
    }
    if (k === "]") {
      if (typingComments) return;
      if (clickIfVisible(".speedBtn.speedUp")) {
        e.preventDefault();
        e.stopPropagation();
      }
      return;
    }
    if (k === "s") {
      if (typingComments) return;
      if (clickIfVisible("#btnSleep")) {
        e.preventDefault();
        e.stopPropagation();
      }
      return;
    }
    if (k === "t") {
      if (typingComments) return;
      if (clickIfVisible("#btnTheme")) {
        e.preventDefault();
        e.stopPropagation();
      }
      return;
    }
    if (k === "g") {
      if (typingComments) return;
      const opened = clickIfVisible(".guideNowBlock") || clickIfVisible("#btnCloseGuide");
      if (opened) {
        e.preventDefault();
        e.stopPropagation();
      }
      return;
    }
    if (k === "d") {
      if (typingComments) return;
      if (clickIfVisible("#btnDetails")) {
        e.preventDefault();
        e.stopPropagation();
      }
      return;
    }
    if (k === "y") {
      if (typingComments) return;
      if (clickIfVisible("#btnHistory")) {
        e.preventDefault();
        e.stopPropagation();
      }
      return;
    }
    if (k === "f") {
      if (typingComments) return;
      toggleFullscreen();
      e.preventDefault();
      e.stopPropagation();
      return;
    }
  };

  const onKeyUp = (e) => {
    if (e.key === "Alt") {
      altHeld = false;
      stopHints();
      e.preventDefault();
      e.stopPropagation();
      return;
    }
  };

  const onBlur = () => {
    altHeld = false;
    stopHints();
  };

  window.addEventListener("keydown", onKeyDown, { capture: true });
  window.addEventListener("keyup", onKeyUp, { capture: true });
  window.addEventListener("blur", onBlur);

  return () => {
    window.removeEventListener("keydown", onKeyDown, { capture: true });
    window.removeEventListener("keyup", onKeyUp, { capture: true });
    window.removeEventListener("blur", onBlur);
    stopHints();
  };
}
