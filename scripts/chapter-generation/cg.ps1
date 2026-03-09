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
    Write-Host "[chapter-generation] installing CUDA torch (cu128) ... (large download)"
    & $Py -m pip install --index-url $TorchIndex $TorchSpec
  }
}

switch ($Cmd) {
  "help" {
    Write-Output @"
Chapter-generation helper.

Usage:
  powershell -ExecutionPolicy Bypass -File scripts/chapter-generation/cg.ps1 chapters [make_chapters.py args...]
  powershell -ExecutionPolicy Bypass -File scripts/chapter-generation/cg.ps1 serve-llm [serve_llm.py args...]
  powershell -ExecutionPolicy Bypass -File scripts/chapter-generation/cg.ps1 pip [pip args...]

Examples:
  powershell -ExecutionPolicy Bypass -File scripts/chapter-generation/cg.ps1 chapters
  powershell -ExecutionPolicy Bypass -File scripts/chapter-generation/cg.ps1 chapters --transcript feed/episode.vtt --print
  powershell -ExecutionPolicy Bypass -File scripts/chapter-generation/cg.ps1 serve-llm --warmup
"@
    exit 0
  }
  "chapters" {
    Ensure-Venv
    & $Py (Join-Path $Root "make_chapters.py") @Args
    exit $LASTEXITCODE
  }
  "serve-llm" {
    Ensure-Venv
    & $Py (Join-Path $Root "serve_llm.py") @Args
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
