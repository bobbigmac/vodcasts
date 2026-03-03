/**
 * Netflix-style browse panel: carousels for shows/episodes (not the guide/EPG).
 */
import { html } from "../runtime/vendor.js";
import { fallbackInitials, thumbFallbackStyle, titlePosClass, VodCarouselRow } from "./vod_carousel.js";

/** Compute show progress: { watchedCount, resumeEpisode, totalEpisodes } */
function getShowProgress(show, feedId, history, player) {
  const episodes = show.episodes || [];
  const total = episodes.length;
  if (total === 0) return { watchedCount: 0, resumeEpisode: null, totalEpisodes: 0 };

  const WATCHED_THRESHOLD = 0.9;
  let watchedCount = 0;
  let resumeEpisode = null;
  let bestProgress = 0;

  for (const ep of episodes) {
    const maxProg = player?.getProgressMaxSec?.(feedId, ep.id) ?? 0;
    const dur = ep.durationSec;
    const isWatched = Number.isFinite(dur) && dur > 0 ? maxProg >= dur * WATCHED_THRESHOLD : maxProg > 60;
    if (isWatched) watchedCount++;
    else if (maxProg > bestProgress && maxProg > 0) {
      bestProgress = maxProg;
      resumeEpisode = ep;
    }
  }

  if (!resumeEpisode && watchedCount < total) {
    const historyAll = history?.all?.value || [];
    const episodeIds = new Set(episodes.map((e) => e?.id).filter(Boolean));
    for (const e of historyAll) {
      if (e.sourceId === feedId && episodeIds.has(e.episodeId)) {
        resumeEpisode = episodes.find((x) => x?.id === e.episodeId);
        break;
      }
    }
  }

  return { watchedCount, resumeEpisode, totalEpisodes: total };
}

function fmtDuration(sec) {
  if (!Number.isFinite(sec) || sec < 0) return "";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (h > 0) return `${h}h${m}m`;
  if (m > 0) return `${m}m`;
  return `${Math.floor(sec)}s`;
}

function playEpisode({ player, feedId, ep, showEpisodes = null, showSlug = null }) {
  if (!feedId || !ep?.id) return;
  const pl = showEpisodes?.length ? { feedId, episodes: showEpisodes, showSlug: showSlug || undefined } : null;
  player.selectSourceAndEpisode(feedId, ep.id, { autoplay: true, playlist: pl });
}

function ensureFocusedThumbInView(e) {
  try {
    e.currentTarget.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "start" });
  } catch {}
}

function onThumbImgError(e) {
  try {
    const img = e.currentTarget;
    img.style.display = "none";
  } catch {}
}

