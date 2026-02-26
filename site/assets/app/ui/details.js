import { html } from "../runtime/vendor.js";
import { TimedComments } from "../vod/timed_comments.js";
import { sanitizeHtml } from "../vod/feed_parse.js";
import { LogPanel } from "./log.js";

export function DetailsPanel({ isOpen, env, player, log }) {
  const cur = player.current.value;
  const ep = cur.episode;
  const safeDescHtml = ep?.descriptionHtml ? sanitizeHtml(ep.descriptionHtml) : "";
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

        <div class="detailsSplit">
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
                          <a
                            class="detailsTranscriptLink"
                            href=${t.url}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
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
          <div class="detailsComments">
            <div class="detailsCommentsTitle">Comments</div>
            <div id="commentsPanel" class="commentsPanel">
              <${TimedComments} env=${env} player=${player} isActive=${isOpen.value} />
            </div>
          </div>
        </div>

        <${LogPanel} log=${log} />
      </div>
    </div>
  `;
}
