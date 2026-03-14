/**
 * Netflix-style browse panel: carousels for shows/episodes (not the guide/EPG).
 */
import { html, useEffect, useRef, useSignal } from "../runtime/vendor.js";
import { fallbackInitials, thumbFallbackStyle, titlePosClass, VodCarouselRow } from "./vod_carousel.js";
import { HeadphonesIcon } from "./icons.js";

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

function isVideoEpisode(ep) {
  const m = ep?.media || null;
  if (!m) return false;
  if (m.pickedIsVideo === true) return true;
  if (m.pickedIsVideo === false) return false;
  const t = String(m.type || "").toLowerCase();
  if (t.startsWith("video/")) return true;
  if (t.startsWith("audio/")) return false;
  const u = String(m.url || "").toLowerCase();
  if (u.includes(".m3u8")) return true;
  if (u.match(/\.(mp4|m4v|mov|webm)(\?|$)/)) return true;
  if (u.match(/\.(mp3|m4a|aac|ogg|opus)(\?|$)/)) return false;
  return false;
}

function isAudioOnlyShow(show) {
  const eps = show?.episodes || [];
  if (!Array.isArray(eps) || !eps.length) return false;
  return !eps.some((e) => isVideoEpisode(e));
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
  onClose,
  onExpandShow,
}) {
  const normBasePath = (p) => {
    let s = String(p || "/");
    if (!s.startsWith("/")) s = "/" + s;
    if (!s.endsWith("/")) s = s + "/";
    return s;
  };
  const bp = normBasePath(window.__VODCASTS__?.basePath || "/");
  const curSourceId = player?.currentSourceId?.value || null;
  const curEpId = player?.currentEpisodeId?.value || null;
  const open = !!isOpen?.value;
  const panelRef = useRef(null);
  const onCloseRef = useRef(onClose);
  const countdownPct = useSignal(1);

  onCloseRef.current = onClose;

  const playAndClose = ({ ep, showEpisodes = null, showSlug = null }) => {
    if (!feedId || !ep?.id) return;
    playEpisode({ player, feedId, ep, showEpisodes, showSlug });
    onCloseRef.current?.();
  };

  useEffect(() => {
    if (!open) return;
    const panel = panelRef.current;
    if (!panel) return;
    // If the user already focused something inside, don't steal it.
    const a = document.activeElement;
    if (a && panel.contains(a)) return;
    const playingBtn =
      panel.querySelector(".vodCarouselItem.playing .vodThumbBtn[data-navitem='1']") ||
      panel.querySelector(".vodCarouselItem.playing [data-navitem='1']");
    if (playingBtn && typeof playingBtn.focus === "function") {
      try {
        playingBtn.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "start" });
      } catch {}
      try {
        playingBtn.focus();
      } catch {}
    }
  }, [open, feedId, initialExpandShowSlug, curSourceId, curEpId]);

  useEffect(() => {
    countdownPct.value = 1;
    if (!open) return;
    const panel = panelRef.current;
    if (!panel || !onCloseRef.current) return;
    const IDLE_MS = 6500;
    let deadline = Date.now() + IDLE_MS;
    let rafId = 0;
    let closed = false;

    const tick = () => {
      if (closed) return;
      const remaining = Math.max(0, deadline - Date.now());
      countdownPct.value = remaining / IDLE_MS;
      if (remaining <= 0) {
        closed = true;
        countdownPct.value = 0;
        onCloseRef.current?.();
        return;
      }
      rafId = window.requestAnimationFrame(tick);
    };

    const resetIdleClose = () => {
      if (closed) return;
      deadline = Date.now() + IDLE_MS;
      countdownPct.value = 1;
    };

    const evs = ["mousemove", "mousedown", "keydown", "touchstart", "touchmove", "wheel", "pointerdown", "pointermove", "focusin"];
    evs.forEach((ev) => panel.addEventListener(ev, resetIdleClose, { passive: true }));
    panel.addEventListener("scroll", resetIdleClose, true);
    tick();

    return () => {
      closed = true;
      countdownPct.value = 1;
      if (rafId) window.cancelAnimationFrame(rafId);
      evs.forEach((ev) => panel.removeEventListener(ev, resetIdleClose));
      panel.removeEventListener("scroll", resetIdleClose, true);
    };
  }, [open, feedId, initialExpandShowSlug]);

  if (!shows?.length) {
    return html`
      <div id="browsePanel" class="browsePanel" aria-hidden=${isOpen?.value ? "false" : "true"} role="panel">
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

  const selfHref = focusedShow
    ? (feedId && (focusedShow.slug || focusedShow.id))
      ? `${bp}feed/${encodeURIComponent(String(feedId))}/shows/${encodeURIComponent(String(focusedShow.slug || focusedShow.id))}/`
      : null
    : (feedId ? `${bp}feed/${encodeURIComponent(String(feedId))}/` : null);

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
      <h2 class="browseTitle">
        ${selfHref
          ? html`<a class="browseTitleLink" href=${selfHref}>${showHeaderTitle}</a>`
          : html`${showHeaderTitle}`}
      </h2>
      ${onClose
        ? html`
            <div class="browseHeaderActions">
              <span class="browseAutoClose" aria-hidden="true">
                <span class="browseAutoCloseTrack">
                  <span class="browseAutoCloseFill" style=${{ transform: `scaleX(${countdownPct.value})` }}></span>
                </span>
              </span>
              <button class="browseCloseBtn" type="button" onClick=${onClose} aria-label="Close">
                ×
              </button>
            </div>
          `
        : ""}
    </header>
  `;

  // Show episodes view.
  if (focusedShow) {
    const eps = focusedShow.episodes || [];
    const progress = getShowProgress(focusedShow, feedId, history, player);
    const resumeId = progress.resumeEpisode?.id || null;
    const artSeed = `${feedId}:${focusedShow.slug || focusedShow.id}`;

    return html`
      <div id="browsePanel" class="browsePanel" aria-hidden=${isOpen?.value ? "false" : "true"} role="panel">
        <div class="browsePanel-inner" data-carousel-group="browseFeed">
          ${header}
          ${focusedShow.description ? html`<p class="browseShowDesc browseShowDescTop">${focusedShow.description}</p>` : ""}

          <${VodCarouselRow} rowId=${`eps-${feedId}-${focusedShow.id}`} title="Episodes" className="browseEpRow">
            ${eps.map((ep, idx) => {
              const meta = `${ep.dateText || ""}${ep.durationSec ? ` · ${fmtDuration(ep.durationSec)}` : ""}`.trim();
              const isResume = resumeId && ep?.id === resumeId;
              const isPlaying = curSourceId === feedId && curEpId && ep?.id === curEpId;
              const badge = isPlaying ? "Playing" : isResume ? "Resume" : null;
              return html`
                <div class=${"vodCarouselItem vodCarouselItemEpisode" + (isPlaying ? " playing" : "")} data-carousel-idx=${idx} key=${ep.id || idx}>
                  <div class=${"vodThumbWrap vodThumbWrapEpisode " + titlePosClass(`${feedId}:${ep.slug || ep.id}`)}>
                    <button
                      class="vodThumbBtn"
                      type="button"
                      data-navitem="1"
                      aria-label=${isResume ? `Resume: ${ep.title || "Episode"}` : (ep.title || "Episode")}
                      onClick=${() => playAndClose({ ep, showEpisodes: eps, showSlug: focusedShow.slug || focusedShow.id })}
                      onFocus=${ensureFocusedThumbInView}
                    >
                      <div class="vodThumb" style=${thumbFallbackStyle(artSeed)}>
                        <span class="vodThumbPlaceholder">▶</span>
                        ${focusedShow.artworkUrl
                          ? html`<img
                              class="vodThumbImg"
                              src=${focusedShow.artworkUrl}
                              alt=""
                              loading="lazy"
                              decoding="async"
                              fetchpriority="low"
                              onError=${onThumbImgError}
                            />`
                          : ""}
                        ${badge ? html`<span class="vodThumbBadge" aria-hidden="true">${badge}</span>` : ""}
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
      <div id="browsePanel" class="browsePanel" aria-hidden=${isOpen?.value ? "false" : "true"} role="panel">
        <div class="browsePanel-inner" data-carousel-group="browseFeed">
          ${header}
          <${VodCarouselRow} rowId=${`feed-eps-${feedId}`} title="Episodes" className="browseEpRow">
            ${episodes.map((ep, idx) => {
              const meta = `${ep.dateText || ""}${ep.durationSec ? ` · ${fmtDuration(ep.durationSec)}` : ""}`.trim();
              const isPlaying = curSourceId === feedId && curEpId && ep?.id === curEpId;
              return html`
                <div class=${"vodCarouselItem vodCarouselItemEpisode" + (isPlaying ? " playing" : "")} data-carousel-idx=${idx} key=${ep.id || idx}>
                  <div class=${"vodThumbWrap vodThumbWrapEpisode " + titlePosClass(`${feedId}:${ep.slug || ep.id}`)}>
                    <button
                      class="vodThumbBtn"
                      type="button"
                      data-navitem="1"
                      aria-label=${ep.title || "Episode"}
                      onClick=${() => playAndClose({ ep, showEpisodes: episodes, showSlug: shows[0]?.slug || shows[0]?.id })}
                      onFocus=${ensureFocusedThumbInView}
                    >
                      <div class="vodThumb" style=${thumbFallbackStyle(artSeed)}>
                        <span class="vodThumbPlaceholder">▶</span>
                        ${shows[0]?.artworkUrl
                          ? html`<img
                              class="vodThumbImg"
                              src=${shows[0].artworkUrl}
                              alt=""
                              loading="lazy"
                              decoding="async"
                              fetchpriority="low"
                              onError=${onThumbImgError}
                            />`
                          : ""}
                        ${isPlaying ? html`<span class="vodThumbBadge" aria-hidden="true">Playing</span>` : ""}
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
    <div id="browsePanel" class="browsePanel" aria-hidden=${isOpen?.value ? "false" : "true"} role="panel">
      <div class="browsePanel-inner" data-carousel-group="browseFeed">
        ${header}
        <${VodCarouselRow} rowId=${`shows-${feedId}`} title="Shows" className="browseShowsRow">
          ${shows.map((show, idx) => {
            const progress = getShowProgress(show, feedId, history, player);
            const showTitle = show.title_full || show.title;
            const posClass = titlePosClass(`${feedId}:${show.slug || show.id}`);
            const eps = show.episodes || [];
            const isPlayingShow = curSourceId === feedId && curEpId && eps.some((e) => e?.id === curEpId);
            const audioOnly = isAudioOnlyShow(show);
            const total = progress.totalEpisodes || (show.episodeCount || 0);
            const watched = progress.watchedCount || 0;
            const resumeLabel = progress.resumeEpisode ? "Resume" : "Play";
            const watchedPct = total > 0 ? Math.round((watched / total) * 100) : 0;
            const thumbSeed = `${feedId}:${show.slug || show.id}`;
            const initials = fallbackInitials(showTitle) || "TV";

            return html`
              <div class=${"vodCarouselItem vodCarouselItemShow" + (isPlayingShow ? " playing" : "")} key=${show.id} data-carousel-idx=${idx}>
                <div class=${"vodThumbWrap " + posClass}>
                  <button
                    class="vodThumbBtn"
                    type="button"
                    data-navitem="1"
                    aria-label=${showTitle || "Show"}
                    onClick=${() => {
                      const ep = progress.resumeEpisode || eps[0];
                      playAndClose({ ep, showEpisodes: eps, showSlug: show.slug || show.id });
                    }}
                    onFocus=${ensureFocusedThumbInView}
                  >
                    <div class="vodThumb" style=${thumbFallbackStyle(thumbSeed)}>
                      <span class="vodThumbPlaceholder">${initials}</span>
                      ${show.artworkUrl
                        ? html`<img
                            class="vodThumbImg"
                            src=${show.artworkUrl}
                            alt=""
                            loading="lazy"
                            decoding="async"
                            fetchpriority="low"
                            onError=${onThumbImgError}
                          />`
                        : ""}
                      ${isPlayingShow ? html`<span class="vodThumbBadge" aria-hidden="true">Playing</span>` : ""}
                      ${audioOnly
                        ? html`<span class="vodThumbAudio" aria-hidden="true" title="Audio only"><${HeadphonesIcon} size=${16} /></span>`
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
