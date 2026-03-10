Param(
  [string]$Feeds = "",
  [string]$Cache = "",
  [string]$Out = "",
  [string]$Tag = "church,sermons",
  [switch]$AllSources,
  [string]$SourceId = "",
  [string]$EpisodeSlug = "",
  [int]$MaxEpisodesPerFeed = 10,
  [int]$Concurrency = 0,
  [switch]$PreferShorter,
  [switch]$NoDownloadProvided,
  [switch]$GenerateMissing,
  [int]$SpotCheckEvery = 0,
  [int]$SpotCheckSeconds = 600,
  [string]$SpotCheckBitrate = "96k",
  [switch]$Execute,
  [switch]$Refresh,
  [string]$Ffmpeg = "ffmpeg",
  [string]$Whisperx = "whisperx",
  [string]$WhisperxModel = "medium",
  [string]$Language = "en",
  [string]$WhisperxDevice = "cuda",
  [string]$WhisperxComputeType = "float16",
  [string]$WhisperxExtraArgs = "",
  [string]$WhisperxWorkerUrl = "",
  [string]$Backend = "whisperx",
  [switch]$NoWorker,
  [switch]$ServeWorker,
  [string]$WorkerHost = "127.0.0.1",
  [int]$WorkerPort = 0,
  [switch]$WorkerWarmup
)

$ErrorActionPreference = "Stop"

function Get-FreeTcpPort {
  $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
  $listener.Start()
  try {
    return ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
  }
  finally {
    $listener.Stop()
  }
}

function Get-WorkerHealth([string]$BaseUrl, [int]$TimeoutSec = 3) {
  $healthUrl = ($BaseUrl.TrimEnd("/")) + "/health"
  try {
    return Invoke-RestMethod -Uri $healthUrl -TimeoutSec $TimeoutSec -Method Get
  }
  catch {
    return $null
  }
}

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

$serveScript = Join-Path $PSScriptRoot "serve_transcripts_whisperx.py"

if ($ServeWorker) {
  $servePort = if ($WorkerPort -gt 0) { $WorkerPort } else { 8776 }
  $serveArgs = @(
    $serveScript,
    "--host", $WorkerHost,
    "--port", "$servePort",
    "--model", $WhisperxModel,
    "--language", $Language,
    "--device", $WhisperxDevice,
    "--compute-type", $WhisperxComputeType
  )
  if ($WhisperxExtraArgs -ne "") { $serveArgs += @("--extra-args", $WhisperxExtraArgs) }
  if ($WorkerWarmup) { $serveArgs += @("--warmup") }
  & $python @serveArgs
  exit $LASTEXITCODE
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
if ($Concurrency -gt 0) { $argsList += @("--concurrency", "$Concurrency") }
if ($PreferShorter) { $argsList += @("--prefer-shorter") }
if ($NoDownloadProvided) { $argsList += @("--no-download-provided") }
if ($GenerateMissing) { $argsList += @("--generate-missing") }
if ($SpotCheckEvery -gt 0) {
  $argsList += @("--spot-check-every", "$SpotCheckEvery")
  if ($SpotCheckSeconds -gt 0) { $argsList += @("--spot-check-seconds", "$SpotCheckSeconds") }
  if ($SpotCheckBitrate -ne "") { $argsList += @("--spot-check-bitrate", $SpotCheckBitrate) }
}
if ($Execute) { $argsList += @("--execute") }
if ($Refresh) { $argsList += @("--refresh") }
if ($WhisperxExtraArgs -ne "") { $argsList += @("--whisperx-extra-args", $WhisperxExtraArgs) }
if ($WhisperxDevice -ne "") { $argsList += @("--whisperx-device", $WhisperxDevice) }
if ($WhisperxComputeType -ne "") { $argsList += @("--whisperx-compute-type", $WhisperxComputeType) }
$workerProc = $null

# Parakeet and Moonshine run in-process; no worker needed.
$useWorker = -not $NoWorker -and ($Backend -eq "whisperx")

try {
  if ($GenerateMissing -and $Execute -and $useWorker -and $WhisperxWorkerUrl -eq "") {
    $autoPort = if ($WorkerPort -gt 0) { $WorkerPort } else { Get-FreeTcpPort }
    $WhisperxWorkerUrl = "http://$WorkerHost`:$autoPort"
    $existing = Get-WorkerHealth -BaseUrl $WhisperxWorkerUrl
    if ($null -eq $existing) {
      $serveArgs = @(
        $serveScript,
        "--host", $WorkerHost,
        "--port", "$autoPort",
        "--model", $WhisperxModel,
        "--language", $Language,
        "--device", $WhisperxDevice,
        "--compute-type", $WhisperxComputeType
      )
      if ($WhisperxExtraArgs -ne "") { $serveArgs += @("--extra-args", $WhisperxExtraArgs) }
      $serveArgs += @("--warmup")
      $workerProc = Start-Process -FilePath $python -ArgumentList $serveArgs -PassThru -WindowStyle Hidden
      $ready = $false
      for ($i = 0; $i -lt 240; $i++) {
        Start-Sleep -Milliseconds 1000
        if ($workerProc.HasExited) {
          throw "WhisperX worker exited before becoming ready."
        }
        $health = Get-WorkerHealth -BaseUrl $WhisperxWorkerUrl
        if ($null -ne $health) {
          $ready = $true
          break
        }
      }
      if (-not $ready) {
        throw "WhisperX worker did not become ready at $WhisperxWorkerUrl"
      }
      Write-Host "[worker] started $WhisperxWorkerUrl model=$WhisperxModel device=$WhisperxDevice"
    }
    else {
      Write-Host "[worker] reusing $WhisperxWorkerUrl"
    }
  }

  if ($WhisperxWorkerUrl -ne "") { $argsList += @("--whisperx-worker-url", $WhisperxWorkerUrl) }
if ($Backend -ne "") { $argsList += @("--backend", $Backend) }

  & $python @argsList
  exit $LASTEXITCODE
}
finally {
  if ($null -ne $workerProc) {
    try {
      if (-not $workerProc.HasExited) {
        Stop-Process -Id $workerProc.Id -Force
        Write-Host "[worker] stopped pid=$($workerProc.Id)"
      }
    }
    catch {
    }
  }
}
