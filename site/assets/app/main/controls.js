// Keyboard + remote-control navigation and shortcuts for vodcasts.
// Self-contained: relies only on `data-keyhint` / `data-navitem` attributes in the DOM.

const STYLE_ID = "vodcasts-controls-style-v1";

function ensureStyle() {
  if (document.getElementById(STYLE_ID)) return;
  const el = document.createElement("style");
  el.id = STYLE_ID;
  el.textContent = `
.guideNowBlock:focus-visible { outline: 2px solid color-mix(in srgb, var(--accent) 70%, transparent) }
.guideChannelRow:focus-visible { outline: 2px solid color-mix(in srgb, var(--accent) 70%, transparent); background: rgba(255,255,255,.03) }
.guideBtn:focus-visible,
.speedBtn:focus-visible,
.volumeBtn:focus-visible,
.cornerBtn:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--accent) 70%, transparent);
  outline-offset: 2px;
}

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
  if (el.disabled) return false;
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

function clickIfPresent(sel) {
  const el = document.querySelector(sel);
  if (!el) return false;
  // Don't require visibility; this is used for media controls and shortcuts.
  return clickEl(el);
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

function keyCodeOf(e) {
  const kc = e?.keyCode ?? e?.which;
  return Number.isFinite(Number(kc)) ? Number(kc) : 0;
}

function isKey(e, keys = [], codes = [], keyCodes = []) {
  const k = String(e?.key || "");
  const c = String(e?.code || "");
  const kc = keyCodeOf(e);
  if (keys.includes(k)) return true;
  if (codes.includes(c)) return true;
  if (keyCodes.includes(kc)) return true;
  return false;
}

function isMediaKey(e) {
  const k = String(e?.key || "");
  const kc = keyCodeOf(e);
  return (
    k.startsWith("Media") ||
    k.startsWith("AudioVolume") ||
    kc === 179 || // Play/Pause
    kc === 178 || // Stop
    kc === 176 || // Next
    kc === 177 || // Previous
    kc === 173 || // Mute
    kc === 174 || // Volume down
    kc === 175 || // Volume up
    k === "Play" ||
    k === "Pause" ||
    k === "Stop" ||
    k === "NextTrack" ||
    k === "PreviousTrack"
  );
}

function setupMediaSession({ getVideoEl } = {}) {
  const ms = navigator.mediaSession;
  if (!ms || typeof ms.setActionHandler !== "function") return () => {};

  let videoEl = null;
  let cleanupVideo = null;
  let obs = null;

  const safeSet = (action, handler) => {
    try {
      ms.setActionHandler(action, handler);
    } catch {}
  };

  const updateState = () => {
    if (!videoEl) return;
    try {
      ms.playbackState = videoEl.paused ? "paused" : "playing";
    } catch {}
    try {
      if (typeof ms.setPositionState === "function") {
        const dur = videoEl.duration;
        const pos = videoEl.currentTime;
        const rate = videoEl.playbackRate || 1;
        if (Number.isFinite(dur) && dur > 0) ms.setPositionState({ duration: dur, playbackRate: rate, position: Math.max(0, pos || 0) });
      }
    } catch {}
  };

  const connect = () => {
    videoEl = (getVideoEl && getVideoEl()) || document.getElementById("video") || document.querySelector("video");
    if (!videoEl) return false;

    const onPlay = () => updateState();
    const onPause = () => updateState();
    const onTime = () => updateState();

    videoEl.addEventListener("play", onPlay);
    videoEl.addEventListener("pause", onPause);
    videoEl.addEventListener("ratechange", onTime);
    videoEl.addEventListener("timeupdate", onTime);
    videoEl.addEventListener("durationchange", onTime);
    updateState();

    safeSet("play", async () => {
      try {
        await videoEl.play();
      } catch {
        clickIfPresent("#btnPlay");
      }
      updateState();
    });
    safeSet("pause", () => {
      try {
        videoEl.pause();
      } catch {
        clickIfPresent("#btnPlay");
      }
      updateState();
    });
    safeSet("stop", () => {
      try {
        videoEl.pause();
      } catch {}
      updateState();
    });
    safeSet("previoustrack", () => {
      clickIfPresent("#btnSeekBack");
      updateState();
    });
    safeSet("nexttrack", () => {
      clickIfPresent("#btnSeekFwd");
      updateState();
    });
    safeSet("seekbackward", (details) => {
      const off = Number(details?.seekOffset);
      if (Number.isFinite(off) && off > 0) {
        try {
          videoEl.currentTime = Math.max(0, (videoEl.currentTime || 0) - off);
        } catch {
          clickIfPresent("#btnSeekBack");
        }
        updateState();
        return;
      }
      clickIfPresent("#btnSeekBack");
      updateState();
    });
    safeSet("seekforward", (details) => {
      const off = Number(details?.seekOffset);
      if (Number.isFinite(off) && off > 0) {
        try {
          videoEl.currentTime = Math.max(0, (videoEl.currentTime || 0) + off);
        } catch {
          clickIfPresent("#btnSeekFwd");
        }
        updateState();
        return;
      }
      clickIfPresent("#btnSeekFwd");
      updateState();
    });
    safeSet("seekto", (details) => {
      const t = Number(details?.seekTime);
      if (!Number.isFinite(t)) return;
      try {
        videoEl.currentTime = Math.max(0, t);
      } catch {}
      updateState();
    });

    cleanupVideo = () => {
      try {
        videoEl.removeEventListener("play", onPlay);
        videoEl.removeEventListener("pause", onPause);
        videoEl.removeEventListener("ratechange", onTime);
        videoEl.removeEventListener("timeupdate", onTime);
        videoEl.removeEventListener("durationchange", onTime);
      } catch {}
      cleanupVideo = null;
      videoEl = null;
    };

    return true;
  };

  if (!connect()) {
    obs = new MutationObserver(() => {
      if (videoEl) return;
      if (connect() && obs) {
        obs.disconnect();
        obs = null;
      }
    });
    try {
      obs.observe(document.documentElement, { childList: true, subtree: true });
    } catch {}
  }

  return () => {
    if (obs) {
      try {
        obs.disconnect();
      } catch {}
      obs = null;
    }
    if (cleanupVideo) cleanupVideo();
    // Clear handlers (best-effort).
    ["play", "pause", "stop", "previoustrack", "nexttrack", "seekbackward", "seekforward", "seekto"].forEach((a) => safeSet(a, null));
  };
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
  let hintMode = null; // "alt" | "temp" | null
  let hints = [];
  let hintRaf = null;
  let hintTo = null;
  const cleanupMediaSession = setupMediaSession();

  const stopHints = () => {
    if (hintRaf) cancelAnimationFrame(hintRaf);
    hintRaf = null;
    if (hintTo) clearTimeout(hintTo);
    hintTo = null;
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

  const showHintsTemporarily = (ms = 2500) => {
    altHeld = true;
    hintMode = "temp";
    startHints();
    if (hintTo) clearTimeout(hintTo);
    hintTo = setTimeout(() => {
      if (hintMode !== "temp") return;
      altHeld = false;
      hintMode = null;
      stopHints();
    }, Math.max(250, Number(ms) || 2500));
  };

  const onKeyDown = (e) => {
    const k = normalizeKey(e);

    // Alt-held "legend" overlay.
    if (e.key === "Alt") {
      if (!altHeld) {
        altHeld = true;
        hintMode = "alt";
        startHints();
      }
      e.preventDefault();
      return;
    }

    const typingComments = isTypingInComments();
    if (typingComments && !isMediaKey(e) && e.key !== "Escape") return;

    // Common TV/remote keys we might see (Roku/WebView/SmartTV variants).
    // Prefer semantics over UI visibility; app may be faded/backgrounded.
    const isBack =
      isKey(e, ["BrowserBack", "GoBack", "Back", "Exit", "Cancel"], [], [461, 10009]) || // 461/10009 show up on some TV browsers
      (e.key === "Backspace" && !typingComments);
    const isHome = isKey(e, ["Home", "BrowserHome", "GoHome"], [], [36]);
    const isMenu = isKey(e, ["ContextMenu", "Menu", "Options"], [], [93]);
    const isInfo = isKey(e, ["Info", "Guide", "TVGuide"], [], []);

    if (isMenu) {
      if (!typingComments) {
        showHintsTemporarily(2800);
        e.preventDefault();
      }
      return;
    }

    if (isHome) {
      if (typingComments) return;
      // "Home" should get the UI back to a sane state.
      // Best-effort: trigger the app's Escape handler.
      try {
        document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
      } catch {}
      focusFirstNavItem();
      e.preventDefault();
      return;
    }

    if (isInfo) {
      if (typingComments) return;
      if (clickIfPresent("#btnDetails")) {
        e.preventDefault();
      }
      return;
    }

    if (isBack) {
      if (typingComments) return;
      // Try close buttons first, then toggle panels, then fall back to Escape.
      const closed =
        clickIfVisible("#btnCloseGuide") ||
        clickIfVisible("#btnCloseDetails") ||
        clickIfVisible(".historyBtnClose") ||
        clickIfVisible("#btnDetails") ||
        clickIfVisible("#btnHistory");
      if (!closed) {
        try {
          document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
        } catch {}
      }
      e.preventDefault();
      return;
    }

    // Remote-style activation.
    if (e.key === "Enter" || e.key === "NumpadEnter" || e.key === "Select" || e.key === "Accept") {
      if (typingComments) return;
      const a = document.activeElement;
      if (a && a !== document.body && clickEl(a)) {
        e.preventDefault();
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
        return;
      }
      // If nothing focused yet, seed focus.
      if (!cur) {
        focusFirstNavItem();
        e.preventDefault();
      }
      return;
    }

    // Browser-back / remote back.
    if (e.key === "BrowserBack" || e.key === "GoBack") {
      if (typingComments) return;
      if (clickIfVisible("#btnCloseGuide") || clickIfVisible("#btnDetails") || clickIfVisible("#btnHistory")) {
        e.preventDefault();
      }
      return;
    }

    // Media keys (hardware buttons).
    if (isKey(e, ["MediaPlayPause", "Play", "Pause", "MediaPlay", "MediaPause"], ["MediaPlayPause"], [179])) {
      if (clickIfPresent("#btnPlay")) {
        e.preventDefault();
      }
      return;
    }
    if (isKey(e, ["MediaStop", "Stop"], ["MediaStop"], [178])) {
      // Stop is effectively Pause for us.
      const v = document.getElementById("video") || document.querySelector("video");
      if (v && !v.paused) {
        try {
          v.pause();
          e.preventDefault();
          return;
        } catch {}
      }
      if (clickIfPresent("#btnPlay")) e.preventDefault();
      return;
    }
    if (isKey(e, ["MediaRewind", "Rewind"], ["MediaRewind"], [])) {
      if (clickIfPresent("#btnSeekBack")) e.preventDefault();
      return;
    }
    if (isKey(e, ["MediaFastForward", "FastForward"], ["MediaFastForward"], [])) {
      if (clickIfPresent("#btnSeekFwd")) e.preventDefault();
      return;
    }
    if (isKey(e, ["MediaReplay", "Replay", "InstantReplay"], [], [])) {
      if (clickIfPresent("#btnSeekBack")) e.preventDefault();
      return;
    }
    if (e.key === "MediaTrackPrevious" || e.key === "PreviousTrack") {
      if (clickIfPresent("#btnSeekBack")) {
        e.preventDefault();
      }
      return;
    }
    if (e.key === "MediaTrackNext" || e.key === "NextTrack") {
      if (clickIfPresent("#btnSeekFwd")) {
        e.preventDefault();
      }
      return;
    }
    if (e.key === "AudioVolumeMute") {
      if (clickIfPresent(".volumeBtn.volumeLevel")) {
        e.preventDefault();
      }
      return;
    }
    if (e.key === "AudioVolumeUp") {
      if (clickIfPresent(".volumeBtn.volumeUp")) {
        e.preventDefault();
      }
      return;
    }
    if (e.key === "AudioVolumeDown") {
      if (clickIfPresent(".volumeBtn.volumeDown")) {
        e.preventDefault();
      }
      return;
    }

    // Single-key shortcuts (ignored when typing comments).
    if (e.altKey || e.metaKey || e.ctrlKey) return;
    if (!k) return;

    if (k === " " || k === "k") {
      if (typingComments) return;
      if (clickIfPresent("#btnPlay")) {
        e.preventDefault();
      }
      return;
    }
    if (k === "j") {
      if (typingComments) return;
      if (clickIfPresent("#btnSeekBack")) {
        e.preventDefault();
      }
      return;
    }
    if (k === "l") {
      if (typingComments) return;
      if (clickIfPresent("#btnSeekFwd")) {
        e.preventDefault();
      }
      return;
    }
    if (k === "m") {
      if (typingComments) return;
      if (clickIfPresent(".volumeBtn.volumeLevel")) {
        e.preventDefault();
      }
      return;
    }
    if (k === "c") {
      if (typingComments) return;
      if (clickIfPresent("#btnCC")) {
        e.preventDefault();
      }
      return;
    }
    if (k === "r") {
      if (typingComments) return;
      if (clickIfPresent("#btnRandom")) {
        e.preventDefault();
      }
      return;
    }
    if (k === "[") {
      if (typingComments) return;
      if (clickIfPresent(".speedBtn.speedDown")) {
        e.preventDefault();
      }
      return;
    }
    if (k === "]") {
      if (typingComments) return;
      if (clickIfPresent(".speedBtn.speedUp")) {
        e.preventDefault();
      }
      return;
    }
    if (k === "s") {
      if (typingComments) return;
      if (clickIfPresent("#btnSleep")) {
        e.preventDefault();
      }
      return;
    }
    if (k === "t") {
      if (typingComments) return;
      if (clickIfPresent("#btnTheme")) {
        e.preventDefault();
      }
      return;
    }
    if (k === "g") {
      if (typingComments) return;
      const opened = clickIfVisible(".guideNowBlock") || clickIfVisible("#btnCloseGuide");
      if (opened) {
        e.preventDefault();
      }
      return;
    }
    if (k === "d") {
      if (typingComments) return;
      if (clickIfPresent("#btnDetails")) {
        e.preventDefault();
      }
      return;
    }
    if (k === "y") {
      if (typingComments) return;
      if (clickIfPresent("#btnHistory")) {
        e.preventDefault();
      }
      return;
    }
    if (k === "f") {
      if (typingComments) return;
      toggleFullscreen();
      e.preventDefault();
      return;
    }
  };

  const onKeyUp = (e) => {
    if (e.key === "Alt") {
      if (hintMode === "alt") {
        altHeld = false;
        hintMode = null;
        stopHints();
        e.preventDefault();
      }
      return;
    }
  };

  const onBlur = () => {
    altHeld = false;
    hintMode = null;
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
    cleanupMediaSession?.();
  };
}
