[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$scriptRoot = [IO.Path]::GetFullPath($PSScriptRoot)
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

$expectedPath = [IO.Path]::GetFullPath([string]$state.executable)
$actualPath = if ($process.Path) { [IO.Path]::GetFullPath($process.Path) } else { "" }
if (-not $actualPath.Equals($expectedPath, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to stop PID $($state.pid): executable path does not match CjRepo ($actualPath)."
}

Stop-Process -Id $process.Id -Force
$process.WaitForExit(5000) | Out-Null
Remove-Item -LiteralPath $statePath -Force
Write-Host "CjRepo stopped (PID $($state.pid)). Data remains at $($state.storage)."
