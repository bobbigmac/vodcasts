"""Shorts-experiment helpers. Reuses parent sermon-clipper _lib where possible."""
from __future__ import annotations

import sys
from pathlib import Path

_PARENT = Path(__file__).resolve().parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

# Import from parent sermon-clipper
from _lib import (  # noqa: F401
    clip_has_render_requirements,
    clip_id,
    clip_transcript_to_vtt,
    default_cache_dir,
    default_content_cache_dir,
    default_env,
    default_transcripts_root,
    get_episode_media_url,
    get_feed_title,
    get_source_path,
    get_transcript_path,
    load_clips_json,
    load_used_clips,
    parse_short_script,
    remove_path,
    resolve_work_dir,
    reset_directory,
    save_used_clips,
    search_segments_cached,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
