import { html, useEffect, useMemo, useRef, useSignal, useSignalEffect } from "../runtime/vendor.js";
import { GuidePanel } from "../ui/guide.js";
import { DetailsPanel } from "../ui/details.js";
import { HistoryPanel } from "../ui/history.js";
import { StatusToast } from "../ui/status_toast.js";
import { SubtitleBox } from "../ui/subtitle_box.js";
import { usePanelTakeover } from "../ui/takeover/panel_takeover.js";
import { CaptionsTakeover } from "../ui/takeover/captions_takeover.js";
import { ThemeTakeover } from "../ui/takeover/theme_takeover.js";
import { SleepTakeover } from "../ui/takeover/sleep_takeover.js";
import { RandomTakeover } from "../ui/takeover/random_takeover.js";
import { SkipTakeover } from "../ui/takeover/skip_takeover.js";
import { SpeedTakeover } from "../ui/takeover/speed_takeover.js";
import { AudioTakeover } from "../ui/takeover/audio_takeover.js";
import { MoonIcon } from "../ui/icons.js";
import { useLongPress } from "../ui/long_press.js";
import { installControls } from "./controls.js";

export function App({ env, log, sources, player, history }) {
  const guideOpen = useSignal(false);
  const detailsOpen = useSignal(false);
  const historyOpen = useSignal(false);
  const toast = useSignal({ show: false, msg: "", level: "info", ms: 2200 });
  const panelTakeover = usePanelTakeover({ defaultIdleMs: 5000 });
  const scrubPreview = useSignal({ show: false, label: "", pct: 50 });
  const theme = useSignal("modern");

  const videoRef = useRef(null);
  const guideBarRef = useRef(null);
  const progressRef = useRef(null);
  const durationRef = useRef(NaN);

  useEffect(() => {
    const cleanup = installControls();
    return () => cleanup?.();
  }, []);

  useEffect(() => {
    const el = progressRef.current;
    if (!el) return;
    const updatePos = (clientX) => {
      const r = el.getBoundingClientRect();
      const pct = Math.min(100, Math.max(0, ((clientX - r.left) / r.width) * 100));
      el.style.setProperty("--scrubber-x", `${pct}%`);
      const dur = durationRef.current;
      if (Number.isFinite(dur) && dur > 0) {
        const t = (dur * pct) / 100;
        scrubPreview.value = { show: true, label: player.fmtTime(t), pct };
      } else {
        scrubPreview.value = { show: false, label: "", pct };
      }
    };
    const onMove = (e) => {
      const x = e.touches ? e.touches[0]?.clientX : e.clientX;
      if (x != null) updatePos(x);
    };
    const onLeave = () => {
      scrubPreview.value = { ...scrubPreview.value, show: false };
      el.style.removeProperty("--scrubber-x");
    };
    el.addEventListener("mousemove", onMove, { passive: true });
    el.addEventListener("mouseleave", onLeave);
    el.addEventListener("mousedown", onMove, { passive: true });
    el.addEventListener("touchstart", onMove, { passive: true });
    el.addEventListener("touchmove", onMove, { passive: true });
    el.addEventListener("touchend", onLeave);
    return () => {
      el.removeEventListener("mousemove", onMove);
      el.removeEventListener("mouseleave", onLeave);
      el.removeEventListener("mousedown", onMove);
      el.removeEventListener("touchstart", onMove);
      el.removeEventListener("touchmove", onMove);
      el.removeEventListener("touchend", onLeave);
    };
  }, []);

  useEffect(() => {
    if (videoRef.current) {
      player.attachVideo(videoRef.current);
      log.info("Video ready");
    }
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
      const isIdle = Date.now() > idleTo;
      if (isIdle) el.classList.add("idle");
      else el.classList.remove("idle");
      if (isIdle && !wasIdle) panelTakeover.close();
      wasIdle = isIdle;
      requestAnimationFrame(tick);
    };
    tick();
    ["mousemove", "mousedown", "keydown", "touchstart"].forEach((ev) => document.addEventListener(ev, reset, { passive: true }));
    return () => {
      ["mousemove", "mousedown", "keydown", "touchstart"].forEach((ev) => document.removeEventListener(ev, reset));
    };
  }, []);

  const cur = player.current.value;
  const pb = player.playback.value;
  const cap = player.captions.value;
  const loading = player.loading.value;
  const sleep = player.sleep.value;
  const audioBlocked = player.audioBlocked.value;
  const skip = player.skip?.value || { back: 10, fwd: 30 };
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
        id: "sleep",
        idleMs: 7000,
        render: (takeover) => html`<${SleepTakeover} player=${player} takeover=${takeover} />`,
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

  const onSeekBarClick = (ev, el) => {
    if (!el) return;
    const r = el.getBoundingClientRect();
    const x = ev.clientX - r.left;
    const pct01 = Math.min(1, Math.max(0, x / r.width));
    player.seekToPct(pct01);
  };

  return html`
    <div class="app-inner">
      <${StatusToast} toast=${toast} />
      <div class="player ${cap.showing ? "custom-captions" : ""}" id="player">
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
          class=${"progress" + (progressTime.crampedLeft ? " progress-crampedLeft" : progressTime.crampedRight ? " progress-crampedRight" : "")}
          id="progress"
          ref=${progressRef}
          title="Seek"
          style=${{ "--progress-pct": `${pct}%` }}
          onClick=${(e) => { e.stopPropagation(); onSeekBarClick(e, e.currentTarget); }}
        >
          <div class="progressFill" id="progressFill" style=${{ width: `${pct}%` }}></div>
          <div
            class=${"scrubPreview" +
              (scrubPreview.value.show ? " show" : "") +
              (scrubPreview.value.pct < 12 ? " scrubPreview-left" : scrubPreview.value.pct > 88 ? " scrubPreview-right" : "")}
            style=${{ left: `${scrubPreview.value.pct}%` }}
            aria-hidden=${scrubPreview.value.show ? "false" : "true"}
          >
            ${scrubPreview.value.label}
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
                  <button id="btnPlay" class="guideBtn" title="Play/Pause" data-navitem="1" data-keyhint="K — Play" onClick=${() => player.togglePlay()}>
                    ${pb.paused ? "▶" : "❚❚"}
                  </button>
                  <div
                    class=${"volumeControl" + (audioBlocked ? " audioBlocked" : "") + (pb.muted && !audioBlocked ? " muted" : "")}
                    title=${audioBlocked ? "Click video or Play to enable sound (browser restriction)" : pb.muted ? "Muted" : "Volume"}
                  >
                    <button class="volumeBtn volumeUp" title="Volume up" data-navitem="1" onClick=${() => player.volumeUp()}>+</button>
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
                    <button class="volumeBtn volumeDown" title="Volume down" data-navitem="1" onClick=${() => player.volumeDown()}>−</button>
                    ${audioBlocked ? html`<span class="volumeHint">Tap to unmute</span>` : ""}
                  </div>
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
                      title="Sleep timer"
                      data-navitem="1"
                      data-keyhint="S — Sleep"
                      style=${{ "--lp": `${Math.round(sleepLongPress.progress.value * 100)}%` }}
                      onPointerDown=${sleepLongPress.onPointerDown}
                      onPointerUp=${sleepLongPress.onPointerUp}
                      onPointerCancel=${sleepLongPress.onPointerCancel}
                      onClick=${(e) => {
                        e.stopPropagation();
                        if (sleepLongPress.consumeClick()) return;
                        if (sleep.active) return player.clearSleepTimer();
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
