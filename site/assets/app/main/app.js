import { html, useEffect, useMemo, useRef, useSignal, useSignalEffect } from "../runtime/vendor.js";
import { GuidePanel } from "../ui/guide.js";
import { DetailsPanel } from "../ui/details.js";
import { HistoryPanel } from "../ui/history.js";
import { StatusToast } from "../ui/status_toast.js";
import { SubtitleBox } from "../ui/subtitle_box.js";
import { usePanelTakeover } from "../ui/takeover/panel_takeover.js";
import { CaptionsTakeover } from "../ui/takeover/captions_takeover.js";
import { ThemeTakeover } from "../ui/takeover/theme_takeover.js";
import { SleepSettingsTakeover, SleepTakeover } from "../ui/takeover/sleep_takeover.js";
import { RandomTakeover } from "../ui/takeover/random_takeover.js";
import { SkipTakeover } from "../ui/takeover/skip_takeover.js";
import { SpeedTakeover } from "../ui/takeover/speed_takeover.js";
import { AudioTakeover } from "../ui/takeover/audio_takeover.js";
import { ChaptersNavSettingsTakeover, ChaptersNavTakeover } from "../ui/takeover/chapters_nav_takeover.js";
import { ShareTakeover } from "../ui/takeover/share_takeover.js";
import { ShuffleTakeover } from "../ui/takeover/shuffle_takeover.js";
import { ExitFullscreenIcon, FullscreenIcon, MoonIcon, MuteIcon, PauseIcon, PlayIcon, ShareIcon, ShuffleIcon } from "../ui/icons.js";
import { useLongPress } from "../ui/long_press.js";
import { installControls } from "./controls.js";
import { setRouteInUrl } from "./route.js";

function chapterIndexAt(chapters, tSec) {
  const t = Number(tSec) || 0;
  let idx = -1;
  for (let i = 0; i < (chapters || []).length; i++) {
    const ct = Number(chapters[i]?.t) || 0;
    if (ct <= t) idx = i;
    else break;
  }
  return idx;
}

function chapterNameAt(chapters, tSec) {
  const idx = chapterIndexAt(chapters, tSec);
  const ch = idx >= 0 ? chapters[idx] : null;
  return ch?.name ? String(ch.name) : "";
}

