"""Shared utilities for sermon-clipper scripts."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

# Add repo root for imports
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.feed_manifest import parse_feed_for_manifest
from scripts.sources import load_sources_config


def _slugify_query(q: str) -> str:
    """Safe filename from query string."""
    s = re.sub(r"[^a-z0-9]+", "-", (q or "").lower().strip()).strip("-")
    return s[:64] if s else "query"


def safe_slug(value: str, default: str = "item", max_len: int = 64) -> str:
    """Filesystem-safe slug."""
    s = re.sub(r"[^a-z0-9]+", "-", (value or "").lower().strip()).strip("-")
    return (s[:max_len] or default).strip("-") or default


def search_segments_cached(
    cache_dir: Path,
    db_path: Path,
    q: str,
    limit: int = 400,
    candidates: int = 400,
    include_noncontent: bool = False,
    no_cache: bool = False,
):
    """Call search_segments, caching the raw payload by theme to avoid repeated queries."""
    from answer_engine_lib import search_segments

    key = hashlib.sha256(
        f"{q}|{limit}|{candidates}|{include_noncontent}".encode("utf-8")
    ).hexdigest()[:16]
    slug = _slugify_query(q)
    cache_subdir = cache_dir / "sermon-clipper" / "query-cache"
    cache_path = cache_subdir / f"{slug}-{key}.json"

    if not no_cache and cache_path.exists():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            return data
        except Exception:
            pass

    payload = search_segments(
        db_path=db_path,
        q=q,
        limit=limit,
        candidates=candidates,
        include_noncontent=include_noncontent,
    )

    if not payload.get("error"):
        cache_subdir.mkdir(parents=True, exist_ok=True)
        try:
            cache_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=0),
                encoding="utf-8",
            )
        except Exception:
            pass

    return payload


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


def default_content_cache_dir(env: str | None = None) -> Path:
    """Project-local shared cache for downloaded source videos. Clear occasionally in production."""
    return default_cache_dir(env) / "sermon-clipper" / "content"


def default_work_root() -> Path:
    """Scratch work root kept inside sermon-clipper, not next to user outputs."""
    return Path(__file__).resolve().parent / ".work"


def resolve_work_dir(
    kind: str,
    output_path: Path,
    explicit_work_dir: str = "",
) -> tuple[Path, bool]:
    """Resolve work dir. Auto-generated work dirs live under scripts/sermon-clipper/.work/."""
    if explicit_work_dir:
        return Path(explicit_work_dir).resolve(), False
    digest = hashlib.sha1(str(output_path.resolve()).encode("utf-8")).hexdigest()[:10]
    work_dir = default_work_root() / safe_slug(kind, default="render") / f"{safe_slug(output_path.stem, default='output')}-{digest}"
    return work_dir, True


def reset_directory(path: Path) -> Path:
    """Remove and recreate a directory."""
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


def remove_path(path: Path) -> None:
    """Remove file or directory if present."""
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def get_source_path(content_cache: Path, feed: str, episode_slug: str) -> Path:
    """Path for cached source video. Episode slug sanitized for filesystem."""
    safe = re.sub(r"[^\w\-.]", "_", (episode_slug or "").strip())[:120]
    return content_cache / f"{feed}_{safe}.mp4"


def default_db_path(cache_dir: Path) -> Path:
    return cache_dir / "answer-engine" / "answer_engine.sqlite"


def default_transcripts_root() -> Path:
    return _REPO_ROOT / "site" / "assets" / "transcripts"


def get_episode_media_url(cache_dir: Path, feed_slug: str, episode_slug: str) -> str | None:
    """Resolve media URL for feed/episode from cached feed XML."""
    info = get_episode_media_info(cache_dir, feed_slug, episode_slug)
    return info.get("url") if info else None


def get_episode_media_info(cache_dir: Path, feed_slug: str, episode_slug: str) -> dict | None:
    """Resolve media URL and video flag from cached feed XML. Use pickedIsVideo to skip audio-only."""
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
                return {
                    "url": str(media["url"]).strip(),
                    "pickedIsVideo": bool(media.get("pickedIsVideo")),
                }
            return None
    except Exception:
        pass
    return None


def clip_has_render_requirements(
    cache_dir: Path,
    transcripts_root: Path,
    feed_slug: str,
    episode_slug: str,
    require_video: bool = True,
    require_transcript: bool = True,
) -> bool:
    """Return True when a clip is renderable with the requested constraints."""
    media_info = get_episode_media_info(cache_dir, feed_slug, episode_slug)
    if not media_info or not media_info.get("url"):
        return False
    if require_video and not media_info.get("pickedIsVideo"):
        return False
    if require_transcript and not get_transcript_path(transcripts_root, feed_slug, episode_slug):
        return False
    return True


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
                if e <= start_sec or s >= end_sec:
                    continue
                new_s = max(0.0, s - start_sec)
                new_e = min(end_sec - start_sec, e - start_sec)
                cues.append((new_s, new_e, txt))
        elif ext == ".srt":
            import pysrt

            subs = pysrt.open(
                str(transcript_path),
                encoding="utf-8",
                error_handling=getattr(pysrt, "ERROR_LOG", 1),
            )
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


def parse_markdown_sections(text: str) -> list[dict]:
    """Parse ##-headed markdown sections in order."""
    sections: list[dict] = []
    current_type: str | None = None
    current_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        line_stripped = line.strip()
        if line_stripped.startswith("## "):
            if current_type is not None:
                sections.append(
                    {"type": current_type, "content": "\n".join(current_lines).strip()}
                )
            current_type = line_stripped[3:].strip().lower()
            current_lines = []
            continue
        if current_type is not None:
            current_lines.append(line)
    if current_type is not None:
        sections.append(
            {"type": current_type, "content": "\n".join(current_lines).strip()}
        )
    return sections


