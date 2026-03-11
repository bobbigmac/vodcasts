# Shorts Experiment - PowerShell entrypoint
Param(
  [Parameter(Position = 0)][string]$Cmd = "help",
  [Parameter(ValueFromRemainingArguments = $true)][string[]]$Args
)

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Parent = Split-Path -Parent $Root
$AeRoot = Join-Path (Split-Path -Parent $Parent) "answer-engine"
$AePy = Join-Path (Join-Path (Join-Path $AeRoot ".venv") "Scripts") "python.exe"
$ClipperReq = Join-Path $Parent "requirements.txt"
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
  "search" { Run-Python -ScriptName "search_shorts.py" -Rest $Args }
  "write"  { Run-Python -ScriptName "write_short_script.py" -Rest $Args }
  "render" { Run-Python -ScriptName "render_short.py" -Rest $Args }
  "clean"  { Run-Python -ScriptName "..\\cleanup_outputs.py" -Rest $Args -UseAeVenv $false }
  "help" {
    Write-Output @"
Shorts Experiment - vertical shorts from church feed clips.

Usage:
  short.ps1 search --theme forgiveness --output out/short-clips.json
  short.ps1 write --theme forgiveness --clips out/short-clips.json --output out/short.md
  short.ps1 render --script out/short.md --output out/short.mp4
  short.ps1 clean --path out/shorts

Commands: search, write, render, clean
"@
    exit 0
  }
  default {
    Write-Error "Unknown command: $Cmd"
    exit 2
  }
}
