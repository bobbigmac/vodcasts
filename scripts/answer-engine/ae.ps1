Param(
  [Parameter(Position = 0)][string]$Cmd = "help",
  [Parameter(ValueFromRemainingArguments = $true)][string[]]$Args
)

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Root ".venv"
$Py = Join-Path $Venv "Scripts/python.exe"
$TorchSpec = "torch==2.10.0+cu128"
$TorchIndex = "https://download.pytorch.org/whl/cu128"

function Ensure-Venv {
  if (!(Test-Path $Py)) {
    python -m venv $Venv
    & $Py -m pip install --upgrade pip
  }

  $req = Join-Path $Root "requirements.txt"
  $stamp = Join-Path $Venv ".deps.sha256"
  $hashSource = (Get-FileHash $req -Algorithm SHA256).Hash + "|" + $TorchSpec
  $hash = [System.BitConverter]::ToString(
    [System.Security.Cryptography.SHA256]::Create().ComputeHash(
      [System.Text.Encoding]::UTF8.GetBytes($hashSource)
    )
  ).Replace("-", "").ToLowerInvariant()

  $current = ""
  if (Test-Path $stamp) {
    $current = (Get-Content $stamp -Raw).Trim()
  }
  if ($current -ne $hash) {
    & $Py -m pip install -r $req
    Set-Content -Path $stamp -Value $hash -NoNewline
  }

  $needsCudaTorch = $true
  try {
    & $Py -c "import torch; import sys; sys.exit(0 if (torch.version.cuda and torch.cuda.is_available()) else 1)"
    if ($LASTEXITCODE -eq 0) { $needsCudaTorch = $false }
  } catch {
    $needsCudaTorch = $true
  }

  if ($needsCudaTorch) {
    Write-Host "[answer-engine] installing CUDA torch (cu128) ... (large download)"
    & $Py -m pip install --index-url $TorchIndex $TorchSpec
  }
}

switch ($Cmd) {
  "help" {
    Write-Output @"
Answer-engine helper.

Usage:
  powershell -ExecutionPolicy Bypass -File scripts/answer-engine/ae.ps1 analyze [analyze.py args...]
  powershell -ExecutionPolicy Bypass -File scripts/answer-engine/ae.ps1 index [build_index.py args...]
  powershell -ExecutionPolicy Bypass -File scripts/answer-engine/ae.ps1 chapters [make_chapters.py args...]
  powershell -ExecutionPolicy Bypass -File scripts/answer-engine/ae.ps1 query [query.py args...]
  powershell -ExecutionPolicy Bypass -File scripts/answer-engine/ae.ps1 pip [pip args...]

Examples:
  powershell -ExecutionPolicy Bypass -File scripts/answer-engine/ae.ps1 analyze
  powershell -ExecutionPolicy Bypass -File scripts/answer-engine/ae.ps1 analyze --transcript bridgetown/2026-03-02-the-good-news-about-our-bodies-chronic-illness-disability-10g2du.vtt
  powershell -ExecutionPolicy Bypass -File scripts/answer-engine/ae.ps1 index
  powershell -ExecutionPolicy Bypass -File scripts/answer-engine/ae.ps1 chapters --transcript feed/episode.vtt --print
  powershell -ExecutionPolicy Bypass -File scripts/answer-engine/ae.ps1 query search --q "forgiveness" --limit 10
"@
    exit 0
  }
  "analyze" {
    Ensure-Venv
    & $Py (Join-Path $Root "analyze.py") @Args
    exit $LASTEXITCODE
  }
  "index" {
    Ensure-Venv
    & $Py (Join-Path $Root "build_index.py") @Args
    exit $LASTEXITCODE
  }
  "chapters" {
    Ensure-Venv
    & $Py (Join-Path $Root "make_chapters.py") @Args
    exit $LASTEXITCODE
  }
  "query" {
    Ensure-Venv
    & $Py (Join-Path $Root "query.py") @Args
    exit $LASTEXITCODE
  }
  "pip" {
    Ensure-Venv
    & $Py -m pip @Args
    exit $LASTEXITCODE
  }
  default {
    Write-Error "Unknown command: $Cmd"
    exit 2
  }
}
