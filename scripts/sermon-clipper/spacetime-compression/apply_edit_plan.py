"""Compatibility wrapper for the markdown-video-editor plan applier."""
from __future__ import annotations

import runpy
from pathlib import Path


def main() -> None:
    target = Path(__file__).resolve().parents[2] / "markdown-video-editor" / "apply_edit_plan.py"
    runpy.run_path(str(target), run_name="__main__")


if __name__ == "__main__":
    main()
