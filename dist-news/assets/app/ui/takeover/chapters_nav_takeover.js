import { html } from "../../runtime/vendor.js";

const PREF_KEY = "vodcasts_chapters_nav_layout_v1";

function getLayout() {
  try {
    const v = localStorage.getItem(PREF_KEY);
    return v === "detailed" ? "detailed" : "basic";
  } catch {
    return "basic";
  }
}

function setLayout(v) {
  try {
    localStorage.setItem(PREF_KEY, v === "detailed" ? "detailed" : "basic");
  } catch {}
}

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

function clamp(v, a, b) {
  return Math.min(b, Math.max(a, v));
}

function durFor(ch, nextCh, videoDuration) {
  const t0 = Number(ch?.t);
  if (!Number.isFinite(t0)) return null;
  const t1 = Number(nextCh?.t);
  if (Number.isFinite(t1) && t1 > t0) return t1 - t0;
  const vd = Number(videoDuration);
  if (Number.isFinite(vd) && vd > t0) return vd - t0;
  return null;
}

function card({ label, ch, nextCh, player, isCurrent = false, dim = false, detailed = false, idx = null, total = null, videoDuration = null, onJump }) {
  const name = ch?.name ? String(ch.name) : "—";
  const t0 = Number(ch?.t);
  const tLabel = Number.isFinite(t0) ? player.fmtTime(t0) : "";
  const d = durFor(ch, nextCh, videoDuration);
  const dLabel = Number.isFinite(d) && d > 1 ? player.fmtTime(d) : "";
  const end = Number.isFinite(d) && Number.isFinite(t0) ? t0 + d : null;
  const endLabel = Number.isFinite(end) ? player.fmtTime(end) : "";

  const cls =
    "chapNavCard" +
    (isCurrent ? " chapNavCardCurrent" : "") +
    (dim ? " chapNavCardDim" : "") +
    (detailed ? " chapNavCardDetailed" : "");

  const onClick = () => {
    if (!Number.isFinite(t0)) return;
    try {
      onJump?.(t0);
    } catch {}
  };

  return html`
    <div class=${cls} role="button" tabIndex=${Number.isFinite(t0) ? 0 : -1} onClick=${onClick} onKeyDown=${(e) => { if (e.key === "Enter") onClick(); }}>
      <div class="chapNavCardTop">
        <span class="chapNavCardLabel">${label}</span>
        ${Number.isFinite(idx) && Number.isFinite(total) && total > 0
          ? html`<span class="chapNavCardIdx">${clamp(idx + 1, 1, total)}/${total}</span>`
          : ""}
        <span class="chapNavCardTime">${tLabel}</span>
      </div>
      <div class="chapNavCardTitle">${name}</div>
      ${detailed
        ? html`
            <div class="chapNavCardMeta">
              ${dLabel ? html`<span class="chapNavPill">Duration ${dLabel}</span>` : html`<span class="chapNavPill chapNavPillDim">Duration —</span>`}
              ${endLabel ? html`<span class="chapNavPill">Ends ${endLabel}</span>` : ""}
            </div>
          `
        : ""}
    </div>
  `;
}