def parse_key_value_block(text: str) -> dict[str, str]:
    """Parse simple key: value blocks, preserving continuation lines."""
    data: dict[str, str] = {}
    current_key: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if ":" in line and not line.startswith((" ", "\t")):
            key, value = line.split(":", 1)
            current_key = key.strip()
            data[current_key] = value.strip()
            continue
        if current_key:
            data[current_key] = f"{data[current_key]}\n{line.strip()}".strip()
    return data


def parse_long_form_script(script_path: Path) -> dict:
    """Parse a long-form sermon clipper script."""
    text = script_path.read_text(encoding="utf-8", errors="replace")
    sections = parse_markdown_sections(text)
    items: list[dict] = []
    metadata: dict[str, str] = {}
    transition_idx = 0
    for section in sections:
        section_type = section["type"]
        content = section["content"]
        if section_type == "metadata":
            metadata = parse_key_value_block(content)
            continue
        if section_type in {"intro", "outro"}:
            items.append({"type": section_type, "text": content.strip()})
            continue
        if section_type == "title_card":
            kv = parse_key_value_block(content)
            items.append(
                {
                    "type": "title_card",
                    "id": kv.get("id", ""),
                    "text": kv.get("text", ""),
                }
            )
            continue
        if section_type == "transition":
            transition_idx += 1
            items.append(
                {
                    "type": "title_card",
                    "id": f"transition_{transition_idx}",
                    "text": content.strip(),
                }
            )
            continue
        if section_type == "clip":
            kv = parse_key_value_block(content)
            items.append(
                {
                    "type": "clip",
                    "feed": kv.get("feed"),
                    "episode": kv.get("episode"),
                    "start_sec": float(kv.get("start_sec") or 0),
                    "end_sec": float(kv.get("end_sec") or 0),
                    "quote": kv.get("quote", ""),
                    "episode_title": kv.get("episode_title") or "",
                    "feed_title": kv.get("feed_title") or "",
                }
            )
    return {"metadata": metadata, "items": items}


def parse_short_script(script_path: Path) -> dict:
    """Parse a shorts script."""
    text = script_path.read_text(encoding="utf-8", errors="replace")
    sections = parse_markdown_sections(text)
    items: list[dict] = []
    metadata: dict[str, str] = {}
    for section in sections:
        section_type = section["type"]
        content = section["content"]
        if section_type == "metadata":
            metadata = parse_key_value_block(content)
            continue
        if section_type in {"intro", "outro"}:
            items.append({"type": section_type, "text": content.strip()})
            continue
        if section_type == "clip":
            kv = parse_key_value_block(content)
            items.append(
                {
                    "type": "clip",
                    "feed": kv.get("feed"),
                    "episode": kv.get("episode"),
                    "start_sec": float(kv.get("start_sec") or 0),
                    "end_sec": float(kv.get("end_sec") or 0),
                    "quote": kv.get("quote", ""),
                    "context": kv.get("context", ""),
                    "decorators": kv.get("decorators", ""),
                    "episode_title": kv.get("episode_title") or "",
                    "feed_title": kv.get("feed_title") or "",
                }
            )
    return {"metadata": metadata, "items": items}


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
