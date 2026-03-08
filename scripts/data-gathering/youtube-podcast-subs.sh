#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_FILE="${SOURCE_FILE:-$SCRIPT_DIR/youtube-podcast-sources.tsv}"
OUT_DIR="${OUT_DIR:-podcast-transcripts/youtube}"
ARCHIVE_FILE="${ARCHIVE_FILE:-$OUT_DIR/.yt-dlp-archive.txt}"
PLAYLIST_END="${PLAYLIST_END:-}"
SUB_LANGS="${SUB_LANGS:-en.*,en}"
DATEAFTER="${DATEAFTER:-}"
YTDLP_BIN="${YTDLP_BIN:-yt-dlp}"
SLEEP_INTERVAL="${SLEEP_INTERVAL:-2}"
MAX_SLEEP_INTERVAL="${MAX_SLEEP_INTERVAL:-5}"

usage() {
  cat <<'EOF'
Usage:
  bash scripts/data-gathering/youtube-podcast-subs.sh [options] [-- extra yt-dlp args]

Options:
  --source-file PATH    Override the TSV source manifest.
  --out-dir PATH        Output directory. Default: podcast-transcripts/youtube
  --archive-file PATH   Download archive path. Default: <out-dir>/.yt-dlp-archive.txt
  --playlist-end N      Limit items per channel/playlist. Default: all items
  --slug SLUG           Only run one slug. Repeatable.
  --dateafter DATE      Pass through to yt-dlp, e.g. 20250101
  -h, --help            Show this help.

Environment overrides:
  YTDLP_BIN, SOURCE_FILE, OUT_DIR, ARCHIVE_FILE, PLAYLIST_END,
  SUB_LANGS, DATEAFTER, SLEEP_INTERVAL, MAX_SLEEP_INTERVAL

Examples:
  bash scripts/data-gathering/youtube-podcast-subs.sh
  bash scripts/data-gathering/youtube-podcast-subs.sh --playlist-end 25 --slug lex-fridman
  DATEAFTER=20250101 bash scripts/data-gathering/youtube-podcast-subs.sh -- --cookies-from-browser firefox
EOF
}

declare -a FILTER_SLUGS=()
declare -a EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-file)
      SOURCE_FILE="$2"
      shift 2
      ;;
    --out-dir)
      OUT_DIR="$2"
      shift 2
      ;;
    --archive-file)
      ARCHIVE_FILE="$2"
      shift 2
      ;;
    --playlist-end)
      PLAYLIST_END="$2"
      shift 2
      ;;
    --slug)
      FILTER_SLUGS+=("$2")
      shift 2
      ;;
    --dateafter)
      DATEAFTER="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      EXTRA_ARGS=("$@")
      break
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if ! command -v "$YTDLP_BIN" >/dev/null 2>&1; then
  echo "Missing yt-dlp binary: $YTDLP_BIN" >&2
  exit 1
fi

if [[ ! -f "$SOURCE_FILE" ]]; then
  echo "Source manifest not found: $SOURCE_FILE" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"
touch "$ARCHIVE_FILE"

slug_selected() {
  local slug="$1"
  if [[ ${#FILTER_SLUGS[@]} -eq 0 ]]; then
    return 0
  fi
  local selected
  for selected in "${FILTER_SLUGS[@]}"; do
    if [[ "$selected" == "$slug" ]]; then
      return 0
    fi
  done
  return 1
}

run_source() {
  local slug="$1"
  local kind="$2"
  local url="$3"
  local note="$4"

  local target_dir="$OUT_DIR/$slug"
  mkdir -p "$target_dir"

  local -a cmd=(
    "$YTDLP_BIN"
    --ignore-errors
    --continue
    --no-overwrites
    --skip-download
    --yes-playlist
    --write-subs
    --write-auto-subs
    --sub-langs "$SUB_LANGS"
    --sub-format "vtt/srt/best"
    --convert-subs vtt
    --download-archive "$ARCHIVE_FILE"
    --sleep-interval "$SLEEP_INTERVAL"
    --max-sleep-interval "$MAX_SLEEP_INTERVAL"
    --output "$target_dir/%(upload_date>%Y-%m-%d)s - %(title).180B [%(id)s].%(ext)s"
  )

  if [[ -n "$PLAYLIST_END" ]]; then
    cmd+=(--playlist-end "$PLAYLIST_END")
  fi

  if [[ -n "$DATEAFTER" ]]; then
    cmd+=(--dateafter "$DATEAFTER")
  fi

  cmd+=("${EXTRA_ARGS[@]}")
  cmd+=("$url")

  printf '\n[%s] %s\n' "$slug" "$note"
  printf '[%s] %s %s\n' "$slug" "$kind" "$url"
  "${cmd[@]}"
}

while IFS=$'\t' read -r slug kind url note; do
  if [[ -z "${slug:-}" || "${slug:0:1}" == "#" ]]; then
    continue
  fi

  if ! slug_selected "$slug"; then
    continue
  fi

  run_source "$slug" "$kind" "$url" "${note:-}"
done < "$SOURCE_FILE"
