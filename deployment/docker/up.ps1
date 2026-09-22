# Copyright (c) 2026 CjRepoMesh contributors.
# Licensed under the Apache License, Version 2.0.

[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8080,
    [string]$PublishToken = "",
    [string]$Upstream = "",
    [string]$UpstreamToken = "",
    [ValidateRange(0, 31536000)]
    [long]$ProxyTtlSeconds = 86400,
    [string]$WslDistribution = "CjRepoMesh",
    [string]$WslProjectRoot = "/home/chemic/work/CjRepoMesh-src",
    [string]$WslSdkRoot = "/home/chemic/apps/cangjie-1.1.3"
)

$ErrorActionPreference = "Stop"
$scriptRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$envPath = Join-Path $scriptRoot ".env"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI is not available. Install or enable Docker Desktop first."
}
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker engine is not running. Start Docker Desktop and retry."
}

if ([string]::IsNullOrWhiteSpace($PublishToken)) {
    $randomBytes = New-Object byte[] 32
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($randomBytes)
    } finally {
        $generator.Dispose()
    }
    $PublishToken = ([BitConverter]::ToString($randomBytes)).Replace("-", "").ToLowerInvariant()
}
if ($PublishToken -notmatch '^[A-Za-z0-9._~-]{16,256}$') {
    throw "PublishToken must contain 16-256 URL-safe characters."
}
foreach ($value in @($Upstream, $UpstreamToken)) {
    if ($value.Contains("`r") -or $value.Contains("`n")) {
        throw "Environment values must not contain newlines."
    }
}

& (Join-Path $scriptRoot "prepare.ps1") `
    -WslDistribution $WslDistribution -WslProjectRoot $WslProjectRoot -WslSdkRoot $WslSdkRoot

$lines = @(
    "CJREPO_HOST_PORT=$Port",
    "CJREPO_PUBLISH_TOKEN=$PublishToken",
    "CJREPO_UPSTREAM=$Upstream",
    "CJREPO_UPSTREAM_TOKEN=$UpstreamToken",
    "CJREPO_PROXY_TTL_SECONDS=$ProxyTtlSeconds"
)
[IO.File]::WriteAllLines($envPath, $lines, [Text.UTF8Encoding]::new($false))

docker compose --project-directory $scriptRoot --env-file $envPath up -d --build
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose deployment failed."
}

$healthy = $false
foreach ($attempt in 1..60) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 1
        if ($health.status -eq "ok" -and $health.service -eq "cjrepo") {
            $healthy = $true
            break
        }
    } catch {
        Start-Sleep -Milliseconds 500
    }
}
if (-not $healthy) {
    docker compose --project-directory $scriptRoot --env-file $envPath logs --tail 100
    throw "CjRepo container did not become healthy."
}

Write-Host "CjRepo container is ready: http://127.0.0.1:$Port"
Write-Host "Publish token: $PublishToken"
Write-Host "Credentials are stored only in the ignored file: $envPath"
