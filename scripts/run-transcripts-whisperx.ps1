Param(
  [string]$Feeds = "feeds\\dev.md",
  [string]$Cache = "cache\\dev",
  [string]$Out = "",
  [string]$Tag = "sermons",
  [switch]$AllSources,
  [int]$MaxEpisodesPerFeed = 0,
  [switch]$GenerateMissing,
  [switch]$Execute,
  [switch]$Refresh,
  [string]$Ffmpeg = "ffmpeg",
  [string]$Whisperx = "whisperx",
  [string]$WhisperxModel = "large-v3",
  [string]$Language = "en",
  [string]$WhisperxExtraArgs = ""
)

$ErrorActionPreference = "Stop"

# Run from repo root (this script lives in scripts/).
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# Optional: force offline model usage (only works if models are already cached).
# $env:HF_HUB_OFFLINE = "1"
# $env:TRANSFORMERS_OFFLINE = "1"

$argsList = @(
  "-m", "scripts.transcripts_whisperx",
  "--feeds", $Feeds,
  "--cache", $Cache,
  "--tag", $Tag,
  "--max-episodes-per-feed", "$MaxEpisodesPerFeed",
  "--ffmpeg", $Ffmpeg,
  "--whisperx", $Whisperx,
  "--whisperx-model", $WhisperxModel,
  "--language", $Language
)

if ($Out -ne "") { $argsList += @("--out", $Out) }
if ($AllSources) { $argsList += @("--all-sources") }
if ($GenerateMissing) { $argsList += @("--generate-missing") }
if ($Execute) { $argsList += @("--execute") }
if ($Refresh) { $argsList += @("--refresh") }
if ($WhisperxExtraArgs -ne "") { $argsList += @("--whisperx-extra-args", $WhisperxExtraArgs) }

python @argsList

