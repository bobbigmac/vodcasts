#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${ROOT}/.venv"
PY="${VENV}/bin/python"
TORCH_INDEX="https://download.pytorch.org/whl/cu128"
TORCH_SPEC="torch==2.10.0+cu128"

ensure_venv() {
  if [[ ! -x "${PY}" ]]; then
    python3 -m venv "${VENV}"
    "${PY}" -m pip install --upgrade pip
  fi

  local req_hash
  req_hash="$( (cat "${ROOT}/requirements.txt"; echo "${TORCH_SPEC}") | sha256sum | awk '{print $1}')"
  local stamp="${VENV}/.deps.sha256"
  local cur=""
  if [[ -f "${stamp}" ]]; then
    cur="$(cat "${stamp}" || true)"
  fi
  if [[ "${cur}" != "${req_hash}" ]]; then
    "${PY}" -m pip install -r "${ROOT}/requirements.txt"
    echo "${req_hash}" > "${stamp}"
  fi

  if ! "${PY}" -c 'import torch, sys; sys.exit(0 if (torch.version.cuda and torch.cuda.is_available()) else 1)' >/dev/null 2>&1; then
    echo "[chapter-generation] installing CUDA torch (cu128) ... (large download)" >&2
    "${PY}" -m pip install --index-url "${TORCH_INDEX}" "${TORCH_SPEC}"
  fi
}

cmd="${1:-}"
shift || true

case "${cmd}" in
  ""|-h|--help|help)
    cat <<'EOF'
Chapter-generation helper.

Usage:
  bash scripts/chapter-generation/cg.sh chapters [make_chapters.py args...]
  bash scripts/chapter-generation/cg.sh serve-llm [serve_llm.py args...]
  bash scripts/chapter-generation/cg.sh pip [pip args...]

Examples:
  bash scripts/chapter-generation/cg.sh chapters
  bash scripts/chapter-generation/cg.sh chapters --transcript calvary-chapel-anne-arundel/2026-01-04-ephesians-1-7-10-848zvp.vtt --print
  bash scripts/chapter-generation/cg.sh serve-llm --warmup
EOF
    exit 0
    ;;
  chapters)
    ensure_venv
    exec env PYTHONUNBUFFERED=1 "${PY}" "${ROOT}/make_chapters.py" "$@"
    ;;
  serve-llm)
    ensure_venv
    exec env PYTHONUNBUFFERED=1 "${PY}" "${ROOT}/serve_llm.py" "$@"
    ;;
  pip)
    ensure_venv
    exec "${PY}" -m pip "$@"
    ;;
  *)
    echo "Unknown command: ${cmd}" >&2
    exit 2
    ;;
esac
