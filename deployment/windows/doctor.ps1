[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$scriptRoot = [IO.Path]::GetFullPath($PSScriptRoot)
. (Join-Path $scriptRoot "common.ps1")
$serverExe = [IO.Path]::GetFullPath((Join-Path $scriptRoot "..\..\server\target\release\bin\main.exe"))
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

if (-not (Test-CjRepoProcessIdentity $process $state $serverExe)) {
    Write-Host "PROCESS FAIL  PID $($state.pid) identity does not match. Inspect legacy or stale state manually."
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
    $listeners = @(Get-CjRepoPortListener ([int]$state.port))
    $process.Refresh()
    if ($process.HasExited -or
        @($listeners | Where-Object { $_.OwningProcess -ne $process.Id }).Count -ne 0 -or
        @($listeners | Where-Object { $_.LocalAddress -eq "127.0.0.1" -and $_.OwningProcess -eq $process.Id }).Count -eq 0) {
        throw "Listener does not belong to the recorded CjRepo process"
    }
} catch {
    Write-Host "HEALTH  FAIL  http://127.0.0.1:$($state.port)/health"
    exit 1
}
Write-Host "HEALTH  PASS  http://127.0.0.1:$($state.port)/health"
Write-Host "CjRepo deployment is healthy."
exit 0
