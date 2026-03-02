/**
 * Netflix-style browse panel: shows as primary, summary + count only.
 * Episodes are in the guide, not dumped on the channel page.
 */
import { html, useEffect, useSignal } from "../runtime/vendor.js";

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

export function BrowsePanel({ isOpen, feedId, feedTitle, shows, hasCustomShows, initialExpandShowSlug, player, history, onBack, onExpandShow, onCollapseShow }) {
  const expandedShowId = useSignal(null);

  useEffect(() => {
    if (!initialExpandShowSlug || !shows?.length) return;
    const s = shows.find((x) => String(x?.slug || "").toLowerCase() === String(initialExpandShowSlug).toLowerCase());
    if (s?.id) expandedShowId.value = s.id;
  }, [initialExpandShowSlug, shows]);

  const playEpisode = (ep, showEpisodes = null, showSlug = null) => {
    if (!feedId || !ep?.id) return;
    const pl = showEpisodes?.length ? { feedId, episodes: showEpisodes, showSlug: showSlug || undefined } : null;
    player.selectSourceAndEpisode(feedId, ep.id, { autoplay: true, playlist: pl });
  };

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

  const focusedShow = initialExpandShowSlug && shows.length > 1
    ? shows.find((x) => String(x?.slug || "").toLowerCase() === String(initialExpandShowSlug).toLowerCase())
    : null;

  if (focusedShow) {
    const episodes = focusedShow.episodes || [];
    const progress = getShowProgress(focusedShow, feedId, history, player);
    const showTitle = focusedShow.title_full || focusedShow.title;
    return html`
      <div class="browsePanel" aria-hidden=${isOpen?.value ? "false" : "true"} role="panel">
        <div class="browsePanel-inner">
          <header class="browseHeader">
            ${onBack
              ? html`
                  <button class="browseBackBtn" type="button" onClick=${onBack} aria-label="Back to shows">
                    ←
                  </button>
                `
              : ""}
            <h2 class="browseTitle">${showTitle}</h2>
          </header>
          ${episodes.length
            ? html`
                <div class="browseEpActions">
                  ${progress.resumeEpisode
                    ? html`
                        <button class="browseResumeBtn" type="button" onClick=${() => playEpisode(progress.resumeEpisode, episodes, focusedShow?.slug)}>
                          Resume
                        </button>
                      `
                    : ""}
                  <button class="browsePlayBtn" type="button" onClick=${() => playEpisode(episodes[0], episodes, focusedShow?.slug)}>
                    ${progress.resumeEpisode ? "Play from start" : "Play"}
                  </button>
                </div>
              `
            : ""}
          <div class="browseEpList">
            ${episodes.map(
              (ep) => html`
                <button
                  class="browseEpItem"
                  type="button"
                  onClick=${() => playEpisode(ep, episodes, focusedShow?.slug)}
                  aria-label=${ep.title || "Episode"}
                >
                  <span class="browseEpItemTitle">${ep.title || "Episode"}</span>
                  <span class="browseEpItemMeta">
                    ${ep.dateText || ""} ${ep.durationSec ? fmtDuration(ep.durationSec) : ""}
                  </span>
                </button>
              `
            )}
          </div>
        </div>
      </div>
    `;
  }

  if (episodesOnly) {
    const progress = getShowProgress(shows[0], feedId, history, player);
    return html`
      <div class="browsePanel" aria-hidden=${isOpen?.value ? "false" : "true"} role="panel">
        <div class="browsePanel-inner">
          <header class="browseHeader">
            ${onBack
              ? html`
                  <button class="browseBackBtn" type="button" onClick=${onBack} aria-label="Back to guide">
                    ←
                  </button>
                `
              : ""}
            <h2 class="browseTitle">${feedTitle || feedId}</h2>
          </header>
          ${progress.resumeEpisode
            ? html`
                <div class="browseEpActions">
                  <button class="browseResumeBtn" type="button" onClick=${() => playEpisode(progress.resumeEpisode, episodes, shows[0]?.slug)}>
                    Resume
                  </button>
                </div>
              `
            : ""}
          <div class="browseEpList">
            ${episodes.map(
              (ep) => html`
                <button
                  class="browseEpItem"
                  type="button"
                  onClick=${() => playEpisode(ep, episodes, shows[0]?.slug)}
                  aria-label=${ep.title || "Episode"}
                >
                  <span class="browseEpItemTitle">${ep.title || "Episode"}</span>
                  <span class="browseEpItemMeta">
                    ${ep.dateText || ""} ${ep.durationSec ? fmtDuration(ep.durationSec) : ""}
                  </span>
                </button>
              `
            )}
          </div>
        </div>
      </div>
    `;
  }

  return html`
    <div class="browsePanel" aria-hidden=${isOpen?.value ? "false" : "true"} role="panel">
      <div class="browsePanel-inner">
        <header class="browseHeader">
          ${onBack
            ? html`
                <button class="browseBackBtn" type="button" onClick=${onBack} aria-label="Back to guide">
                  ←
                </button>
              `
            : ""}
          <h2 class="browseTitle">${feedTitle || feedId}</h2>
        </header>
        <div class="browseShowGrid">
          ${shows.map(
            (show) => {
              const isExpanded = expandedShowId.value === show.id;
              const progress = getShowProgress(show, feedId, history, player);
              const showTitle = show.title_full || show.title;
              return html`
                <div class="browseShowCard" key=${show.id}>
                  <button
                    class="browseShowCardBtn"
                    type="button"
                    onClick=${() => {
                      const next = isExpanded ? null : show.id;
                      expandedShowId.value = next;
                      if (next) onExpandShow?.(feedId, show.slug || show.id);
                      else onCollapseShow?.();
                    }}
                  >
                    <div class="browseShowCardThumb">
                      ${show.artworkUrl
                        ? html`
                            <img class="browseShowCardImg" src=${show.artworkUrl} alt="" loading="lazy" />
                            ${(show.artworkOverlay || showTitle) ? html`
                              <span class="browseShowCardOverlay">
                                <span class="browseShowCardOverlayBar">${show.artworkOverlay || showTitle}</span>
                              </span>
                            ` : ""}
                          `
                        : html`<span class="browseShowCardPlaceholder">${show.episodeCount || 0}</span>`}
                    </div>
                    <div class="browseShowCardInfo">
                      <span class="browseShowCardTitle">${showTitle}</span>
                      <span class="browseShowCardMeta">
                        ${progress.totalEpisodes} episodes
                        ${progress.watchedCount > 0 ? ` · ${progress.watchedCount} watched` : ""}
                      </span>
                      ${progress.watchedCount > 0 || progress.resumeEpisode
                        ? html`
                            <div class="browseShowCardProgress" role="progressbar" aria-valuenow=${progress.watchedCount} aria-valuemin=${0} aria-valuemax=${progress.totalEpisodes}>
                              <div
                                class="browseShowCardProgressFill"
                                style=${{ width: `${(progress.watchedCount / progress.totalEpisodes) * 100}%` }}
                              ></div>
                            </div>
                          `
                        : ""}
                    </div>
                    <span class="browseShowCardExpand">${isExpanded ? "−" : "+"}</span>
                  </button>
                  ${isExpanded
                    ? html`
                        <div class="browseShowExpand">
                          ${show.description ? html`<p class="browseShowDesc">${show.description}</p>` : ""}
                          <div class="browseShowActions">
                            ${progress.resumeEpisode
                              ? html`
                                  <button class="browseResumeBtn" type="button" onClick=${() => playEpisode(progress.resumeEpisode, show.episodes, show.slug)}>
                                    Resume
                                  </button>
                                `
                              : ""}
                            ${(show.episodes || []).length
                              ? html`
                                  <button class="browsePlayBtn" type="button" onClick=${() => playEpisode(show.episodes[0], show.episodes, show.slug)}>
                                    ${progress.resumeEpisode ? "Play from start" : "Play"}
                                  </button>
                                `
                              : ""}
                          </div>
                        </div>
                      `
                    : ""}
                </div>
              `;
            }
          )}
        </div>
      </div>
    </div>
  `;
}
