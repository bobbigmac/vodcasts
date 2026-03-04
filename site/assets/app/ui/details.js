import { html } from "../runtime/vendor.js";
import { useEffect } from "../runtime/vendor.js";
import { sanitizeHtml } from "../vod/feed_parse.js";
import { LogPanel } from "./log.js";

function escapeHtml(s) {
  if (!s) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function DetailsPanel({ isOpen, env, player, log }) {
  const bp = String(env?.basePath || "/").replace(/\/?$/, "/");
  const cur = player.current.value;
  const ep = cur.episode;
  const cache = player.fullDescriptionCache?.value || {};
  const epKey = cur.source?.id && ep?.id ? `${cur.source.id}::${ep.id}` : "";
  const fullHtml = epKey ? cache[epKey] : "";
  const descHtml = ep?.descriptionHtml || fullHtml;
  const safeDescHtml = descHtml ? sanitizeHtml(descHtml) : ep?.descriptionShort ? escapeHtml(ep.descriptionShort) : "";

  useEffect(() => {
    if (isOpen.value && ep?.id && cur.source?.id && ep.descriptionShort && !ep.descriptionHtml && !fullHtml) {
      player.loadFullDescription?.(cur.source.id, ep.id);
    }
  }, [isOpen.value, ep?.id, cur.source?.id, ep?.descriptionShort, ep?.descriptionHtml, fullHtml]);
  const chapters = player.chapters.value || [];
  const chaptersErr = player.chaptersLoadError?.value ?? null;
  const transcriptsErr = player.transcriptsLoadError?.value ?? null;
  const hasChapters = ep && ((ep.chaptersInline && ep.chaptersInline.length) || ep.chaptersExternal);
  const hasSubtitles = ep && ep.transcripts && ep.transcripts.length > 0;
  const transcriptsAll = ep?.transcriptsAll || ep?.transcripts || [];
  const hasTranscriptLink = transcriptsAll.length > 0;

  return html`
    <div id="detailsPanel" class="detailsPanel" aria-hidden=${isOpen.value ? "false" : "true"}>
      <div class="detailsHeader">
        <span>Details</span>
        <button id="btnCloseDetails" class="guideBtn" onClick=${() => (isOpen.value = false)}>✕</button>
      </div>
      <div class="detailsContent">
        <div id="epTitle" class="detailsTitle">${ep?.title || "—"}</div>
        <div id="epSub" class="detailsSub">
          ${ep ? `${ep.channelTitle || cur.source?.title || ""}${ep.dateText ? " · " + ep.dateText : ""}` : "—"}
        </div>
        ${ep
          ? html`
              <div class="detailsFeatures">
                <span class=${"detailsFeature" + (hasChapters ? " available" : "")} title=${hasChapters ? "Chapters available" : chaptersErr ? "Chapters: " + chaptersErr : "No chapters"}>
                  Chapters ${hasChapters ? "✓" : chaptersErr ? "✗" : "—"}
                </span>
                <span class=${"detailsFeature" + (hasSubtitles || hasTranscriptLink ? " available" : "")} title=${hasSubtitles ? "Subtitles loaded" : hasTranscriptLink ? "Transcript link available" : transcriptsErr ? "Subtitles: " + transcriptsErr : "No transcript"}>
                  Transcript ${hasSubtitles ? "✓" : hasTranscriptLink ? "link" : transcriptsErr ? "✗" : "—"}
                </span>
              </div>
            `
          : ""}
        <div id="epDesc" class="detailsDesc" dangerouslySetInnerHTML=${{ __html: safeDescHtml }}></div>

        <div class="detailsChapters">
          <div class="detailsChaptersTitle">Chapters</div>
          ${chaptersErr
            ? html`<div class="detailsEnrichError">Failed to load: ${chaptersErr}</div>`
            : !hasChapters && ep
              ? html`<div class="detailsEnrichHint">Not available for this episode</div>`
              : ""}
          <div id="chapters" class="chapters">
            ${chapters.map(
              (ch) => html`
                <div
                  class="ch"
                  onClick=${() => {
                    player.seekToTime(ch.t || 0);
                    player.play({ userGesture: true });
                  }}
                >
                  <div class="chName">${ch.name || "Chapter"}</div>
                  <div class="chTime">${player.fmtTime(ch.t)}</div>
                </div>
              `
            )}
          </div>
          ${hasTranscriptLink
            ? html`
                <div class="detailsTranscriptLinks">
                  <div class="detailsChaptersTitle">Transcript</div>
                  ${transcriptsAll.map(
                    (t) =>
                      html`
                        <a class="detailsTranscriptLink" href=${t.url} target="_blank" rel="noopener noreferrer">
                          ${t.lang || "en"} transcript</a
                        >
                      `
                  )}
                </div>
              `
            : transcriptsErr
              ? html`<div class="detailsEnrichError">Subtitles: ${transcriptsErr}</div>`
              : ep && !hasSubtitles && !transcriptsAll.length
                ? html`<div class="detailsEnrichHint">No transcript for this episode</div>`
                : ""}
        </div>

        <${LogPanel} log=${log} />

        <div class="detailsSupport">
          <div class="detailsSupportTitle">Prays.be</div>
          <div class="detailsSupportLinks">
            <a href=${bp + "about/"} target="_self">About</a>
            <a href=${bp + "for/"} target="_self">Who it’s for</a>
            <a href=${bp + "privacy/"} target="_self">Privacy</a>
            <a href=${bp + "legal/"} target="_self">Legal</a>
            <a href="mailto:admin@prays.be">Contact</a>
          </div>
          <div class="detailsSupportNote">
            We curate a mix of third‑party feeds and may adjust the selection over time. If a feed should be removed, email admin@prays.be.
          </div>
        </div>
      </div>
    </div>
  `;
}
