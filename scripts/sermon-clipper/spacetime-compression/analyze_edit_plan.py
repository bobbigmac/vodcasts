"""Compatibility wrapper for the markdown-video-editor spacetime analyzer."""
from __future__ import annotations

import runpy
from pathlib import Path


def main() -> None:
    target = Path(__file__).resolve().parents[2] / "markdown-video-editor" / "analyze_spacetime_plan.py"
    runpy.run_path(str(target), run_name="__main__")


if __name__ == "__main__":
    main()
