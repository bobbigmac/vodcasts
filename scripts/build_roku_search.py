from __future__ import annotations

import json
import os
import re
import shutil
import time
from hashlib import sha1
from pathlib import Path
from typing import Any

from scripts.feed_manifest import short_description
from scripts.shared import VODCASTS_ROOT, read_json

ROKU_SEARCH_ROOT = "assets/search-feeds/roku-search.json"
ROKU_SEARCH_DIR = "assets/search-feeds"
DEFAULT_CONFIG_PATH = VODCASTS_ROOT / "feeds" / "roku-search.json"

_HTTP_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
_GENERIC_TITLE_RE = re.compile(
    r"^(episode|sermon|message|service|worship|podcast|broadcast|livestream|audio)\b",
    re.IGNORECASE,
)
_ONLY_DATE_RE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}$")


def cleanup_roku_search_outputs(out_dir: Path) -> None:
    root_path = out_dir / ROKU_SEARCH_ROOT
    try:
        root_path.unlink(missing_ok=True)
    except Exception:
        pass
    pages_dir = out_dir / ROKU_SEARCH_DIR
    if pages_dir.exists():
        for old in pages_dir.glob("roku-search-*.json"):
            old.unlink(missing_ok=True)


def build_roku_search(
    *,
    out_dir: Path,
    base_path: str,
    site_origin: str,
    public_sources: list[dict[str, Any]],
    manifest_feeds: list[dict[str, Any]],
    shows_config_all: dict[str, list[dict[str, Any]]],
    args_limit_per_feed: int,
    args_exclude_feeds: str,
    log: callable,
) -> dict[str, int]:
    cfg = _load_config()
    limit_per_feed, limit_source = _resolve_limit(args_limit_per_feed)
    exclude_feed_ids = set(_parse_csv_list(args_exclude_feeds))
    exclude_feed_ids.update(_parse_csv_list(os.getenv("VOD_ROKU_SEARCH_EXCLUDE_FEEDS", "")))
    exclude_feed_ids.update(str(v).strip() for v in cfg.get("excludeFeedIds") or [] if str(v).strip())

    video_shows_per_feed = max(0, int(cfg.get("videoShowsPerFeed") or 2))
    video_episodes_per_feed = max(0, min(limit_per_feed, int(cfg.get("videoEpisodesPerFeed") or 100)))
    audio_only_feed_sample_limit = max(0, int(cfg.get("audioOnlyFeedSampleLimit") or 12))
    audio_episodes_per_feed = max(0, min(limit_per_feed, int(cfg.get("audioEpisodesPerFeed") or 1)))
    short_form_max_duration = max(60, int(cfg.get("shortFormMaxDurationSeconds") or 900))
    page_bytes = max(250_000, int(cfg.get("pageBytes") or 4_000_000))

    manifest_by_id = {str(feed.get("id") or ""): feed for feed in manifest_feeds}
    episode_picks = _normalize_episode_picks(cfg.get("episodePicks") or [])
    query_boosts = _normalize_query_boosts(cfg.get("queryBoosts") or [])

    feeds: list[dict[str, Any]] = []
    for src in public_sources:
        fid = str(src.get("id") or "").strip()
        if not fid or fid in exclude_feed_ids:
            continue
        mf = manifest_by_id.get(fid) or {}
        feats = mf.get("features") or src.get("features") or {}
        feeds.append(
            {
                "id": fid,
                "source": src,
                "manifest": mf,
                "shows": list(shows_config_all.get(fid) or []),
                "episodes": _episodes_recent_first(list((mf.get("episodes") or [])[:limit_per_feed])),
                "hasVideo": bool(feats.get("hasVideo")),
            }
        )

    selected_series_by_feed: dict[str, list[dict[str, Any]]] = {}
    selected_playables: list[dict[str, Any]] = []

    for feed in feeds:
        fid = feed["id"]
        episodes = list(feed["episodes"])
        if not episodes:
            continue

        explicit_picks = _find_explicit_episode_picks(episodes, episode_picks.get(fid) or [])

        if feed["hasVideo"]:
            selected_series = _pick_series(feed["shows"], limit=video_shows_per_feed)
            selected_series_by_feed[fid] = selected_series
            chosen = _pick_video_feed_episodes(
                episodes=episodes,
                explicit_picks=explicit_picks,
                per_feed_limit=video_episodes_per_feed,
            )
            for ep in chosen:
                selected_playables.append({"feed": feed, "episode": ep})

    audio_candidates: list[tuple[float, dict[str, Any], list[dict[str, Any]]]] = []
    for feed in feeds:
        if feed["hasVideo"]:
            continue
        episodes = list(feed["episodes"])
        if not episodes:
            continue
        explicit_picks = _find_explicit_episode_picks(episodes, episode_picks.get(feed["id"]) or [])
        if explicit_picks:
            for ep in explicit_picks[: max(1, limit_per_feed)]:
                selected_playables.append({"feed": feed, "episode": ep})
            continue
        best = _pick_interesting_episodes(episodes, max_items=audio_episodes_per_feed)
        if best:
            score = _episode_interest_score(best[0])
            audio_candidates.append((score, feed, best))

    audio_candidates.sort(key=lambda item: (-item[0], str(item[1]["source"].get("title") or item[1]["id"]).lower(), item[1]["id"]))
    for _, feed, eps in audio_candidates[:audio_only_feed_sample_limit]:
        for ep in eps[:audio_episodes_per_feed]:
            selected_playables.append({"feed": feed, "episode": ep})

    if query_boosts:
        boost_stats = _apply_query_boosts(
            feeds=feeds,
            selected_playables=selected_playables,
            query_boosts=query_boosts,
        )
        shortfalls = [f"{q}={got}/{want}" for q, got, want in boost_stats["shortfalls"][:8]]
        msg = f"  query boosts: +{boost_stats['added']} items across {boost_stats['queries']} queries"
        if shortfalls:
            msg += f" (shortfalls: {', '.join(shortfalls)})"
        log(msg)

    series_assets: list[dict[str, Any]] = []
    selected_series_ids: set[str] = set()
    episode_to_series: dict[tuple[str, str], tuple[str, int | None]] = {}

    for feed in feeds:
        fid = feed["id"]
        for show in selected_series_by_feed.get(fid) or []:
            series_id = _series_asset_id(fid, str(show.get("slug") or ""))
            selected_series_ids.add(series_id)
            series_assets.append(_build_series_asset(feed=feed, show=show, series_id=series_id))
            for key, episode_number in _episode_numbers_for_show(show).items():
                episode_to_series[(fid, key)] = (series_id, episode_number)

    playable_assets: list[dict[str, Any]] = []
    seen_asset_ids: set[str] = set()
    for entry in selected_playables:
        feed = entry["feed"]
        ep = entry["episode"]
        asset_id = _episode_asset_id(feed["id"], ep)
        if asset_id in seen_asset_ids:
            continue
        seen_asset_ids.add(asset_id)
        series_ref = _episode_series_ref(feed["id"], ep, episode_to_series)
        playable_assets.append(
            _build_playable_asset(
                feed=feed,
                ep=ep,
                asset_id=asset_id,
                series_ref=series_ref,
                short_form_max_duration=short_form_max_duration,
            )
        )

    all_assets = series_assets + playable_assets
    all_assets.sort(key=_asset_sort_key, reverse=True)

    if not all_assets:
        cleanup_roku_search_outputs(out_dir)
        return {"feeds": 0, "series": 0, "episodes": 0, "pages": 0, "changed": 0}

    pages = _paginate_assets(
        assets=all_assets,
        page_bytes=page_bytes,
        site_origin=site_origin,
        base_path=base_path,
    )
    changed_files = _write_pages(
        out_dir=out_dir,
        pages=pages,
        site_origin=site_origin,
        base_path=base_path,
    )

    log(
        "  "
        + f"{len(feeds)} feeds, {len(series_assets)} series, {len(playable_assets)} playable assets, "
        + f"{len(pages)} pages ({limit_source}, cap={limit_per_feed}, changed={changed_files})"
    )
    return {
        "feeds": len(feeds),
        "series": len(series_assets),
        "episodes": len(playable_assets),
        "pages": len(pages),
        "changed": changed_files,
    }


