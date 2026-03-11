Param(
  [Parameter(Position = 0)][string]$Cmd = "help",
  [Parameter(ValueFromRemainingArguments = $true)][string[]]$Args
)

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Run-Python {
  param([string]$ScriptName, [string[]]$Rest = @())
  $script = Join-Path $Root $ScriptName
  & python $script @Rest
  exit $LASTEXITCODE
}

switch ($Cmd) {
  "analyze-spacetime" { Run-Python -ScriptName "analyze_spacetime_plan.py" -Rest $Args }
  "apply" { Run-Python -ScriptName "apply_edit_plan.py" -Rest $Args }
  "help" {
    Write-Output @"
Markdown Video Editor

Usage:
  mve.ps1 analyze-spacetime --input in/source.mp4 --output out/source.edit.md
  mve.ps1 apply --plan out/source.edit.md --output out/source.out.mp4

Commands: analyze-spacetime, apply
"@
    exit 0
  }
  default {
    Write-Error "Unknown command: $Cmd"
    exit 2
  }
}
