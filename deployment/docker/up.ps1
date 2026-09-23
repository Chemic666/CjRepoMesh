# Copyright (c) 2026 CjRepoMesh contributors.
# Licensed under the Apache License, Version 2.0.

[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8080,
    [Security.SecureString]$PublishToken,
    [string]$Upstream = "",
    [Security.SecureString]$UpstreamToken,
    [ValidateRange(0, 31536000)]
    [long]$ProxyTtlSeconds = 86400,
    [string]$WslDistribution = "CjRepoMesh",
    [string]$WslProjectRoot = "/home/chemic/work/CjRepoMesh-src",
    [string]$WslSdkRoot = "/home/chemic/apps/cangjie-1.1.3"
)

$ErrorActionPreference = "Stop"
$scriptRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$envPath = Join-Path $scriptRoot ".env"
$publishTokenValue = if ($null -ne $PublishToken) {
    [Net.NetworkCredential]::new("", $PublishToken).Password
} else {
    ""
}
$upstreamTokenValue = if ($null -ne $UpstreamToken) {
    [Net.NetworkCredential]::new("", $UpstreamToken).Password
} else {
    ""
}

function Protect-CredentialFile([string]$Path) {
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
        return
    }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $acl = [Security.AccessControl.FileSecurity]::new()
    $acl.SetOwner($identity.User)
    $acl.SetAccessRuleProtection($true, $false)
    $rule = [Security.AccessControl.FileSystemAccessRule]::new(
        $identity.User,
        [Security.AccessControl.FileSystemRights]::FullControl,
        [Security.AccessControl.AccessControlType]::Allow
    )
    $acl.AddAccessRule($rule)
    Set-Acl -LiteralPath $Path -AclObject $acl
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI is not available. Install or enable Docker Desktop first."
}
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker engine is not running. Start Docker Desktop and retry."
}

if ([string]::IsNullOrWhiteSpace($publishTokenValue) -and (Test-Path -LiteralPath $envPath)) {
    $existingToken = Get-Content -LiteralPath $envPath |
        Where-Object { $_.StartsWith("CJREPO_PUBLISH_TOKEN=") } |
        Select-Object -First 1
    if ($existingToken) {
        $publishTokenValue = $existingToken.Substring($existingToken.IndexOf("=") + 1)
    }
}
if ([string]::IsNullOrWhiteSpace($publishTokenValue)) {
    $randomBytes = New-Object byte[] 32
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($randomBytes)
    } finally {
        $generator.Dispose()
    }
    $publishTokenValue = ([BitConverter]::ToString($randomBytes)).Replace("-", "").ToLowerInvariant()
}
if ($publishTokenValue -notmatch '^[A-Za-z0-9._~-]{16,256}$') {
    throw "PublishToken must contain 16-256 URL-safe characters."
}
foreach ($value in @($Upstream, $upstreamTokenValue)) {
    if ($value.Contains("`r") -or $value.Contains("`n")) {
        throw "Environment values must not contain newlines."
    }
}

& (Join-Path $scriptRoot "prepare.ps1") `
    -WslDistribution $WslDistribution -WslProjectRoot $WslProjectRoot -WslSdkRoot $WslSdkRoot

$lines = @(
    "CJREPO_HOST_PORT=$Port",
    "CJREPO_PUBLISH_TOKEN=$publishTokenValue",
    "CJREPO_UPSTREAM=$Upstream",
    "CJREPO_UPSTREAM_TOKEN=$upstreamTokenValue",
    "CJREPO_PROXY_TTL_SECONDS=$ProxyTtlSeconds"
)
[IO.File]::WriteAllLines($envPath, $lines, [Text.UTF8Encoding]::new($false))
Protect-CredentialFile $envPath

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
Write-Host "Publish token value is hidden. Credentials are stored in the ignored file: $envPath"
