#!/usr/bin/env bash
# Sermon Clipper - Bash entrypoint
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AE_ROOT="$(cd "$ROOT/../answer-engine" && pwd)"
PY="${AE_ROOT}/.venv/bin/python"
[[ -x "$PY" ]] || PY=python

cmd="${1:-help}"
shift || true

case "$cmd" in
  search) exec "$PY" "$ROOT/search_clips.py" "$@" ;;
  write)  exec "$PY" "$ROOT/write_script.py" "$@" ;;
  cards)  python "$ROOT/make_title_cards.py" "$@" ;;
  render) python "$ROOT/render_video.py" "$@" ;;
  help)
    echo "Sermon Clipper - generate video essays from church feed clips."
    echo ""
    echo "Usage: bash scripts/sermon-clipper/sc.sh <cmd> [args...]"
    echo "Commands: search, write, cards, render"
    echo ""
    echo "Examples:"
    echo "  bash scripts/sermon-clipper/sc.sh search --theme forgiveness --output out/clips.json"
    echo "  bash scripts/sermon-clipper/sc.sh write --theme forgiveness --clips out/clips.json --output out/video.md"
    echo "  bash scripts/sermon-clipper/sc.sh cards --script out/video.md --output out/title-cards"
    echo "  bash scripts/sermon-clipper/sc.sh render --script out/video.md --output out/video.mp4 --title-cards out/title-cards"
    exit 0
    ;;
  *)
    echo "Unknown command: $cmd" >&2
    exit 2
    ;;
esac
