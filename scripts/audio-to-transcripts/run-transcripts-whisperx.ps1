Param(
  [string]$Feeds = "",
  [string]$Cache = "",
  [string]$Out = "",
  [string]$Tag = "church,sermons",
  [switch]$AllSources,
  [string]$SourceId = "",
  [string]$EpisodeSlug = "",
  [int]$MaxEpisodesPerFeed = 10,
  [switch]$NoDownloadProvided,
  [switch]$GenerateMissing,
  [switch]$AllowCpu,
  [int]$SpotCheckEvery = 0,
  [int]$SpotCheckSeconds = 600,
  [string]$SpotCheckBitrate = "96k",
  [switch]$Execute,
  [switch]$Refresh,
  [string]$Ffmpeg = "ffmpeg",
  [string]$Whisperx = "whisperx",
  [string]$WhisperxModel = "large-v3",
  [string]$Language = "en",
  [string]$WhisperxDevice = "cuda",
  [string]$WhisperxComputeType = "float16",
  [string]$WhisperxExtraArgs = ""
)

$ErrorActionPreference = "Stop"

# Run from repo root (this script lives in scripts/audio-to-transcripts/).
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root

# Prefer the local venv if present.
$venvPy = Join-Path $PSScriptRoot ".venv\\Scripts\\python.exe"
$python = if (Test-Path $venvPy) { $venvPy } else { "python" }

$venvWhisperx = Join-Path $PSScriptRoot ".venv\\Scripts\\whisperx.exe"
if ($Whisperx -eq "whisperx" -and (Test-Path $venvWhisperx)) {
  $Whisperx = $venvWhisperx
}

# Optional: force offline model usage (only works if models are already cached).
# $env:HF_HUB_OFFLINE = "1"
# $env:TRANSFORMERS_OFFLINE = "1"

$argsList = @(
  (Join-Path $PSScriptRoot "transcripts_whisperx.py"),
  "--tag", $Tag,
  "--max-episodes-per-feed", "$MaxEpisodesPerFeed",
  "--ffmpeg", $Ffmpeg,
  "--whisperx", $Whisperx,
  "--whisperx-model", $WhisperxModel,
  "--language", $Language
)

if ($Feeds -ne "") { $argsList += @("--feeds", $Feeds) }
if ($Cache -ne "") { $argsList += @("--cache", $Cache) }
if ($Out -ne "") { $argsList += @("--out", $Out) }
if ($AllSources) { $argsList += @("--all-sources") }
if ($SourceId -ne "") { $argsList += @("--source-id", $SourceId) }
if ($EpisodeSlug -ne "") { $argsList += @("--episode-slug", $EpisodeSlug) }
if ($NoDownloadProvided) { $argsList += @("--no-download-provided") }
if ($GenerateMissing) { $argsList += @("--generate-missing") }
if ($AllowCpu) { $argsList += @("--allow-cpu") }
if ($SpotCheckEvery -ge 0) { $argsList += @("--spot-check-every", "$SpotCheckEvery") }
if ($SpotCheckSeconds -gt 0) { $argsList += @("--spot-check-seconds", "$SpotCheckSeconds") }
if ($SpotCheckBitrate -ne "") { $argsList += @("--spot-check-bitrate", $SpotCheckBitrate) }
if ($Execute) { $argsList += @("--execute") }
if ($Refresh) { $argsList += @("--refresh") }
if ($WhisperxExtraArgs -ne "") { $argsList += @("--whisperx-extra-args", $WhisperxExtraArgs) }
if ($WhisperxDevice -ne "") { $argsList += @("--whisperx-device", $WhisperxDevice) }
if ($WhisperxComputeType -ne "") { $argsList += @("--whisperx-compute-type", $WhisperxComputeType) }

& $python @argsList

