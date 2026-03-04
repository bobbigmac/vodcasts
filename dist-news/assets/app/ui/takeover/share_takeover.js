import { html } from "../../runtime/vendor.js";
import { buildShareUrl } from "../../main/route.js";

async function copyToClipboard(text) {
  const s = String(text || "");
  if (!s) return false;
  try {
    await navigator.clipboard?.writeText?.(s);
    return true;
  } catch {}

  try {
    const ta = document.createElement("textarea");
    ta.value = s;
    ta.setAttribute("readonly", "true");
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    ta.style.top = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return !!ok;
  } catch {
    return false;
  }
}

export function ShareTakeover({ player, takeover, log }) {
  const cur = player.current.value;
  const pb = player.playback.value;

  const feed = cur.source?.id || "";
  const epSlug = cur.episode?.slug || "";
  const t = Number(pb.time) || 0;

  const base = feed ? buildShareUrl({ feed }) : "";
  const epUrl = feed && epSlug ? buildShareUrl({ feed, ep: epSlug }) : "";
  const timeUrl = feed && epSlug ? buildShareUrl({ feed, ep: epSlug, t }) : "";

  const copyAndClose = async (url, label) => {
    const ok = await copyToClipboard(url);
    if (ok) log?.info?.(`Copied ${label} link`);
    else log?.warn?.("Copy failed");
    takeover.close();
  };

  return html`
    <div class="guideBarTakeover" role="dialog" aria-label="Share" onPointerDownCapture=${() => takeover.bump()} onKeyDownCapture=${() => takeover.bump()}>
      <div class="guideBarTakeoverHeader">
        <div class="guideBarTakeoverTitle">Share</div>
      </div>
      <div class="guideBarTakeoverBody">
        <div class="takeoverHint">Tap what you want to copy.</div>
        <div class="takeoverOpts">
          <button class="guideBtn" disabled=${!base} title="Copy channel link" onClick=${() => copyAndClose(base, "channel")}>Feed</button>
          <button class="guideBtn" disabled=${!epUrl} title="Copy episode link" onClick=${() => copyAndClose(epUrl, "episode")}>Episode</button>
          <button class="guideBtn" disabled=${!timeUrl} title="Copy link with timestamp" onClick=${() => copyAndClose(timeUrl, "timestamp")}>Time</button>
        </div>
        ${epUrl
          ? html`<div class="takeoverHint" style=${{ fontFamily: "var(--mono)", fontSize: "11px", opacity: 0.9 }}>${epUrl}</div>`
          : ""}
      </div>
    </div>
  `;
}

