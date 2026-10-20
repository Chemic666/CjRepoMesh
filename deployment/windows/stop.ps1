[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$scriptRoot = [IO.Path]::GetFullPath($PSScriptRoot)
. (Join-Path $scriptRoot "common.ps1")
$serverExe = [IO.Path]::GetFullPath((Join-Path $scriptRoot "..\..\server\target\release\bin\main.exe"))
$statePath = Join-Path $scriptRoot "run\cjrepo.json"

if (-not (Test-Path -LiteralPath $statePath)) {
    Write-Host "CjRepo is not running (no deployment state found)."
    exit 0
}

$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
$process = Get-Process -Id ([int]$state.pid) -ErrorAction SilentlyContinue
if ($null -eq $process) {
    Remove-Item -LiteralPath $statePath -Force
    Write-Host "Removed stale CjRepo deployment state."
    exit 0
}

if (-not (Test-CjRepoProcessIdentity $process $state $serverExe)) {
    throw "Refusing to stop PID $($state.pid): process identity does not match CjRepo. Inspect legacy or stale state manually."
}

Stop-Process -InputObject $process -Force
if (-not $process.WaitForExit(5000)) {
    throw "CjRepo did not exit within 5 seconds. Deployment state has been preserved."
}
Remove-Item -LiteralPath $statePath -Force
Write-Host "CjRepo stopped (PID $($state.pid)). Data remains at $($state.storage)."
