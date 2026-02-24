import { html, useEffect, useMemo, useRef, useSignal, useSignalEffect } from "../runtime/vendor.js";
import { GuidePanel } from "../ui/guide.js";
import { DetailsPanel } from "../ui/details.js";
import { HistoryPanel } from "../ui/history.js";
import { StatusToast } from "../ui/status_toast.js";

export function App({ env, log, sources, player, history }) {
  const guideOpen = useSignal(false);
  const detailsOpen = useSignal(false);
  const historyOpen = useSignal(false);
  const sleepMenuOpen = useSignal(false);
  const toast = useSignal({ show: false, msg: "", level: "info", ms: 2200 });

  const videoRef = useRef(null);
  const guideBarRef = useRef(null);

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
    if (savedTheme) htmlRoot.dataset.theme = savedTheme;
  }, []);

  const toggleTheme = () => {
    const THEME_KEY = "vodcasts_theme_v1";
    const htmlRoot = document.getElementById("htmlRoot") || document.documentElement;
    const cur = htmlRoot?.dataset?.theme || "modern";
    const next = cur === "modern" ? "dos" : "modern";
    if (htmlRoot) htmlRoot.dataset.theme = next;
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch {}
  };

  // Escape closes panels.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== "Escape") return;
      if (guideOpen.value) guideOpen.value = false;
      if (detailsOpen.value) detailsOpen.value = false;
      if (historyOpen.value) historyOpen.value = false;
      if (sleepMenuOpen.value) sleepMenuOpen.value = false;
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  // Click outside closes the sleep menu.
  useEffect(() => {
    const onClick = () => {
      if (sleepMenuOpen.value) sleepMenuOpen.value = false;
    };
    document.addEventListener("click", onClick);
    return () => document.removeEventListener("click", onClick);
  }, []);

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
    const reset = () => {
      idleTo = Date.now() + GUIDE_IDLE_MS;
      el.classList.remove("idle");
    };
    const tick = () => {
      if (Date.now() > idleTo) el.classList.add("idle");
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
  const sleep = player.sleep.value;

  useEffect(() => {
    if (!cur?.source?.id) return;
    const s = cur.source.title || cur.source.id;
    const e = cur.episode?.title ? ` — ${cur.episode.title}` : "";
    log.info(`Now: ${s}${e}`);
  }, [cur?.source?.id, cur?.episode?.id]);

  const srcTitle = cur.source?.title || cur.source?.id || "—";
  const epTitle = cur.episode?.title || "—";
  const timeLabel = useMemo(() => {
    const curT = pb.time || 0;
    const dur = pb.duration;
    return `${player.fmtTime(curT)}${Number.isFinite(dur) ? " / " + player.fmtTime(dur) : ""}`;
  }, [pb.time, pb.duration, cur.episode?.id]);

  const pct = useMemo(() => {
    const dur = pb.duration;
    if (!Number.isFinite(dur) || dur <= 0) return 0;
    return Math.min(100, (pb.time / dur) * 100);
  }, [pb.time, pb.duration]);

  const onSeekBarClick = (ev, el) => {
    if (!el) return;
    const r = el.getBoundingClientRect();
    const x = ev.clientX - r.left;
    const pct01 = Math.min(1, Math.max(0, x / r.width));
    player.seekToPct(pct01);
  };

  return html`
    <div>
      <${StatusToast} toast=${toast} />
      <div class="player" id="player">
        <video id="video" playsinline ref=${videoRef}></video>
        <div class="progress" id="progress" title="Seek" onClick=${(e) => onSeekBarClick(e, e.currentTarget)}>
          <div class="progressFill" id="progressFill" style=${{ width: `${pct}%` }}></div>
        </div>
      </div>

      <div class="guideBar" id="guideBar" ref=${guideBarRef}>
        <div class="guideBar-inner">
          <button id="btnSeekBack" class="guideBtn guideBtnSeek" title="-10s" onClick=${() => player.seekBy(-10)}>−10</button>
          <button id="btnSeekFwd" class="guideBtn guideBtnSeek" title="+30s" onClick=${() => player.seekBy(30)}>+30</button>
          <div id="guideSeek" class="guideSeek" title="Seek" onClick=${(e) => onSeekBarClick(e, e.currentTarget)}>
            <div id="guideSeekFill" class="guideSeekFill" style=${{ width: `${pct}%` }}></div>
          </div>
          <button id="btnChannel" class="guideChannel" title="Channels" onClick=${() => (guideOpen.value = true)}>${srcTitle}</button>
          <div class="guideNow" id="guideNow">${epTitle}</div>
          <button id="btnRandom" class="guideBtn" title="Random" onClick=${() => player.playRandom()}>Random</button>
          <button
            id="btnCC"
            class=${"guideBtn" + (cap.showing ? " active" : "")}
            title="Subtitles"
            aria-label="Subtitles"
            style=${{ display: cap.available ? "" : "none" }}
            onClick=${() => player.toggleCaptions()}
          >
            CC
          </button>
          <button id="btnPlay" class="guideBtn" title="Play/Pause" onClick=${() => player.togglePlay()}>
            ${pb.paused ? "▶" : "❚❚"}
          </button>
          <div class="guideTime mono" id="guideTime">${timeLabel}</div>

          <div class="guideBar-sleep">
            <button
              id="btnSleep"
              class="guideBtn"
              title="Sleep timer"
              onClick=${(e) => {
                e.stopPropagation();
                if (sleep.active) return player.clearSleepTimer();
                sleepMenuOpen.value = !sleepMenuOpen.value;
              }}
            >
              ${sleep.label || "Sleep"}
            </button>
            <div
              id="sleepMenu"
              class="sleepMenu"
              aria-hidden=${sleepMenuOpen.value ? "false" : "true"}
              onClick=${(e) => e.stopPropagation()}
            >
              ${[5, 15, 30, 60].map(
                (mins) => html`
                  <button
                    class="sleepOpt"
                    data-mins=${String(mins)}
                    onClick=${(e) => {
                      e.stopPropagation();
                      player.setSleepTimerMins(mins);
                      sleepMenuOpen.value = false;
                    }}
                  >
                    ${mins === 60 ? "1 hr" : `${mins} min`}
                  </button>
                `
              )}
            </div>
          </div>

          <button id="btnTheme" class="guideBtn" title="Theme" onClick=${toggleTheme}>Theme</button>
        </div>
      </div>

      <${GuidePanel} isOpen=${guideOpen} sources=${sources} player=${player} />
      <${HistoryPanel} isOpen=${historyOpen} history=${history} player=${player} />
      <${DetailsPanel} isOpen=${detailsOpen} env=${env} player=${player} log=${log} />

      <button id="btnHistory" class="cornerBtn cornerBtnLeft" title="History" onClick=${() => (historyOpen.value = !historyOpen.value)}>
        ☰
      </button>
      <button id="btnDetails" class="cornerBtn" title="Details" onClick=${() => (detailsOpen.value = !detailsOpen.value)}>⋯</button>
    </div>
  `;
}