def _load_config() -> dict[str, Any]:
    path = Path(os.getenv("VOD_ROKU_SEARCH_CONFIG", "") or DEFAULT_CONFIG_PATH)
    defaults = {
        "excludeFeedIds": [],
        "videoShowsPerFeed": 2,
        "videoEpisodesPerFeed": 100,
        "showEpisodeSampleSize": 2,
        "audioOnlyFeedSampleLimit": 12,
        "audioEpisodesPerFeed": 1,
        "shortFormMaxDurationSeconds": 900,
        "pageBytes": 2_000_000,
        "episodePicks": [],
        "queryBoosts": [],
    }
    if not path.exists():
        return defaults
    doc = read_json(path)
    if not isinstance(doc, dict):
        raise ValueError(f"Invalid Roku search config: {path}")
    out = dict(defaults)
    out.update(doc)
    return out


def _parse_csv_list(raw: str) -> list[str]:
    out: list[str] = []
    for part in str(raw or "").split(","):
        item = part.strip()
        if item:
            out.append(item)
    return out


def _resolve_limit(args_limit: int) -> tuple[int, str]:
    if int(args_limit or 0) > 0:
        return int(args_limit), "arg"
    env_limit = os.getenv("VOD_ROKU_SEARCH_LIMIT_PER_FEED", "").strip()
    if env_limit:
        try:
            n = int(env_limit)
            if n > 0:
                return n, "env"
        except ValueError:
            pass
    if os.getenv("GITHUB_ACTIONS", "").strip().lower() == "true":
        return 100, "github_actions"
    return 50, "local_default"


