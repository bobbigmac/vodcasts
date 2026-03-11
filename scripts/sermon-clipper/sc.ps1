# Sermon Clipper - PowerShell entrypoint
Param(
  [Parameter(Position = 0)][string]$Cmd = "help",
  [Parameter(ValueFromRemainingArguments = $true)][string[]]$Args
)

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$AeRoot = Join-Path (Split-Path -Parent $Root) "answer-engine"
$AePy = Join-Path (Join-Path (Join-Path $AeRoot ".venv") "Scripts") "python.exe"
$ClipperReq = Join-Path $Root "requirements.txt"
$ClipperStamp = Join-Path (Join-Path $AeRoot ".venv") ".sermon-clipper.deps.sha256"
if (!(Test-Path $AePy)) { $AePy = "python" }

function Ensure-ClipperDeps {
  if (!(Test-Path $AePy)) { return }
  if (!(Test-Path $ClipperReq)) { return }

  $hash = (Get-FileHash $ClipperReq -Algorithm SHA256).Hash.ToLowerInvariant()
  $current = ""
  if (Test-Path $ClipperStamp) {
    $current = (Get-Content $ClipperStamp -Raw).Trim().ToLowerInvariant()
  }
  if ($current -ne $hash) {
    & $AePy -m pip install -r $ClipperReq
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Set-Content -Path $ClipperStamp -Value $hash -NoNewline
  }
}

function Run-Python {
  param([string]$ScriptName, [string[]]$Rest = @(), [switch]$UseAeVenv = $true)
  $script = Join-Path $Root $ScriptName
  $py = if ($UseAeVenv -and (Test-Path $AePy)) { $AePy } else { "python" }
  if ($UseAeVenv) {
    Ensure-ClipperDeps
  }
  & $py $script @Rest
  exit $LASTEXITCODE
}

switch ($Cmd) {
  "search" { Run-Python -ScriptName "search_clips.py" -Rest $Args }
  "write"  { Run-Python -ScriptName "write_script.py" -Rest $Args }
  "cards"  { Run-Python -ScriptName "make_title_cards.py" -Rest $Args }
  "render" { Run-Python -ScriptName "render_video.py" -Rest $Args }
  "clean"  { Run-Python -ScriptName "cleanup_outputs.py" -Rest $Args -UseAeVenv $false }
  "help" {
    Write-Output @"
Sermon Clipper - generate video essays from church feed clips.

Usage:
  powershell -ExecutionPolicy Bypass -File scripts/sermon-clipper/sc.ps1 search --theme forgiveness --output out/clips.json
  powershell -ExecutionPolicy Bypass -File scripts/sermon-clipper/sc.ps1 write --theme forgiveness --output out/video.md
  powershell -ExecutionPolicy Bypass -File scripts/sermon-clipper/sc.ps1 cards --script out/video.md --output out/title-cards
  powershell -ExecutionPolicy Bypass -File scripts/sermon-clipper/sc.ps1 render --script out/video.md --output out/video.mp4 --title-cards out/title-cards
  powershell -ExecutionPolicy Bypass -File scripts/sermon-clipper/sc.ps1 clean --path out/sermon-clips-examples

Commands: search, write, cards, render, clean
"@
    exit 0
  }
  default {
    Write-Error "Unknown command: $Cmd"
    exit 2
  }
}
