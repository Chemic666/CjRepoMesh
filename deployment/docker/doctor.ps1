# Copyright (c) 2026 CjRepoMesh contributors.
# Licensed under the Apache License, Version 2.0.

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$scriptRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$envPath = Join-Path $scriptRoot ".env"
if (-not (Test-Path -LiteralPath $envPath)) {
    throw "Docker environment file not found. Run up.ps1 first."
}

$portLine = Get-Content -LiteralPath $envPath |
    Where-Object { $_.StartsWith("CJREPO_HOST_PORT=") } |
    Select-Object -First 1
if (-not $portLine) {
    throw "CJREPO_HOST_PORT is missing from $envPath"
}
$port = [int]$portLine.Substring($portLine.IndexOf("=") + 1)

$containerId = ((& docker compose --project-directory $scriptRoot --env-file $envPath ps -q cjrepo) -join "").Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($containerId)) {
    throw "CjRepo container is not running."
}
$inspect = $null
foreach ($attempt in 1..30) {
    $inspect = (& docker inspect $containerId | ConvertFrom-Json)[0]
    if ($inspect.State.Health.Status -eq "healthy") {
        break
    }
    Start-Sleep -Milliseconds 500
}

$checks = [ordered]@{
    "Container running" = [bool]$inspect.State.Running
    "Docker healthy" = $inspect.State.Health.Status -eq "healthy"
    "Non-root user" = $inspect.Config.User -eq "10001:10001"
    "Read-only root" = [bool]$inspect.HostConfig.ReadonlyRootfs
    "Capabilities dropped" = $inspect.HostConfig.CapDrop -contains "ALL"
    "No new privileges" = $inspect.HostConfig.SecurityOpt -contains "no-new-privileges:true"
    "Localhost binding" = $inspect.HostConfig.PortBindings.'8080/tcp'[0].HostIp -eq "127.0.0.1"
    "Persistent volume" = @($inspect.Mounts | Where-Object {
        $_.Type -eq "volume" -and $_.Destination -eq "/var/lib/cjrepo"
    }).Count -eq 1
}

try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -TimeoutSec 2
    $checks["Registry API"] = $health.status -eq "ok" -and $health.service -eq "cjrepo"
} catch {
    $checks["Registry API"] = $false
}

$failed = 0
foreach ($entry in $checks.GetEnumerator()) {
    $result = if ($entry.Value) { "PASS" } else { "FAIL" }
    if (-not $entry.Value) { $failed++ }
    Write-Host ("{0,-24} {1}" -f $entry.Key, $result)
}
if ($failed -gt 0) {
    throw "Docker diagnostics failed: $failed check(s)."
}
Write-Host "Overall                  PASS"