export function App({ env, log, sources, player, history }) {
  const guideOpen = useSignal(false);
  const detailsOpen = useSignal(false);
  const historyOpen = useSignal(false);
  const isFullscreen = useSignal(false);
  const toast = useSignal({ show: false, msg: "", level: "info", ms: 2200 });
  const panelTakeover = usePanelTakeover({ defaultIdleMs: 5000 });
  const scrubPreview = useSignal({ show: false, label: "", pct: 50, t: 0 });
  const theme = useSignal("modern");

  const videoRef = useRef(null);
  const playerFrameRef = useRef(null);
  const guideBarRef = useRef(null);
  const progressRef = useRef(null);
  const durationRef = useRef(NaN);
  const seekFxLeftRef = useRef(null);
  const seekFxRightRef = useRef(null);
  const seekFxHideRef = useRef(null);
  const uiIdleToRef = useRef(null);
  const uiIdleRef = useRef(false);
  const appRootRef = useRef(null);
  const uiIdleDepsRef = useRef({
    paused: null,
    ended: null,
    loading: null,
    guideOpen: null,
    detailsOpen: null,
    historyOpen: null,
  });

  const UI_IDLE_MS = 3200;
  const setUiIdle = (next) => {
    const appEl = appRootRef.current || document.getElementById("app");
    if (!appEl) return;
    if (uiIdleRef.current === next) return;
    uiIdleRef.current = next;
    appEl.classList.toggle("uiIdle", next);
    if (next) {
      // Blur focus so we don't hide a focused control (keyboard / remote UX).
      const a = document.activeElement;
      if (a && a !== document.body) {
        try {
          if (appEl.contains(a) && typeof a.blur === "function") a.blur();
        } catch {}
      }
      // Ensure the progress hover state can't get "stuck" on touch browsers.
      try {
        const el = progressRef.current;
        if (el) {
          el.style.removeProperty("--scrubber-x");
          el.style.removeProperty("--scrub-pct");
        }
      } catch {}
      scrubPreview.value = { ...scrubPreview.value, show: false };
      panelTakeover.close();
    }
  };

  const canUiIdleNow = () => {
    const pb = player.playback.value;
    const loading = !!player.loading.value;
    const playing = !loading && !pb.paused && !pb.ended;
    if (!playing) return false;
    if (guideOpen.value || detailsOpen.value || historyOpen.value) return false;
    if (progressRef.current?.classList?.contains("scrubbing")) return false;
    return true;
  };

  const clearUiIdleTimer = () => {
    if (uiIdleToRef.current) {
      clearTimeout(uiIdleToRef.current);
      uiIdleToRef.current = null;
    }
  };

  const scheduleUiIdle = () => {
    clearUiIdleTimer();
    if (!canUiIdleNow()) {
      setUiIdle(false);
      return;
    }
    setUiIdle(false);
    uiIdleToRef.current = setTimeout(() => {
      uiIdleToRef.current = null;
      if (canUiIdleNow()) setUiIdle(true);
    }, UI_IDLE_MS);
  };

  const wakeUi = () => {
    setUiIdle(false);
    scheduleUiIdle();
  };

  useEffect(() => {
    const cleanup = installControls();
    return () => cleanup?.();
  }, []);

  // Global UI idle: while playing, hide chrome (except mute + thin progress bar) after a short delay.
  useEffect(() => {
    appRootRef.current = document.getElementById("app");

    const onActivity = () => wakeUi();
    const evs = [
      "mousemove",
      "mousedown",
      "mouseup",
      "keydown",
      "touchstart",
      "touchmove",
      "touchend",
      "touchcancel",
      "pointerdown",
      "pointermove",
      "pointerup",
      "pointercancel",
      "wheel",
    ];
    evs.forEach((ev) => document.addEventListener(ev, onActivity, { passive: true }));
    scheduleUiIdle();
    return () => {
      clearUiIdleTimer();
      evs.forEach((ev) => document.removeEventListener(ev, onActivity));
    };
  }, []);

  // Reschedule when playback / overlays change (e.g. ended, buffering, panels opening).
  useSignalEffect(() => {
    const pb = player.playback.value;
    const next = {
      paused: !!pb.paused,
      ended: !!pb.ended,
      loading: !!player.loading.value,
      guideOpen: !!guideOpen.value,
      detailsOpen: !!detailsOpen.value,
      historyOpen: !!historyOpen.value,
    };
    const prev = uiIdleDepsRef.current;
    const changed =
      next.paused !== prev.paused ||
      next.ended !== prev.ended ||
      next.loading !== prev.loading ||
      next.guideOpen !== prev.guideOpen ||
      next.detailsOpen !== prev.detailsOpen ||
      next.historyOpen !== prev.historyOpen;
    if (!changed) return;
    uiIdleDepsRef.current = next;
    scheduleUiIdle();
  });

  useEffect(() => {
    const onFs = () => {
      isFullscreen.value = !!document.fullscreenElement;
    };
    document.addEventListener("fullscreenchange", onFs);
    onFs();
    return () => document.removeEventListener("fullscreenchange", onFs);
  }, []);

  useEffect(() => {
    const el = progressRef.current;
    if (!el) return;
    let scrubbing = false;
    let pointerId = null;
    let rafId = null;
    let lastPct = null;
    let lastFromScrub = false;
    let hideTo = null;

    const pctFromClientX = (clientX) => {
      const r = el.getBoundingClientRect();
      const w = Math.max(1, r.width || 1);
      return Math.min(100, Math.max(0, ((clientX - r.left) / w) * 100));
    };

    const setPreview = (pct, { fromScrub = false } = {}) => {
      el.style.setProperty("--scrubber-x", `${pct}%`);
      const dur = durationRef.current;
      if (Number.isFinite(dur) && dur > 0) {
        const t = (dur * pct) / 100;
        scrubPreview.value = { show: true, label: player.fmtTime(t), pct, t };
      } else {
        scrubPreview.value = { show: false, label: "", pct, t: 0 };
      }
      if (fromScrub) el.style.setProperty("--scrub-pct", `${pct}%`);
      else el.style.removeProperty("--scrub-pct");
    };

    const hidePreview = () => {
      scrubPreview.value = { ...scrubPreview.value, show: false };
      el.style.removeProperty("--scrubber-x");
      el.style.removeProperty("--scrub-pct");
    };

    const schedule = (pct, { fromScrub = false } = {}) => {
      lastPct = pct;
      lastFromScrub = fromScrub;
      if (rafId) return;
      rafId = requestAnimationFrame(() => {
        rafId = null;
        const p = Number(lastPct);
        if (!Number.isFinite(p)) return;
        setPreview(p, { fromScrub: lastFromScrub });
        if (lastFromScrub) player.seekToPct(p / 100);
      });
    };

    const onPointerDown = (e) => {
      if (e.button != null && e.button !== 0) return;
      scrubbing = true;
      pointerId = e.pointerId;
      el.classList.add("scrubbing");
      el.dataset.scrub = e.pointerType === "touch" || e.pointerType === "pen" ? "touch" : "mouse";
      try {
        el.setPointerCapture(pointerId);
      } catch {}
      if (hideTo) clearTimeout(hideTo);
      hideTo = null;
      schedule(pctFromClientX(e.clientX), { fromScrub: true });
      try {
        e.preventDefault();
      } catch {}
    };

    const onPointerMove = (e) => {
      if (!scrubbing && e.pointerType === "mouse") {
        schedule(pctFromClientX(e.clientX), { fromScrub: false });
        return;
      }
      if (!scrubbing || pointerId == null || e.pointerId !== pointerId) return;
      schedule(pctFromClientX(e.clientX), { fromScrub: true });
    };

    const finish = () => {
      scrubbing = false;
      pointerId = null;
      el.classList.remove("scrubbing");
      el.dataset.scrub = "";
      if (hideTo) clearTimeout(hideTo);
      hideTo = setTimeout(() => hidePreview(), 900);
    };

    const onPointerUp = (e) => {
      if (!scrubbing || pointerId == null || e.pointerId !== pointerId) return;
      schedule(pctFromClientX(e.clientX), { fromScrub: true });
      try {
        el.releasePointerCapture(pointerId);
      } catch {}
      finish();
    };

    const onPointerCancel = () => {
      if (!scrubbing) return;
      finish();
    };

    const onLeave = () => {
      if (scrubbing) return;
      if (hideTo) clearTimeout(hideTo);
      hideTo = setTimeout(() => hidePreview(), 250);
    };

    el.addEventListener("pointerdown", onPointerDown);
    el.addEventListener("pointermove", onPointerMove);
    el.addEventListener("pointerup", onPointerUp);
    el.addEventListener("pointercancel", onPointerCancel);
    el.addEventListener("pointerleave", onLeave);
    return () => {
      if (rafId) cancelAnimationFrame(rafId);
      if (hideTo) clearTimeout(hideTo);
      el.removeEventListener("pointerdown", onPointerDown);
      el.removeEventListener("pointermove", onPointerMove);
      el.removeEventListener("pointerup", onPointerUp);
      el.removeEventListener("pointercancel", onPointerCancel);
      el.removeEventListener("pointerleave", onLeave);
    };
  }, []);

  useEffect(() => {
    const videoEl = videoRef.current;
    const frameEl = playerFrameRef.current;
    if (!videoEl) return;
    player.attachVideo(videoEl);
    log.info("Video ready");

    if (!frameEl) return;

    // Double-tap seek on the left/right half of the video frame (mobile UX).
    // Uses configured skip values and suppresses the video's normal click-to-toggle behavior.
    const TAP_MAX_MS = 260;
    const DOUBLE_TAP_MS = 340;
    const MOVE_MAX_PX = 18;
    const SIDE_ZONE_PCT = 0.33; // left/right third; center area preserves normal click-to-toggle
    let down = null;
    let lastTap = { t: 0, side: null };
    let suppressClickUntil = 0;

    const flashSeek = (side, seconds) => {
      const el = side === "left" ? seekFxLeftRef.current : seekFxRightRef.current;
      if (!el) return;
      const label = el.querySelector?.(".seekTapFxLabel");
      if (label) label.textContent = `${side === "left" ? "−" : "+"}${Math.round(Math.abs(seconds))}s`;

      el.classList.remove("show");
      // Restart animation.
      // eslint-disable-next-line no-unused-expressions
      el.offsetWidth;
      el.classList.add("show");

      if (seekFxHideRef.current) clearTimeout(seekFxHideRef.current);
      seekFxHideRef.current = setTimeout(() => {
        try {
          el.classList.remove("show");
        } catch {}
      }, 420);
    };

    const shouldHandle = (e) => {
      // Ignore interactions with the seek bar.
      const t = e?.target;
      if (t?.closest?.(".progress")) return false;
      // Only touch-like pointers should get double-tap seek.
      if (e?.pointerType && e.pointerType !== "touch" && e.pointerType !== "pen") return false;
      return true;
    };

    const onPointerDown = (e) => {
      if (!shouldHandle(e)) return;
      down = { t: performance.now(), x: e.clientX, y: e.clientY };
    };

    const onPointerUp = (e) => {
      if (!shouldHandle(e)) return;
      if (!down) return;
      const dt = performance.now() - down.t;
      const dx = (e.clientX || 0) - down.x;
      const dy = (e.clientY || 0) - down.y;
      down = null;
      if (dt > TAP_MAX_MS) return;
      if (Math.hypot(dx, dy) > MOVE_MAX_PX) return;

      const r = videoEl.getBoundingClientRect();
      if (!r.width || !r.height) return;
      const x = (e.clientX || 0) - r.left;
      const pct = x / r.width;
      if (pct > SIDE_ZONE_PCT && pct < 1 - SIDE_ZONE_PCT) {
        // Center zone: don't interfere with the existing click-to-toggle behavior.
        lastTap = { t: 0, side: null };
        suppressClickUntil = 0;
        return;
      }
      const side = pct <= 0.5 ? "left" : "right";

      const now = performance.now();
      if (now - lastTap.t <= DOUBLE_TAP_MS && lastTap.side === side) {
        lastTap = { t: 0, side: null };
        const cfg = player.skip?.value || { back: 10, fwd: 30 };
        const seconds = side === "left" ? -Math.max(0, Number(cfg.back) || 10) : Math.max(0, Number(cfg.fwd) || 30);
        suppressClickUntil = Date.now() + 650;
        player.seekBy(seconds);
        flashSeek(side, seconds);
      } else {
        lastTap = { t: now, side };
        // Suppress the underlying click-to-toggle until we know whether this is a double-tap.
        suppressClickUntil = Date.now() + DOUBLE_TAP_MS + 80;
      }
    };

    const onPointerCancel = () => {
      down = null;
    };

    const onClickCapture = (e) => {
      if (Date.now() < suppressClickUntil) {
        e.preventDefault();
        e.stopPropagation?.();
        e.stopImmediatePropagation?.();
      }
    };

    frameEl.addEventListener("pointerdown", onPointerDown, { passive: true });
    frameEl.addEventListener("pointerup", onPointerUp, { passive: true });
    frameEl.addEventListener("pointercancel", onPointerCancel);
    frameEl.addEventListener("click", onClickCapture, true);

    return () => {
      frameEl.removeEventListener("pointerdown", onPointerDown);
      frameEl.removeEventListener("pointerup", onPointerUp);
      frameEl.removeEventListener("pointercancel", onPointerCancel);
      frameEl.removeEventListener("click", onClickCapture, true);
      if (seekFxHideRef.current) clearTimeout(seekFxHideRef.current);
      seekFxHideRef.current = null;
    };
  }, []);

  // Theme
  useEffect(() => {
    const THEME_KEY = "vodcasts_theme_v1";
    const htmlRoot = document.getElementById("htmlRoot") || document.documentElement;
    const savedTheme = localStorage.getItem(THEME_KEY);
    const t = savedTheme || htmlRoot?.dataset?.theme || "modern";
    theme.value = t;
    if (htmlRoot) htmlRoot.dataset.theme = t;
  }, []);

  const setTheme = (next) => {
    const THEME_KEY = "vodcasts_theme_v1";
    const htmlRoot = document.getElementById("htmlRoot") || document.documentElement;
    const t = next || "modern";
    theme.value = t;
    if (htmlRoot) htmlRoot.dataset.theme = t;
    try {
      localStorage.setItem(THEME_KEY, t);
    } catch {}
  };

  const toggleTheme = () => {
    const cur = theme.value || "modern";
    setTheme(cur === "modern" ? "dos" : "modern");
  };

  // Escape closes panels.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== "Escape") return;
      if (document.fullscreenElement) {
        try {
          document.exitFullscreen?.();
        } catch {}
      }
      if (guideOpen.value) guideOpen.value = false;
      if (detailsOpen.value) detailsOpen.value = false;
      if (historyOpen.value) historyOpen.value = false;
      if (panelTakeover.active.value) panelTakeover.close();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  // Side panels auto-close after 10s of non-usage (no interaction within the panel).
  const PANEL_IDLE_MS = 10000;
  const panelIds = ["guidePanel", "detailsPanel", "historyPanel"];
  useSignalEffect(() => {
    const anyOpen = guideOpen.value || detailsOpen.value || historyOpen.value;
    if (!anyOpen) return;
    let t = setTimeout(() => {
      if (guideOpen.value) guideOpen.value = false;
      if (detailsOpen.value) detailsOpen.value = false;
      if (historyOpen.value) historyOpen.value = false;
    }, PANEL_IDLE_MS);
    const reset = (e) => {
      const inside = panelIds.some((id) => {
        const el = document.getElementById(id);
        return el && el.contains(e.target);
      });
      if (inside) {
        clearTimeout(t);
        t = setTimeout(() => {
          if (guideOpen.value) guideOpen.value = false;
          if (detailsOpen.value) detailsOpen.value = false;
          if (historyOpen.value) historyOpen.value = false;
        }, PANEL_IDLE_MS);
      }
    };
    const evs = ["mousemove", "mousedown", "keydown", "scroll", "touchstart", "touchmove"];
    evs.forEach((ev) => document.addEventListener(ev, reset, { passive: true }));
    return () => {
      clearTimeout(t);
      evs.forEach((ev) => document.removeEventListener(ev, reset));
    };
  });

  // Brief status toast (mirrors the latest log entry).
  useSignalEffect(() => {
    const list = log.entries.value || [];
    const last = list[list.length - 1];
    if (!last) return;
    toast.value = { show: true, msg: last.msg, level: last.level || "info", ms: 2200 };
  });

  // Guide bar idle fade.
  useEffect(() => {
    const el = guideBarRef.current;
    if (!el) return;
    const GUIDE_IDLE_MS = 3000;
    let idleTo = Date.now() + GUIDE_IDLE_MS;
    let wasIdle = false;
    const reset = () => {
      idleTo = Date.now() + GUIDE_IDLE_MS;
      el.classList.remove("idle");
      wasIdle = false;
    };
    const tick = () => {
      const isIdle = canUiIdleNow() && Date.now() > idleTo;
      if (isIdle) el.classList.add("idle");
      else el.classList.remove("idle");
      if (isIdle && !wasIdle) {
        // If the focused element is inside the guide bar, blur it so we don't hide a focused control.
        const a = document.activeElement;
        if (a && a !== document.body) {
          try {
            if (el.contains(a) && typeof a.blur === "function") a.blur();
          } catch {}
        }
        panelTakeover.close();
      }
      wasIdle = isIdle;
      requestAnimationFrame(tick);
    };
    tick();
    ["mousemove", "mousedown", "keydown", "touchstart"].forEach((ev) => document.addEventListener(ev, reset, { passive: true }));
    return () => {
      ["mousemove", "mousedown", "keydown", "touchstart"].forEach((ev) => document.removeEventListener(ev, reset));
    };
  }, []);

  // Keep the URL shareable (feed + episode) as playback changes.
  useSignalEffect(() => {
    const s = player.current.value.source?.id;
    const e = player.current.value.episode?.slug;
    if (!s) return;
    setRouteInUrl({ feed: s, ep: e }, { replace: true });
  });

  const cur = player.current.value;
  const pb = player.playback.value;
  const cap = player.captions.value;
  const loading = player.loading.value;
  const sleep = player.sleep.value;
  const shuffle = player.shuffle?.value || { active: false, label: "", intervalIdx: 4, changeFeed: true, changeEpisode: true, changeTime: true };
  const audioBlocked = player.audioBlocked.value;
  const skip = player.skip?.value || { back: 10, fwd: 30 };
  const chaptersRaw = player.chapters?.value || [];
  const chapters = useMemo(() => {
    const list = Array.isArray(chaptersRaw) ? chaptersRaw.slice() : [];
    list.sort((a, b) => (Number(a?.t) || 0) - (Number(b?.t) || 0));
    return list;
  }, [chaptersRaw]);
  const hasChapters = chapters.length > 0;
  const ccLongPress = useLongPress({
    ms: 500,
    enabled: cap.available,
    onLongPress: () => {
      if (player.captions.value.available && !player.captions.value.showing) player.toggleCaptions();
      panelTakeover.open({
        id: "captions",
        idleMs: 5000,
        render: (takeover) => html`<${CaptionsTakeover} player=${player} takeover=${takeover} />`,
      });
    },
  });

  const seekBackLongPress = useLongPress({
    ms: 500,
    enabled: true,
    onLongPress: () => {
      panelTakeover.open({
        id: "skip",
        idleMs: 5000,
        render: (takeover) => html`<${SkipTakeover} player=${player} takeover=${takeover} />`,
      });
    },
  });
  const seekFwdLongPress = useLongPress({
    ms: 500,
    enabled: true,
    onLongPress: () => {
      panelTakeover.open({
        id: "skip",
        idleMs: 5000,
        render: (takeover) => html`<${SkipTakeover} player=${player} takeover=${takeover} />`,
      });
    },
  });

  const sleepLongPress = useLongPress({
    ms: 500,
    enabled: true,
    onLongPress: () => {
      panelTakeover.open({
        id: "sleep_settings",
        idleMs: 7000,
        render: (takeover) => html`<${SleepSettingsTakeover} takeover=${takeover} />`,
      });
    },
  });

  const randomLongPress = useLongPress({
    ms: 500,
    enabled: true,
    onLongPress: () => {
      panelTakeover.open({
        id: "random",
        idleMs: 7000,
        render: (takeover) => html`<${RandomTakeover} player=${player} takeover=${takeover} />`,
      });
    },
  });

  const shuffleLongPress = useLongPress({
    ms: 500,
    enabled: true,
    onLongPress: () => {
      panelTakeover.open({
        id: "shuffle",
        idleMs: 9000,
        render: (takeover) => html`<${ShuffleTakeover} player=${player} takeover=${takeover} />`,
      });
    },
  });

  const themeLongPress = useLongPress({
    ms: 500,
    enabled: true,
    onLongPress: () => {
      panelTakeover.open({
        id: "theme",
        idleMs: 7000,
        render: (takeover) => html`<${ThemeTakeover} theme=${theme.value} setTheme=${setTheme} takeover=${takeover} />`,
      });
    },
  });

  const speedLongPress = useLongPress({
    ms: 500,
    enabled: true,
    onLongPress: () => {
      panelTakeover.open({
        id: "speed",
        idleMs: 9000,
        render: (takeover) => html`<${SpeedTakeover} player=${player} takeover=${takeover} />`,
      });
    },
  });

  const audioLongPress = useLongPress({
    ms: 500,
    enabled: true,
    onLongPress: () => {
      panelTakeover.open({
        id: "audio",
        idleMs: 9000,
        render: (takeover) => html`<${AudioTakeover} takeover=${takeover} />`,
      });
    },
  });

  const navLongPress = useLongPress({
    ms: 500,
    enabled: hasChapters,
    onLongPress: () => {
      panelTakeover.open({
        id: "nav_settings",
        idleMs: 7000,
        render: (takeover) => html`<${ChaptersNavSettingsTakeover} takeover=${takeover} />`,
      });
    },
  });

  const rateLabel = useMemo(() => {
    const r = Number(pb.rate) > 0 ? Number(pb.rate) : 1;
    return (Math.round(r * 100) / 100).toString().replace(/\.0+$/, "").replace(/(\.\d)0$/, "$1") + "x";
  }, [pb.rate]);

  useEffect(() => {
    durationRef.current = pb.duration;
  }, [pb.duration]);

  useEffect(() => {
    if (!cur?.source?.id) return;
    const s = cur.source.title || cur.source.id;
    const e = cur.episode?.title ? ` — ${cur.episode.title}` : "";
    log.info(`Now: ${s}${e}`);
  }, [cur?.source?.id, cur?.episode?.id]);

  const srcTitle = cur.source?.title || cur.source?.id || "—";
  const epTitle = cur.episode?.title || "—";
  const pct = useMemo(() => {
    const dur = pb.duration;
    if (!Number.isFinite(dur) || dur <= 0) return 0;
    return Math.min(100, (pb.time / dur) * 100);
  }, [pb.time, pb.duration]);

  const progressTime = useMemo(() => {
    const curT = pb.time || 0;
    const dur = pb.duration;
    const passed = player.fmtTime(curT);
    const total = Number.isFinite(dur) && dur > 0 ? player.fmtTime(dur) : null;
    const remaining = total ? player.fmtTime(Math.max(0, dur - curT)) : null;
    const crampedLeft = total && pct < 15;
    const crampedRight = total && pct > 85;
    return { passed, total, remaining, crampedLeft, crampedRight };
  }, [pb.time, pb.duration, pct]);

  const chapterMarks = useMemo(() => {
    const dur = pb.duration;
    if (!Number.isFinite(dur) || dur <= 0) return [];
    return (chapters || [])
      .map((c, i) => {
        const t = Number(c?.t) || 0;
        const pct = (t / dur) * 100;
        return { i, t, name: String(c?.name || "Chapter"), pct: Math.min(100, Math.max(0, pct)) };
      })
      .filter((m) => Number.isFinite(m.pct));
  }, [pb.duration, chapters]);

  const hoveredChapter = scrubPreview.value.show ? chapterNameAt(chapters, scrubPreview.value.t) : "";
  const currentChapter = chapterNameAt(chapters, pb.time || 0);
  const chapterTitle = hoveredChapter || currentChapter || "";
  const currentChapterIdx = chapterIndexAt(chapters, pb.time || 0);

  return html`
    <div class="app-inner">
      <${StatusToast} toast=${toast} />
      <div class="player ${cap.showing ? "custom-captions" : ""}" id="player" ref=${playerFrameRef}>
        <video id="video" playsinline ref=${videoRef}></video>
        <div
          class=${"playPauseOverlay" + (pb.paused || loading ? " visible" : "")}
          onClick=${(e) => { e.stopPropagation(); if (!loading) player.togglePlay(); }}
          aria-hidden=${pb.paused || loading ? "false" : "true"}
        >
          ${loading
            ? html`
                <span class="playPauseIcon playPauseLoading">
                  <span class="loadingSpinner"></span>
                  <span class="loadingLabel">Loading…</span>
                </span>
              `
            : html`
                <span class="playPauseIcon">
                  <span class="iconPause">❚❚</span>
                  <span class="iconPlay">▶</span>
                </span>
              `}
        </div>
        <div
          class=${"muteIndicator" + (pb.muted ? " show" : "")}
          title=${audioBlocked ? "Sound blocked by browser (tap video or Play)" : "Muted"}
          aria-hidden=${pb.muted ? "false" : "true"}
        >
          <span class="muteIndicatorIcon"><${MuteIcon} /></span>
        </div>
        <div class="seekTapFx" aria-hidden="true">
          <div class="seekTapFxSide seekTapFxLeft" ref=${seekFxLeftRef}>
            <div class="seekTapFxChevrons">
              <span class="seekTapChevron"></span>
              <span class="seekTapChevron"></span>
            </div>
            <div class="seekTapFxLabel">−10s</div>
          </div>
          <div class="seekTapFxSide seekTapFxRight" ref=${seekFxRightRef}>
            <div class="seekTapFxLabel">+30s</div>
            <div class="seekTapFxChevrons">
              <span class="seekTapChevron"></span>
              <span class="seekTapChevron"></span>
            </div>
          </div>
        </div>
        <div
          class=${"progress" + (progressTime.crampedLeft ? " progress-crampedLeft" : progressTime.crampedRight ? " progress-crampedRight" : "")}
          id="progress"
          ref=${progressRef}
          title="Seek"
          style=${{ "--progress-pct": `${pct}%` }}
        >
          <div class="progressFill" id="progressFill" style=${{ width: `${pct}%` }}></div>
          ${chapterMarks.length
            ? html`
                <div class="progressMarks" aria-hidden="true">
                  ${chapterMarks.map((m) => {
                    const active = currentChapterIdx === m.i;
                    return html`<span class=${"progressMark" + (active ? " active" : "")} style=${{ left: `${m.pct}%` }} title=${m.name}></span>`;
                  })}
                </div>
              `
            : ""}
          <div class="progressThumb" aria-hidden="true"></div>
          <div class=${"progressChapterTitle" + (scrubPreview.value.show || !chapterTitle ? " hide" : "")} aria-hidden="true">
            ${chapterTitle}
          </div>
          <div
            class=${"scrubPreview" +
              (scrubPreview.value.show ? " show" : "") +
              (scrubPreview.value.pct < 12 ? " scrubPreview-left" : scrubPreview.value.pct > 88 ? " scrubPreview-right" : "")}
            style=${{ left: `${scrubPreview.value.pct}%` }}
            aria-hidden=${scrubPreview.value.show ? "false" : "true"}
          >
            <span class="scrubTime">${scrubPreview.value.label}</span>
            ${hoveredChapter ? html`<span class="scrubChapter">${hoveredChapter}</span>` : ""}
          </div>
          ${progressTime.total
            ? html`
                <div class="progressTimeLabels">
                  <span class="progressTimePassed">${progressTime.passed}</span>
                  <span class="progressTimeRemaining">${progressTime.remaining} / ${progressTime.total}</span>
                </div>
              `
            : ""}
        </div>
        <${SubtitleBox} player=${player} />
      </div>

      <div
        class="guideBar"
        id="guideBar"
        ref=${guideBarRef}
        onClick=${(e) => {
          e.stopPropagation();
        }}
      >
        <div class="guideBar-inner">
          ${panelTakeover.active.value
            ? panelTakeover.active.value.render?.(panelTakeover)
            : html`
                <div class="guideBar-row1">
                  <div
                    class=${"volumeControl" + (audioBlocked ? " audioBlocked" : "") + (pb.muted && !audioBlocked ? " muted" : "")}
                    title=${audioBlocked ? "Click video or Play to enable sound (browser restriction)" : pb.muted ? "Muted" : "Volume"}
                  >
                    <button class="volumeBtn volumeDown" title="Volume down" data-navitem="1" onClick=${() => player.volumeDown()}>−</button>
                    <button
                      class=${"volumeBtn volumeLevel" + (audioLongPress.pressing.value ? " longpressing" : "")}
                      data-state=${audioBlocked ? "blocked" : pb.muted ? "muted" : "on"}
                      title=${audioBlocked ? "Click video or Play to enable sound" : "Click to toggle mute (long-press: Audio settings)"}
                      data-navitem="1"
                      data-keyhint="M — Mute"
                      style=${{ "--lp": `${Math.round(audioLongPress.progress.value * 100)}%` }}
                      onPointerDown=${audioLongPress.onPointerDown}
                      onPointerUp=${audioLongPress.onPointerUp}
                      onPointerCancel=${audioLongPress.onPointerCancel}
                      onClick=${() => {
                        if (audioLongPress.consumeClick()) return;
                        player.toggleMute();
                      }}
                    >
                      ${audioBlocked ? "blocked" : pb.muted ? "M" : Math.round((pb.volume ?? 1) * 100)}
                    </button>
                    <button class="volumeBtn volumeUp" title="Volume up" data-navitem="1" onClick=${() => player.volumeUp()}>+</button>
                    ${audioBlocked ? html`<span class="volumeHint">Tap to unmute</span>` : ""}
                  </div>
                  <div
                    class="guideNowBlock"
                    title="Channels"
                    role="button"
                    tabIndex=${0}
                    data-navitem="1"
                    data-keyhint="G — Guide"
                    onKeyDown=${(e) => { if (e.key === "Enter") guideOpen.value = true; }}
                    onClick=${() => (guideOpen.value = true)}
                  >
                    <div class="guideChannel" id="guideChannel">${srcTitle}</div>
                    <div class="guideNow" id="guideNow">${epTitle}</div>
                  </div>
                  <button
                    id="btnPlay"
                    class="guideBtn"
                    title="Play/Pause"
                    aria-label=${pb.paused ? "Play" : "Pause"}
                    data-navitem="1"
                    data-keyhint="K — Play"
                    onClick=${() => player.togglePlay()}
                  >
                    <span class="guideBtnIcon">${pb.paused ? html`<${PlayIcon} size=${18} />` : html`<${PauseIcon} size=${18} />`}</span>
                  </button>
                  <button
                    id="btnSeekBack"
                    class=${"guideBtn guideBtnSeek" + (seekBackLongPress.pressing.value ? " longpressing" : "")}
                    title=${`Back ${skip.back}s (long-press to configure)`}
                    data-navitem="1"
                    data-keyhint="J — Back"
                    style=${{ "--lp": `${Math.round(seekBackLongPress.progress.value * 100)}%` }}
                    onPointerDown=${seekBackLongPress.onPointerDown}
                    onPointerUp=${seekBackLongPress.onPointerUp}
                    onPointerCancel=${seekBackLongPress.onPointerCancel}
                    onClick=${() => {
                      if (seekBackLongPress.consumeClick()) return;
                      player.seekBy(-Math.max(0, Number(player.skip?.value?.back) || skip.back || 10));
                    }}
                  >
                    −${Math.round(skip.back || 10)}
                  </button>
                  <button
                    id="btnSeekFwd"
                    class=${"guideBtn guideBtnSeek" + (seekFwdLongPress.pressing.value ? " longpressing" : "")}
                    title=${`Forward ${skip.fwd}s (long-press to configure)`}
                    data-navitem="1"
                    data-keyhint="L — Fwd"
                    style=${{ "--lp": `${Math.round(seekFwdLongPress.progress.value * 100)}%` }}
                    onPointerDown=${seekFwdLongPress.onPointerDown}
                    onPointerUp=${seekFwdLongPress.onPointerUp}
                    onPointerCancel=${seekFwdLongPress.onPointerCancel}
                    onClick=${() => {
                      if (seekFwdLongPress.consumeClick()) return;
                      player.seekBy(Math.max(0, Number(player.skip?.value?.fwd) || skip.fwd || 30));
                    }}
                  >
                    +${Math.round(skip.fwd || 30)}
                  </button>
                </div>
                <div class="guideBar-row2">
                  <button
                    id="btnRandom"
                    class=${"guideBtn" + (randomLongPress.pressing.value ? " longpressing" : "")}
                    title="Random (long-press for options)"
                    data-navitem="1"
                    data-keyhint="R — Random"
                    style=${{ "--lp": `${Math.round(randomLongPress.progress.value * 100)}%` }}
                    onPointerDown=${randomLongPress.onPointerDown}
                    onPointerUp=${randomLongPress.onPointerUp}
                    onPointerCancel=${randomLongPress.onPointerCancel}
                    onClick=${() => {
                      if (randomLongPress.consumeClick()) return;
                      player.playRandom();
                    }}
                  >
                    Random
                  </button>
                  <button
                    id="btnShuffle"
                    class=${"guideBtn guideBtnHasIcon guideBtnShuffle" + (shuffle.active ? " active" : "") + (shuffleLongPress.pressing.value ? " longpressing" : "")}
                    title=${shuffle.active ? `Shuffle on (next in ${shuffle.label || "soon"})` : "Shuffle (long-press: settings)"}
                    data-navitem="1"
                    data-keyhint="H — Shuffle"
                    style=${{ "--lp": `${Math.round(shuffleLongPress.progress.value * 100)}%` }}
                    onPointerDown=${shuffleLongPress.onPointerDown}
                    onPointerUp=${shuffleLongPress.onPointerUp}
                    onPointerCancel=${shuffleLongPress.onPointerCancel}
                    onClick=${() => {
                      if (shuffleLongPress.consumeClick()) return;
                      player.toggleShuffle?.();
                    }}
                  >
                    <span class="guideBtnIcon"><${ShuffleIcon} size=${16} /></span>
                    ${shuffle.active && shuffle.label ? html`<span class="guideBtnLabel">${shuffle.label}</span>` : ""}
                  </button>
                  <button
                    id="btnNav"
                    class=${"guideBtn" + (!hasChapters ? " disabled" : "") + (navLongPress.pressing.value ? " longpressing" : "")}
                    title=${hasChapters ? "Chapters navigation (long-press: settings)" : "No chapters for this episode"}
                    aria-disabled=${hasChapters ? "false" : "true"}
                    disabled=${!hasChapters}
                    data-navitem="1"
                    data-keyhint="N — Nav"
                    style=${{ "--lp": `${Math.round(navLongPress.progress.value * 100)}%` }}
                    onPointerDown=${navLongPress.onPointerDown}
                    onPointerUp=${navLongPress.onPointerUp}
                    onPointerCancel=${navLongPress.onPointerCancel}
                    onClick=${() => {
                      if (!hasChapters) {
                        log.warn("No chapters available for this episode.");
                        return;
                      }
                      if (navLongPress.consumeClick()) return;
                      panelTakeover.open({
                        id: "nav",
                        idleMs: 7000,
                        render: (takeover) => html`<${ChaptersNavTakeover} player=${player} takeover=${takeover} />`,
                      });
                    }}
                  >
                    Nav
                  </button>
                  <div class="speedControl" title="Playback speed">
                    <button class="speedBtn speedDown" title="Slower" data-navitem="1" onClick=${() => player.rateDown()}>−</button>
                    <button
                      class=${"speedBtn speedLevel" + (speedLongPress.pressing.value ? " longpressing" : "")}
                      title="Click to toggle 1× / last speed (long-press: edit steps)"
                      data-navitem="1"
                      data-keyhint="]/[ — Speed"
                      style=${{ "--lp": `${Math.round(speedLongPress.progress.value * 100)}%` }}
                      onPointerDown=${speedLongPress.onPointerDown}
                      onPointerUp=${speedLongPress.onPointerUp}
                      onPointerCancel=${speedLongPress.onPointerCancel}
                      onClick=${() => {
                        if (speedLongPress.consumeClick()) return;
                        player.toggleRate();
                      }}
                    >
                      ${rateLabel}
                    </button>
                    <button class="speedBtn speedUp" title="Faster" data-navitem="1" onClick=${() => player.rateUp()}>+</button>
                  </div>
                  <div class="guideBar-sleep">
                    <button
                      id="btnSleep"
                      class=${"guideBtn guideBtnHasIcon" + (sleepLongPress.pressing.value ? " longpressing" : "")}
                      title="Sleep timer (long-press: configure)"
                      data-navitem="1"
                      data-keyhint="S — Sleep"
                      style=${{ "--lp": `${Math.round(sleepLongPress.progress.value * 100)}%` }}
                      onPointerDown=${sleepLongPress.onPointerDown}
                      onPointerUp=${sleepLongPress.onPointerUp}
                      onPointerCancel=${sleepLongPress.onPointerCancel}
                      onClick=${(e) => {
                        e.stopPropagation();
                        if (sleepLongPress.consumeClick()) return;
                        panelTakeover.open({
                          id: "sleep",
                          idleMs: 7000,
                          render: (takeover) => html`<${SleepTakeover} player=${player} takeover=${takeover} />`,
                        });
                      }}
                    >
                      <span class="guideBtnIcon"><${MoonIcon} size=${16} /></span>
                      ${sleep.active && sleep.label ? html`<span class="guideBtnLabel">${sleep.label}</span>` : ""}
                    </button>
                  </div>
                  <button
                    id="btnCC"
                    class=${"guideBtn" + (cap.showing ? " active" : "") + (!cap.available ? " disabled" : "") + (ccLongPress.pressing.value ? " longpressing" : "")}
                    title=${cap.available ? "Subtitles (long-press for settings)" : "Subtitles unavailable"}
                    aria-label="Subtitles"
                    aria-disabled=${cap.available ? "false" : "true"}
                    disabled=${!cap.available}
                    data-navitem="1"
                    data-keyhint="C — CC"
                    style=${{ "--lp": `${Math.round(ccLongPress.progress.value * 100)}%` }}
                    onPointerDown=${ccLongPress.onPointerDown}
                    onPointerUp=${ccLongPress.onPointerUp}
                    onPointerCancel=${ccLongPress.onPointerCancel}
                    onClick=${() => {
                      if (!cap.available) {
                        log.warn("No captions available for this episode.");
                        return;
                      }
                      if (ccLongPress.consumeClick()) return;
                      player.toggleCaptions();
                    }}
                  >
                    CC
                  </button>
                  <button
                    id="btnTheme"
                    class=${"guideBtn" + (themeLongPress.pressing.value ? " longpressing" : "")}
                    title="Theme (long-press for options)"
                    data-navitem="1"
                    data-keyhint="T — Theme"
                    style=${{ "--lp": `${Math.round(themeLongPress.progress.value * 100)}%` }}
                    onPointerDown=${themeLongPress.onPointerDown}
                    onPointerUp=${themeLongPress.onPointerUp}
                    onPointerCancel=${themeLongPress.onPointerCancel}
                    onClick=${() => {
                      if (themeLongPress.consumeClick()) return;
                      toggleTheme();
                    }}
                  >
                    Theme
                  </button>
                </div>
              `}
        </div>
      </div>

      <${GuidePanel} isOpen=${guideOpen} sources=${sources} player=${player} />
      <${HistoryPanel} isOpen=${historyOpen} history=${history} player=${player} />
      <${DetailsPanel} isOpen=${detailsOpen} env=${env} player=${player} log=${log} />

      <button
        id="btnHistory"
        class="cornerBtn cornerBtnLeft"
        title="History"
        data-navitem="1"
        data-keyhint="Y — History"
        onClick=${() => (historyOpen.value = !historyOpen.value)}
      >
        ☰
      </button>
      <button
        id="btnShare"
        class="cornerBtn cornerBtnShare"
        title="Share"
        data-navitem="1"
        data-keyhint="U — Share"
        onClick=${() => {
          panelTakeover.open({
            id: "share",
            idleMs: 8000,
            render: (takeover) => html`<${ShareTakeover} player=${player} log=${log} takeover=${takeover} />`,
          });
        }}
      >
        <${ShareIcon} />
      </button>
      <button
        id="btnFullscreen"
        class="cornerBtn cornerBtnMid"
        title="Fullscreen"
        data-navitem="1"
        data-keyhint="F — Fullscreen"
        onClick=${() => {
          const appEl = document.getElementById("app") || document.querySelector(".app") || document.documentElement;
          const videoEl = document.getElementById("video") || document.querySelector("video");
          if (!document.fullscreenElement) {
            try {
              appEl.requestFullscreen?.();
              return;
            } catch {
              try {
                videoEl?.requestFullscreen?.();
                return;
              } catch {}
              try {
                videoEl?.webkitEnterFullscreen?.();
              } catch {}
            }
          } else {
            try {
              document.exitFullscreen?.();
            } catch {}
          }
        }}
      >
        ${isFullscreen.value ? html`<${ExitFullscreenIcon} />` : html`<${FullscreenIcon} />`}
      </button>
      <button
        id="btnDetails"
        class="cornerBtn"
        title="Details"
        data-navitem="1"
        data-keyhint="D — Details"
        onClick=${() => (detailsOpen.value = !detailsOpen.value)}
      >
        ⋯
      </button>
    </div>
  `;
}
