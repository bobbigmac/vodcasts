#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python}"
command -v "$PY" >/dev/null 2>&1 || PY=python3

cmd="${1:-help}"
shift || true

case "$cmd" in
  analyze-spacetime) "$PY" "$ROOT/analyze_spacetime_plan.py" "$@" ;;
  apply) "$PY" "$ROOT/apply_edit_plan.py" "$@" ;;
  help)
    echo "Markdown Video Editor"
    echo ""
    echo "Usage: bash scripts/markdown-video-editor/mve.sh <cmd> [args...]"
    echo "Commands: analyze-spacetime, apply"
    echo ""
    echo "Examples:"
    echo "  bash scripts/markdown-video-editor/mve.sh analyze-spacetime --input in/source.mp4 --output out/source.edit.md"
    echo "  bash scripts/markdown-video-editor/mve.sh apply --plan out/source.edit.md --output out/source.out.mp4"
    exit 0
    ;;
  *)
    echo "Unknown command: $cmd" >&2
    exit 2
    ;;
esac
