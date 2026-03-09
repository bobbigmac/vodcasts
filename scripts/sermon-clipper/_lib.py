"""Shared utilities for sermon-clipper scripts."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Add repo root for imports
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.feed_manifest import parse_feed_for_manifest
from scripts.sources import load_sources_config


def default_env() -> str:
    env_file = _REPO_ROOT / ".vodcasts-env"
    if env_file.exists():
        try:
            return env_file.read_text(encoding="utf-8").strip() or "dev"
        except Exception:
            pass
    return os.environ.get("VOD_ENV", "dev")


def default_cache_dir(env: str | None = None) -> Path:
    return _REPO_ROOT / "cache" / (env or default_env())


def default_db_path(cache_dir: Path) -> Path:
    return cache_dir / "answer-engine" / "answer_engine.sqlite"


def default_transcripts_root() -> Path:
    return _REPO_ROOT / "site" / "assets" / "transcripts"


def get_episode_media_url(cache_dir: Path, feed_slug: str, episode_slug: str) -> str | None:
    """Resolve media URL for feed/episode from cached feed XML."""
    feed_path = cache_dir / "feeds" / f"{feed_slug}.xml"
    if not feed_path.exists():
        return None
    try:
        xml_text = feed_path.read_text(encoding="utf-8", errors="replace")
        _feat, _ch, episodes, _img = parse_feed_for_manifest(
            xml_text, source_id=feed_slug, source_title=feed_slug
        )
        for ep in episodes or []:
            if not isinstance(ep, dict):
                continue
            slug = str(ep.get("slug") or "").strip()
            if slug != episode_slug:
                continue
            media = ep.get("media")
            if isinstance(media, dict) and media.get("url"):
                return str(media["url"]).strip()
            return None
    except Exception:
        pass
    return None


def load_clips_json(path: Path) -> list[dict]:
    """Load clips from JSON file."""
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "clips" in data:
        return data["clips"]
    return []


def clip_id(feed: str, episode_slug: str, start_sec: float) -> str:
    """Unique id for a clip (feed + episode + start)."""
    return f"{feed}|{episode_slug}|{start_sec:.1f}"


def load_used_clips(registry_path: Path) -> set[str]:
    """Load set of clip_ids already used in previous videos."""
    if not registry_path.exists():
        return set()
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
        ids = data.get("clip_ids") or []
        return set(str(x) for x in ids)
    except Exception:
        return set()


def save_used_clips(registry_path: Path, clip_ids: set[str], video_title: str = "") -> None:
    """Append clip_ids to the used-clips registry."""
    existing_data = {}
    if registry_path.exists():
        try:
            existing_data = json.loads(registry_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    existing = set(existing_data.get("clip_ids") or [])
    existing.update(clip_ids)
    videos = list(existing_data.get("videos") or [])
    if video_title:
        videos.append({"title": video_title, "clips": list(clip_ids)})
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps({"clip_ids": sorted(existing), "videos": videos}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_transcript_path(transcripts_root: Path, feed: str, episode_slug: str) -> Path | None:
    """Resolve transcript file path for feed/episode. Checks .vtt then .srt."""
    feed_dir = transcripts_root / feed
    for ext in (".vtt", ".srt"):
        p = feed_dir / f"{episode_slug}{ext}"
        if p.exists():
            return p
    return None


def clip_transcript_to_vtt(
    transcript_path: Path,
    start_sec: float,
    end_sec: float,
    out_path: Path,
) -> bool:
    """Extract cues in [start_sec, end_sec], adjust timestamps to be relative to clip start, write VTT."""
    ext = transcript_path.suffix.lower()
    cues: list[tuple[float, float, str]] = []
    try:
        if ext == ".vtt":
            import webvtt
            v = webvtt.read(str(transcript_path))
            for c in getattr(v, "captions", []) or []:
                s = _parse_vtt_time(str(getattr(c, "start", "") or ""))
                e = _parse_vtt_time(str(getattr(c, "end", "") or ""))
                if e <= s:
                    continue
                txt = str(getattr(c, "text", "") or "").strip()
                if not txt:
                    continue
                # Cue overlaps clip if it ends after start and starts before end
                if e <= start_sec or s >= end_sec:
                    continue
                new_s = max(0.0, s - start_sec)
                new_e = min(end_sec - start_sec, e - start_sec)
                cues.append((new_s, new_e, txt))
        elif ext == ".srt":
            import pysrt
            subs = pysrt.open(str(transcript_path), encoding="utf-8", error_handling=getattr(pysrt, "ERROR_LOG", 1))
            for s in subs or []:
                start_ms = getattr(getattr(s, "start", None), "ordinal", 0) or 0
                end_ms = getattr(getattr(s, "end", None), "ordinal", 0) or 0
                s_sec = start_ms / 1000.0
                e_sec = end_ms / 1000.0
                if e_sec <= s_sec:
                    continue
                txt = str(getattr(s, "text", "") or "").strip()
                if not txt:
                    continue
                if e_sec <= start_sec or s_sec >= end_sec:
                    continue
                new_s = max(0.0, s_sec - start_sec)
                new_e = min(end_sec - start_sec, e_sec - start_sec)
                cues.append((new_s, new_e, txt))
        else:
            return False
    except Exception:
        return False
    if not cues:
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["WEBVTT", ""]
    for i, (s, e, txt) in enumerate(cues, 1):
        lines.append(f"{i}")
        lines.append(f"{_sec_to_vtt(s)} --> {_sec_to_vtt(e)}")
        lines.append(txt)
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return True


def _parse_vtt_time(s: str) -> float:
    s = (s or "").strip().replace(",", ".")
    parts = s.split(":")
    if len(parts) == 3:
        h, m, sec = parts
        return int(h) * 3600 + int(m) * 60 + float(sec)
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return 0.0


def _sec_to_vtt(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h:02d}:{m:02d}:{int(s):02d}.{int((s % 1) * 1000):03d}"


def get_feed_title(env: str, feed_slug: str) -> str:
    """Resolve human-readable feed title from config."""
    cfg_path = _REPO_ROOT / "feeds" / f"{env}.md"
    if not cfg_path.exists():
        return feed_slug
    try:
        cfg = load_sources_config(cfg_path)
        for s in cfg.sources or []:
            if str(s.id) == feed_slug:
                return str(s.title or feed_slug)
    except Exception:
        pass
    return feed_slug
