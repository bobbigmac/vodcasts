"""Compatibility import surface for markdown-video-editor helpers."""
from __future__ import annotations

import importlib.util
from pathlib import Path


_TARGET = Path(__file__).resolve().parents[2] / "markdown-video-editor" / "_lib.py"
_SPEC = importlib.util.spec_from_file_location("markdown_video_editor_lib", _TARGET)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load markdown-video-editor helpers from {_TARGET}")
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

for _name in dir(_MODULE):
    if _name.startswith("__"):
        continue
    globals()[_name] = getattr(_MODULE, _name)
