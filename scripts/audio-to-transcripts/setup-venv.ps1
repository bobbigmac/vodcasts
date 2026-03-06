Param(
  [switch]$Force
)

$ErrorActionPreference = "Stop"

# Run from repo root (this script lives in scripts/audio-to-transcripts/).
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root

$venvDir = Join-Path $PSScriptRoot ".venv"
$py = Join-Path $venvDir "Scripts\\python.exe"

if ($Force -and (Test-Path $venvDir)) {
  Remove-Item -Recurse -Force $venvDir
}

if (!(Test-Path $py)) {
  python -m venv $venvDir
}

& $py -m pip install --upgrade pip
& $py -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")

# Ensure CUDA-enabled torch/torchaudio (required for GPU-only WhisperX runs).
$needsCudaTorch = $true
try {
  & $py -c "import torch; import sys; sys.exit(0 if (torch.version.cuda and torch.cuda.is_available()) else 1)"
  if ($LASTEXITCODE -eq 0) { $needsCudaTorch = $false }
} catch {
  $needsCudaTorch = $true
}

if ($needsCudaTorch) {
  Write-Host "Installing CUDA torch/torchaudio (cu128) ... (large download)"
  & $py -m pip install --index-url "https://download.pytorch.org/whl/cu128" "torch==2.8.0+cu128" "torchaudio==2.8.0+cu128"
}

Write-Host "OK: venv ready at $venvDir"
