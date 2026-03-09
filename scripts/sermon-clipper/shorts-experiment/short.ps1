# Shorts Experiment - PowerShell entrypoint
Param(
  [Parameter(Position = 0)][string]$Cmd = "help",
  [Parameter(ValueFromRemainingArguments = $true)][string[]]$Args
)

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Parent = Split-Path -Parent $Root
$AeRoot = Join-Path (Split-Path -Parent $Parent) "answer-engine"
$AePy = Join-Path $AeRoot ".venv" "Scripts" "python.exe"
if (!(Test-Path $AePy)) { $AePy = "python" }

function Run-Python {
  param([string]$ScriptName, [string[]]$Rest = @(), [switch]$UseAeVenv = $true)
  $script = Join-Path $Root $ScriptName
  $py = if ($UseAeVenv -and (Test-Path $AePy)) { $AePy } else { "python" }
  & $py $script @Rest
  exit $LASTEXITCODE
}

switch ($Cmd) {
  "search" { Run-Python -ScriptName "search_shorts.py" -Rest $Args }
  "write"  { Run-Python -ScriptName "write_short_script.py" -Rest $Args }
  "render" { Run-Python -ScriptName "render_short.py" -Rest $Args -UseAeVenv $false }
  "help" {
    Write-Output @"
Shorts Experiment - vertical shorts from church feed clips.

Usage:
  short.ps1 search --theme forgiveness --output out/short-clips.json
  short.ps1 write --theme forgiveness --clips out/short-clips.json --output out/short.md
  short.ps1 render --script out/short.md --output out/short.mp4

Commands: search, write, render
"@
    exit 0
  }
  default {
    Write-Error "Unknown command: $Cmd"
    exit 2
  }
}