export function ChaptersNavTakeover({ player, takeover }) {
  const raw = player.chapters?.value || [];
  const chapters = Array.isArray(raw) ? raw.slice().sort((a, b) => (Number(a?.t) || 0) - (Number(b?.t) || 0)) : [];
  const pb = player.playback?.value || { time: 0 };
  const layout = getLayout();
  const detailed = layout === "detailed";

  if (!chapters.length) {
    return html`
      <div class="guideBarTakeover" role="dialog" aria-label="Chapters" onPointerDownCapture=${() => takeover.bump()} onKeyDownCapture=${() => takeover.bump()}>
        <div class="guideBarTakeoverHeader">
          <div class="guideBarTakeoverTitle">Chapters</div>
          <button class="guideBtn" title="Done" onClick=${() => takeover.close()}>Done</button>
        </div>
        <div class="guideBarTakeoverBody">
          <div class="takeoverHint">No chapters for this episode.</div>
        </div>
      </div>
    `;
  }

  const idx = chapterIndexAt(chapters, pb.time || 0);
  const cur = idx >= 0 ? chapters[idx] : chapters[0];
  const prev = idx > 0 ? chapters[idx - 1] : null;
  const next = idx >= 0 && idx + 1 < chapters.length ? chapters[idx + 1] : null;
  const vd = Number(pb.duration);
  const videoDuration = Number.isFinite(vd) && vd > 0 ? vd : null;

  const jumpTo = (t) => {
    const tt = Number(t);
    if (!Number.isFinite(tt)) return;
    player.seekToTime?.(tt);
  };

  return html`
    <div
      class=${"guideBarTakeover chapNav" + (detailed ? " chapNav-detailed" : " chapNav-basic")}
      role="dialog"
      aria-label="Chapters"
      onPointerDownCapture=${() => takeover.bump()}
      onKeyDownCapture=${() => takeover.bump()}
    >
      <div class="guideBarTakeoverHeader">
        <div class="guideBarTakeoverTitle">Chapters</div>
        <button class="guideBtn" title="Done" onClick=${() => takeover.close()}>Done</button>
      </div>
      <div class="guideBarTakeoverBody">
        <div class="takeoverOpts">
          <button class="guideBtn" title="Previous chapter" disabled=${!prev} onClick=${() => jumpTo(prev?.t)}>Prev</button>
          <button class="guideBtn" title="Restart chapter" onClick=${() => jumpTo(cur?.t)}>Current</button>
          <button class="guideBtn" title="Next chapter" disabled=${!next} onClick=${() => jumpTo(next?.t)}>Next</button>
        </div>

        <div class="chapNavBrowser" aria-label="What’s next">
          ${card({
            label: "Prev",
            ch: prev,
            nextCh: cur,
            player,
            dim: !prev,
            detailed,
            idx: prev ? idx - 1 : null,
            total: chapters.length,
            videoDuration,
            onJump: jumpTo,
          })}
          ${card({
            label: "Now",
            ch: cur,
            nextCh: next,
            player,
            isCurrent: true,
            detailed,
            idx: idx >= 0 ? idx : null,
            total: chapters.length,
            videoDuration,
            onJump: jumpTo,
          })}
          ${card({
            label: "Next",
            ch: next,
            nextCh: chapters[idx + 2],
            player,
            dim: !next,
            detailed,
            idx: next ? idx + 1 : null,
            total: chapters.length,
            videoDuration,
            onJump: jumpTo,
          })}
        </div>
      </div>
    </div>
  `;
}

export function ChaptersNavSettingsTakeover({ takeover }) {
  const layout = getLayout();

  return html`
    <div class="guideBarTakeover" role="dialog" aria-label="Nav settings" onPointerDownCapture=${() => takeover.bump()} onKeyDownCapture=${() => takeover.bump()}>
      <div class="guideBarTakeoverHeader">
        <div class="guideBarTakeoverTitle">Nav settings</div>
        <button class="guideBtn" title="Done" onClick=${() => takeover.close()}>Done</button>
      </div>
      <div class="guideBarTakeoverBody">
        <div class="takeoverOpts" title="Layout">
          <button
            class=${"guideBtn" + (layout === "basic" ? " active" : "")}
            title="Basic layout (compact)"
            onClick=${() => {
              setLayout("basic");
              takeover.bump();
            }}
          >
            Basic
          </button>
          <button
            class=${"guideBtn" + (layout === "detailed" ? " active" : "")}
            title="Detailed layout (shows more info)"
            onClick=${() => {
              setLayout("detailed");
              takeover.bump();
            }}
          >
            Detailed
          </button>
        </div>
        <div class="takeoverHint">Basic shows Prev / Now / Next. Detailed adds extra metadata like durations when available.</div>
      </div>
    </div>
  `;
}
