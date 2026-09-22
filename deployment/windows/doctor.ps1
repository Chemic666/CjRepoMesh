[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$scriptRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$statePath = Join-Path $scriptRoot "run\cjrepo.json"

if (-not (Test-Path -LiteralPath $statePath)) {
    Write-Host "STATE   FAIL  CjRepo has not been started by this deployment."
    exit 1
}

$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
$process = Get-Process -Id ([int]$state.pid) -ErrorAction SilentlyContinue
if ($null -eq $process) {
    Write-Host "PROCESS FAIL  PID $($state.pid) is not running."
    exit 1
}

$expectedPath = [IO.Path]::GetFullPath([string]$state.executable)
$actualPath = if ($process.Path) { [IO.Path]::GetFullPath($process.Path) } else { "" }
if (-not $actualPath.Equals($expectedPath, [StringComparison]::OrdinalIgnoreCase)) {
    Write-Host "PROCESS FAIL  PID $($state.pid) belongs to another executable."
    exit 1
}
Write-Host "PROCESS PASS  PID $($state.pid)"

if (-not (Test-Path -LiteralPath ([string]$state.storage) -PathType Container)) {
    Write-Host "STORAGE FAIL  $($state.storage)"
    exit 1
}
Write-Host "STORAGE PASS  $($state.storage)"

try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$($state.port)/health" -TimeoutSec 2
    if ($health.status -ne "ok" -or $health.service -ne "cjrepo") {
        throw "Unexpected health response"
    }
} catch {
    Write-Host "HEALTH  FAIL  http://127.0.0.1:$($state.port)/health"
    exit 1
}
Write-Host "HEALTH  PASS  http://127.0.0.1:$($state.port)/health"
Write-Host "CjRepo deployment is healthy."