def _normalize_episode_picks(raw: list[Any]) -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        feed_id = str(item.get("feedId") or "").strip()
        if not feed_id:
            continue
        pick = {
            "episodeId": str(item.get("episodeId") or "").strip(),
            "episodeSlug": str(item.get("episodeSlug") or "").strip(),
        }
        if not pick["episodeId"] and not pick["episodeSlug"]:
            continue
        out.setdefault(feed_id, []).append(pick)
    return out


def _normalize_query_boosts(raw: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        query = str(item.get("query") or "").strip()
        if not query:
            continue
        terms_raw = item.get("terms") or [query]
        if isinstance(terms_raw, str):
            terms_raw = [terms_raw]
        terms = [str(term).strip().lower() for term in terms_raw if str(term).strip()]
        if not terms:
            continue
        ensure_count = max(1, min(10, int(item.get("ensureCount") or 5)))
        out.append({"query": query, "terms": terms, "ensureCount": ensure_count})
    return out


def _pick_series(shows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    ranked = []
    for show in shows or []:
        episodes = list(show.get("episodes") or [])
        if not episodes:
            continue
        ranked.append(
            (
                bool(show.get("isLeftovers")),
                -int(show.get("episodeCount") or len(episodes)),
                -int(bool(show.get("featured"))),
                str(show.get("title") or show.get("slug") or "").lower(),
                show,
            )
        )
    ranked.sort()
    return [item[-1] for item in ranked[:limit]]


def _apply_query_boosts(
    *,
    feeds: list[dict[str, Any]],
    selected_playables: list[dict[str, Any]],
    query_boosts: list[dict[str, Any]],
) -> dict[str, Any]:
    selected_keys = {(entry["feed"]["id"], _episode_key(entry["episode"])) for entry in selected_playables if _episode_key(entry["episode"])}
    corpus = []
    for feed in feeds:
        if not feed["hasVideo"]:
            continue
        for ep in feed["episodes"]:
            key = _episode_key(ep)
            if not key:
                continue
            corpus.append(
                {
                    "feed": feed,
                    "episode": ep,
                    "key": (feed["id"], key),
                    "titleText": _norm_text(str(ep.get("title") or "")),
                    "descText": _norm_text(str(ep.get("descriptionShort") or "")),
                    "metaText": _norm_text(" ".join([str(ep.get("title") or ""), str(ep.get("descriptionShort") or "")])),
                    "dateText": str(ep.get("dateText") or ""),
                }
            )

    added = 0
    shortfalls: list[tuple[str, int, int]] = []
    for boost in query_boosts:
        query = boost["query"]
        terms = boost["terms"]
        ensure_count = int(boost["ensureCount"])

        covered = 0
        matches = []
        for cand in corpus:
            score = _query_match_score(terms=terms, candidate=cand)
            if score <= 0:
                continue
            matches.append((score, cand))
            if cand["key"] in selected_keys:
                covered += 1

        if covered < ensure_count:
            matches.sort(
                key=lambda item: (
                    item[0],
                    item[1]["dateText"],
                    str(item[1]["feed"]["source"].get("title") or item[1]["feed"]["id"]).lower(),
                    item[1]["key"][1],
                ),
                reverse=True,
            )
            used_feeds: set[str] = set()
            for diversify in (True, False):
                if covered >= ensure_count:
                    break
                for _, cand in matches:
                    if covered >= ensure_count:
                        break
                    if cand["key"] in selected_keys:
                        continue
                    fid = cand["feed"]["id"]
                    if diversify and fid in used_feeds:
                        continue
                    selected_playables.append({"feed": cand["feed"], "episode": cand["episode"]})
                    selected_keys.add(cand["key"])
                    used_feeds.add(fid)
                    covered += 1
                    added += 1

        if covered < ensure_count:
            shortfalls.append((query, covered, ensure_count))

    return {"added": added, "queries": len(query_boosts), "shortfalls": shortfalls}


def _pick_video_feed_episodes(
    *,
    episodes: list[dict[str, Any]],
    explicit_picks: list[dict[str, Any]],
    per_feed_limit: int,
) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(ep: dict[str, Any]) -> None:
        key = _episode_key(ep)
        if not key or key in seen or len(chosen) >= per_feed_limit:
            return
        seen.add(key)
        chosen.append(ep)

    for ep in explicit_picks:
        add(ep)

    for ep in episodes:
        add(ep)

    return chosen[:per_feed_limit]


def _episodes_recent_first(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        episodes,
        key=lambda ep: (
            str(ep.get("dateText") or ""),
            str(ep.get("title") or "").lower(),
            _episode_key(ep),
        ),
        reverse=True,
    )


def _find_explicit_episode_picks(episodes: list[dict[str, Any]], picks: list[dict[str, str]]) -> list[dict[str, Any]]:
    by_id = {str(ep.get("id") or "").strip(): ep for ep in episodes if str(ep.get("id") or "").strip()}
    by_slug = {str(ep.get("slug") or "").strip(): ep for ep in episodes if str(ep.get("slug") or "").strip()}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pick in picks:
        ep = None
        if pick.get("episodeId"):
            ep = by_id.get(pick["episodeId"])
        if ep is None and pick.get("episodeSlug"):
            ep = by_slug.get(pick["episodeSlug"])
        key = _episode_key(ep or {})
        if ep is not None and key and key not in seen:
            seen.add(key)
            out.append(ep)
    return out


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def _query_match_score(*, terms: list[str], candidate: dict[str, Any]) -> float:
    title = candidate["titleText"]
    desc = candidate["descText"]
    meta = candidate["metaText"]
    score = 0.0
    matched = False
    for term in terms:
        if not term:
            continue
        if term in title:
            score += 140 + len(term)
            matched = True
        elif term in desc:
            score += 70 + len(term)
            matched = True
        elif term in meta:
            score += 30 + len(term)
            matched = True
    if not matched:
        return 0.0
    date_text = candidate["dateText"]
    if len(date_text) >= 10 and date_text[:10].replace("-", "").isdigit():
        score += int(date_text[:10].replace("-", "")) / 10_000_000_000
    return score


def _pick_interesting_episodes(episodes: list[dict[str, Any]], *, max_items: int) -> list[dict[str, Any]]:
    ranked = sorted(
        episodes,
        key=lambda ep: (
            _episode_interest_score(ep),
            str(ep.get("dateText") or ""),
            str(ep.get("title") or "").lower(),
            _episode_key(ep),
        ),
        reverse=True,
    )
    return ranked[:max_items]


def _episode_interest_score(ep: dict[str, Any]) -> float:
    title = str(ep.get("title") or "").strip()
    desc = str(ep.get("descriptionShort") or "") or short_description(str(ep.get("descriptionHtml") or ""), max_chars=180)
    duration = int(ep.get("durationSec") or 0)
    score = 0.0

    if 24 <= len(title) <= 110:
        score += 20
    elif len(title) >= 12:
        score += 8

    words = len([w for w in re.split(r"\s+", title) if w])
    if 4 <= words <= 16:
        score += 12

    if ":" in title or " - " in title:
        score += 6
    if desc and len(desc) >= 40:
        score += 10
    if ep.get("imageUrl"):
        score += 5
    if ep.get("transcripts") or ep.get("transcriptsAll"):
        score += 3
    if duration >= 300:
        score += min(12, duration / 900)

    if _GENERIC_TITLE_RE.search(title):
        score -= 12
    if _ONLY_DATE_RE.match(title):
        score -= 20

    date_text = str(ep.get("dateText") or "")
    if len(date_text) >= 10 and date_text[:10].replace("-", "").isdigit():
        score += int(date_text[:10].replace("-", "")) / 10_000_000_000

    return score


def _series_asset_id(feed_id: str, show_slug: str) -> str:
    return f"series:{feed_id}:{show_slug}"


def _episode_asset_id(feed_id: str, ep: dict[str, Any]) -> str:
    slug = str(ep.get("slug") or "").strip()
    if slug:
        return f"item:{feed_id}:{slug}"
    ep_id = str(ep.get("id") or "").strip()
    if ep_id:
        return f"item:{feed_id}:{sha1(ep_id.encode('utf-8')).hexdigest()[:12]}"
    raw = json.dumps(ep, ensure_ascii=False, sort_keys=True)
    return f"item:{feed_id}:{sha1(raw.encode('utf-8')).hexdigest()[:12]}"


def _episode_key(ep: dict[str, Any]) -> str:
    return str(ep.get("id") or ep.get("slug") or "").strip()


def _episode_numbers_for_show(show: dict[str, Any]) -> dict[str, int]:
    episodes = list(show.get("episodes") or [])
    ordered = sorted(
        episodes,
        key=lambda ep: (
            str(ep.get("dateText") or ""),
            str(ep.get("title") or "").lower(),
            _episode_key(ep),
        ),
    )
    out: dict[str, int] = {}
    for idx, ep in enumerate(ordered, start=1):
        key = _episode_key(ep)
        slug = str(ep.get("slug") or "").strip()
        if key:
            out[key] = idx
        if slug:
            out[slug] = idx
    return out


def _episode_series_ref(feed_id: str, ep: dict[str, Any], series_map: dict[tuple[str, str], tuple[str, int | None]]) -> tuple[str, int | None] | None:
    for key in (_episode_key(ep), str(ep.get("slug") or "").strip()):
        if key and (feed_id, key) in series_map:
            return series_map[(feed_id, key)]
    return None


def _build_series_asset(*, feed: dict[str, Any], show: dict[str, Any], series_id: str) -> dict[str, Any]:
    feed_title = str(feed["source"].get("title") or feed["id"])
    title = str(show.get("title_full") or show.get("title") or feed_title).strip() or feed_title
    desc = str(show.get("description") or "").strip()
    image_url = _first_http_url(show.get("artworkUrl"), feed["manifest"].get("channelImageUrl"))
    newest_ep = _episodes_recent_first(list(show.get("episodes") or []))[:1]
    newest_date = str((newest_ep[0].get("dateText") if newest_ep else "") or "").strip()
    asset: dict[str, Any] = {
        "id": series_id,
        "type": "series",
        "titles": [{"value": title[:200]}],
        "tags": [feed["id"], str(feed["source"].get("category") or "other")],
    }
    if newest_date:
        asset["releaseDate"] = newest_date[:10]
        if len(newest_date) >= 4 and newest_date[:4].isdigit():
            asset["releaseYear"] = int(newest_date[:4])
    genres = _map_genres(feed_category=str(feed["source"].get("category") or ""), extra_terms=list(show.get("categories") or []))
    if genres:
        asset["genres"] = genres
    if desc:
        asset["shortDescriptions"] = [{"value": short_description(desc, max_chars=200)}]
        asset["longDescriptions"] = [{"value": short_description(desc, max_chars=500)}]
    if image_url:
        asset["images"] = [{"type": "main", "url": image_url}]
    return asset


def _build_playable_asset(
    *,
    feed: dict[str, Any],
    ep: dict[str, Any],
    asset_id: str,
    series_ref: tuple[str, int | None] | None,
    short_form_max_duration: int,
) -> dict[str, Any]:
    media = ep.get("media") if isinstance(ep.get("media"), dict) else {}
    title = str(ep.get("title") or "Untitled").strip() or "Untitled"
    date_text = str(ep.get("dateText") or "").strip()
    desc_short = str(ep.get("descriptionShort") or "").strip()
    desc_long = short_description(str(ep.get("descriptionHtml") or desc_short), max_chars=500) if ep.get("descriptionHtml") else desc_short
    duration_sec = int(ep.get("durationSec") or 0) or None
    image_url = _first_http_url(ep.get("imageUrl"), feed["manifest"].get("channelImageUrl"))
    is_video = bool(media.get("pickedIsVideo") or media.get("hasVideoInFeed"))

    if series_ref is not None:
        asset_type = "episode"
    elif duration_sec and duration_sec <= short_form_max_duration:
        asset_type = "shortForm"
    else:
        asset_type = "tvSpecial"

    asset: dict[str, Any] = {
        "id": asset_id,
        "type": asset_type,
        "titles": [{"value": title[:200]}],
        "content": {
            "playOptions": [
                {
                    "license": "free",
                    "quality": "hd" if is_video else "sd",
                    "playId": _build_play_id(feed["id"], ep),
                }
            ]
        },
        "tags": [feed["id"], str(feed["source"].get("category") or "other")],
    }
    if desc_short:
        asset["shortDescriptions"] = [{"value": short_description(desc_short, max_chars=200)}]
    if desc_long:
        asset["longDescriptions"] = [{"value": short_description(desc_long, max_chars=500)}]
    if date_text:
        asset["releaseDate"] = date_text[:10]
        if len(date_text) >= 4 and date_text[:4].isdigit():
            asset["releaseYear"] = int(date_text[:4])
    if image_url:
        asset["images"] = [{"type": "main", "url": image_url}]
    if duration_sec:
        asset["durationInSeconds"] = duration_sec
    genres = _map_genres(feed_category=str(feed["source"].get("category") or ""), extra_terms=[])
    if genres:
        asset["genres"] = genres
    if series_ref is not None:
        series_id, episode_number = series_ref
        ep_info: dict[str, Any] = {"seriesId": series_id, "episodeNumber": int(episode_number or 1)}
        asset["episodeInfo"] = ep_info
    return asset


def _build_play_id(feed_id: str, ep: dict[str, Any]) -> str:
    slug = str(ep.get("slug") or "").strip()
    if slug:
        return f"{feed_id}/{slug}"
    ep_id = str(ep.get("id") or "").strip()
    if ep_id:
        return f"{feed_id}/{ep_id}"
    return feed_id


def _asset_sort_key(asset: dict[str, Any]) -> tuple[str, int, str, str]:
    return (
        str(asset.get("releaseDate") or ""),
        1 if str(asset.get("type") or "") in {"episode", "tvSpecial", "shortForm"} else 0,
        str(asset.get("titles", [{}])[0].get("value") or "").lower(),
        str(asset.get("id") or ""),
    )


def _map_genres(*, feed_category: str, extra_terms: list[str]) -> list[str]:
    terms = " ".join([feed_category] + extra_terms).lower()
    out: list[str] = []
    mapping = [
        ("faith", ("church", "faith", "christian", "sermon", "bible", "religion", "religious")),
        ("technology", ("tech", "technology", "twit", "vodcast", "computer", "ai")),
        ("news", ("news", "current affairs")),
        ("music", ("music", "worship")),
        ("talk", ("talk", "podcast", "conversation")),
        ("educational", ("education", "educational")),
        ("interview", ("interview",)),
    ]
    for genre, needles in mapping:
        if any(token in terms for token in needles) and genre not in out:
            out.append(genre)
    return out[:3]


def _first_http_url(*values: Any) -> str | None:
    for value in values:
        s = str(value or "").strip()
        if s and _HTTP_URL_RE.match(s):
            return s
    return None


def _paginate_assets(
    *,
    assets: list[dict[str, Any]],
    page_bytes: int,
    site_origin: str,
    base_path: str,
) -> list[dict[str, Any]]:
    base_doc = {"version": "1", "defaultLanguage": "en", "assets": []}
    if not site_origin:
        return [{**base_doc, "assets": assets}]

    pages: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for asset in assets:
        candidate = current + [asset]
        doc = {**base_doc, "assets": candidate}
        size = len(_serialize_page(doc).encode("utf-8"))
        if current and size > page_bytes:
            pages.append(current)
            current = [asset]
        else:
            current = candidate
    if current:
        pages.append(current)

    out: list[dict[str, Any]] = []
    for idx, page_assets in enumerate(pages, start=1):
        doc = {**base_doc, "assets": page_assets}
        if idx < len(pages):
            doc["nextPageUrl"] = _page_url(site_origin=site_origin, base_path=base_path, page_number=idx + 1)
        out.append(doc)
    return out


def _write_pages(
    *,
    out_dir: Path,
    pages: list[dict[str, Any]],
    site_origin: str,
    base_path: str,
) -> int:
    pages_dir = out_dir / ROKU_SEARCH_DIR
    pages_dir.mkdir(parents=True, exist_ok=True)
    changed = 0

    root_path = out_dir / ROKU_SEARCH_ROOT
    if _write_text_if_changed(root_path, _serialize_page(pages[0])):
        changed += 1

    keep: set[Path] = set()
    for idx, page in enumerate(pages[1:], start=2):
        page_path = pages_dir / f"roku-search-{idx}.json"
        keep.add(page_path)
        if _write_text_if_changed(page_path, _serialize_page(page)):
            changed += 1

    for old in pages_dir.glob("roku-search-*.json"):
        if old not in keep:
            old.unlink(missing_ok=True)
    return changed


def _page_url(*, site_origin: str, base_path: str, page_number: int) -> str:
    rel = ROKU_SEARCH_ROOT if page_number == 1 else f"{ROKU_SEARCH_DIR}/roku-search-{page_number}.json"
    return f"{site_origin}{base_path}{rel}"


def _serialize_page(doc: dict[str, Any]) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


def _write_text_if_changed(path: Path, text: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except FileNotFoundError:
        pass
    path.write_text(text, encoding="utf-8")
    return True