export function BrowsePanel({
  isOpen,
  feedId,
  feedTitle,
  shows,
  hasCustomShows,
  initialExpandShowSlug,
  player,
  history,
  onBack,
  onExpandShow,
}) {
  if (!shows?.length) {
    return html`
      <div class="browsePanel" aria-hidden=${isOpen?.value ? "false" : "true"} role="panel">
        <div class="browsePanel-inner">
          <div class="browsePanel-empty">No shows for this feed.</div>
        </div>
      </div>
    `;
  }

  const episodesOnly = !hasCustomShows && shows.length === 1 && shows[0]?.isLeftovers;
  const episodes = episodesOnly ? (shows[0]?.episodes || []) : [];

  const focusedShow =
    initialExpandShowSlug && shows.length > 1
      ? shows.find((x) => String(x?.slug || "").toLowerCase() === String(initialExpandShowSlug).toLowerCase())
      : null;

  const showHeaderTitle = focusedShow
    ? focusedShow.title_full || focusedShow.title
    : (feedTitle || feedId);

  const headerBackLabel = focusedShow ? "Back to shows" : "Back";

  const header = html`
    <header class="browseHeader">
      ${onBack
        ? html`
            <button class="browseBackBtn" type="button" onClick=${onBack} aria-label=${headerBackLabel}>
              ←
            </button>
          `
        : ""}
      <h2 class="browseTitle">${showHeaderTitle}</h2>
    </header>
  `;

  // Show episodes view.
  if (focusedShow) {
    const eps = focusedShow.episodes || [];
    const progress = getShowProgress(focusedShow, feedId, history, player);
    const resumeId = progress.resumeEpisode?.id || null;
    const artSeed = `${feedId}:${focusedShow.slug || focusedShow.id}`;

    return html`
      <div class="browsePanel" aria-hidden=${isOpen?.value ? "false" : "true"} role="panel">
        <div class="browsePanel-inner" data-carousel-group="browseFeed">
          ${header}
          ${focusedShow.description ? html`<p class="browseShowDesc browseShowDescTop">${focusedShow.description}</p>` : ""}

          <${VodCarouselRow} rowId=${`eps-${feedId}-${focusedShow.id}`} title="Episodes" className="browseEpRow">
            ${eps.map((ep, idx) => {
              const meta = `${ep.dateText || ""}${ep.durationSec ? ` · ${fmtDuration(ep.durationSec)}` : ""}`.trim();
              const isResume = resumeId && ep?.id === resumeId;
              return html`
                <div class="vodCarouselItem vodCarouselItemEpisode" data-carousel-idx=${idx} key=${ep.id || idx}>
                  <div class=${"vodThumbWrap vodThumbWrapEpisode " + titlePosClass(`${feedId}:${ep.slug || ep.id}`)}>
                    <button
                      class="vodThumbBtn"
                      type="button"
                      data-navitem="1"
                      aria-label=${isResume ? `Resume: ${ep.title || "Episode"}` : (ep.title || "Episode")}
                      onClick=${() => playEpisode({ player, feedId, ep, showEpisodes: eps, showSlug: focusedShow.slug || focusedShow.id })}
                      onFocus=${ensureFocusedThumbInView}
                    >
                      <div class="vodThumb" style=${thumbFallbackStyle(artSeed)}>
                        <span class="vodThumbPlaceholder">▶</span>
                        ${focusedShow.artworkUrl
                          ? html`<img class="vodThumbImg" src=${focusedShow.artworkUrl} alt="" loading="lazy" onError=${onThumbImgError} />`
                          : ""}
                        ${isResume ? html`<span class="vodThumbBadge" aria-hidden="true">Resume</span>` : ""}
                        <span class="vodThumbTitle">
                          <span class="vodThumbTitleBar">${ep.title || "Episode"}</span>
                        </span>
                        ${meta ? html`<span class="vodThumbSub">${meta}</span>` : ""}
                      </div>
                    </button>
                  </div>
                </div>
              `;
            })}
          </${VodCarouselRow}>
        </div>
      </div>
    `;
  }

  // Episodes-only feeds (no custom shows).
  if (episodesOnly) {
    const artSeed = `${feedId}:${shows[0]?.slug || shows[0]?.id || "feed"}`;
    return html`
      <div class="browsePanel" aria-hidden=${isOpen?.value ? "false" : "true"} role="panel">
        <div class="browsePanel-inner" data-carousel-group="browseFeed">
          ${header}
          <${VodCarouselRow} rowId=${`feed-eps-${feedId}`} title="Episodes" className="browseEpRow">
            ${episodes.map((ep, idx) => {
              const meta = `${ep.dateText || ""}${ep.durationSec ? ` · ${fmtDuration(ep.durationSec)}` : ""}`.trim();
              return html`
                <div class="vodCarouselItem vodCarouselItemEpisode" data-carousel-idx=${idx} key=${ep.id || idx}>
                  <div class=${"vodThumbWrap vodThumbWrapEpisode " + titlePosClass(`${feedId}:${ep.slug || ep.id}`)}>
                    <button
                      class="vodThumbBtn"
                      type="button"
                      data-navitem="1"
                      aria-label=${ep.title || "Episode"}
                      onClick=${() => playEpisode({ player, feedId, ep, showEpisodes: episodes, showSlug: shows[0]?.slug || shows[0]?.id })}
                      onFocus=${ensureFocusedThumbInView}
                    >
                      <div class="vodThumb" style=${thumbFallbackStyle(artSeed)}>
                        <span class="vodThumbPlaceholder">▶</span>
                        ${shows[0]?.artworkUrl
                          ? html`<img class="vodThumbImg" src=${shows[0].artworkUrl} alt="" loading="lazy" onError=${onThumbImgError} />`
                          : ""}
                        <span class="vodThumbTitle">
                          <span class="vodThumbTitleBar">${ep.title || "Episode"}</span>
                        </span>
                        ${meta ? html`<span class="vodThumbSub">${meta}</span>` : ""}
                      </div>
                    </button>
                  </div>
                </div>
              `;
            })}
          </${VodCarouselRow}>
        </div>
      </div>
    `;
  }

  // Shows carousel view.
  return html`
    <div class="browsePanel" aria-hidden=${isOpen?.value ? "false" : "true"} role="panel">
      <div class="browsePanel-inner" data-carousel-group="browseFeed">
        ${header}
        <${VodCarouselRow} rowId=${`shows-${feedId}`} title="Shows" className="browseShowsRow">
          ${shows.map((show, idx) => {
            const progress = getShowProgress(show, feedId, history, player);
            const showTitle = show.title_full || show.title;
            const posClass = titlePosClass(`${feedId}:${show.slug || show.id}`);
            const eps = show.episodes || [];
            const total = progress.totalEpisodes || (show.episodeCount || 0);
            const watched = progress.watchedCount || 0;
            const resumeLabel = progress.resumeEpisode ? "Resume" : "Play";
            const watchedPct = total > 0 ? Math.round((watched / total) * 100) : 0;
            const thumbSeed = `${feedId}:${show.slug || show.id}`;
            const initials = fallbackInitials(showTitle) || "TV";

            return html`
              <div class="vodCarouselItem vodCarouselItemShow" key=${show.id} data-carousel-idx=${idx}>
                <div class=${"vodThumbWrap " + posClass}>
                  <button
                    class="vodThumbBtn"
                    type="button"
                    data-navitem="1"
                    aria-label=${showTitle || "Show"}
                    onClick=${() => {
                      const ep = progress.resumeEpisode || eps[0];
                      playEpisode({ player, feedId, ep, showEpisodes: eps, showSlug: show.slug || show.id });
                    }}
                    onFocus=${ensureFocusedThumbInView}
                  >
                    <div class="vodThumb" style=${thumbFallbackStyle(thumbSeed)}>
                      <span class="vodThumbPlaceholder">${initials}</span>
                      ${show.artworkUrl
                        ? html`<img class="vodThumbImg" src=${show.artworkUrl} alt="" loading="lazy" onError=${onThumbImgError} />`
                        : ""}
                      ${(show.artworkOverlay || showTitle)
                        ? html`
                            <span class="vodThumbTitle">
                              <span class="vodThumbTitleBar">${show.artworkOverlay || showTitle}</span>
                            </span>
                          `
                        : ""}
                      <span class="vodThumbMeta" aria-hidden="true">
                        <span class="vodThumbMetaTop">${resumeLabel}</span>
                        <span class="vodThumbMetaMid">${total} eps${watched ? ` · ${watched} watched` : ""}</span>
                        ${watchedPct > 0
                          ? html`
                              <span class="vodThumbMetaBar">
                                <span class="vodThumbMetaBarFill" style=${{ width: `${watchedPct}%` }}></span>
                              </span>
                            `
                          : ""}
                      </span>
                    </div>
                  </button>
                  <button
                    class="vodThumbIcon"
                    type="button"
                    data-navitem="1"
                    aria-label="View episodes"
                    title="Episodes"
                    onClick=${() => onExpandShow?.(feedId, show.slug || show.id)}
                  >
                    ≡
                  </button>
                </div>
              </div>
            `;
          })}
        </${VodCarouselRow}>
      </div>
    </div>
  `;
}
