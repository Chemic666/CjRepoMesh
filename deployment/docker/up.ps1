# Copyright (c) 2026 CjRepoMesh contributors.
# Licensed under the Apache License, Version 2.0.

[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8080,
    [Security.SecureString]$PublishToken,
    [Security.SecureString]$ReadToken,
    [switch]$DisableReadToken,
    [string]$Upstream = "",
    [Security.SecureString]$UpstreamToken,
    [ValidateRange(0, 31536000)]
    [long]$ProxyTtlSeconds = 86400,
    [string]$WslDistribution = "CjRepoMesh",
    [string]$WslProjectRoot = "/home/chemic/work/CjRepoMesh-src",
    [string]$WslSdkRoot = "/home/chemic/apps/cangjie-1.1.3",
    [string]$ServerBinaryPath = ""
)

$ErrorActionPreference = "Stop"
$scriptRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$envPath = Join-Path $scriptRoot ".env"
if ($DisableReadToken -and $null -ne $ReadToken) {
    throw "ReadToken and DisableReadToken cannot be used together."
}
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
$readTokenValue = if ($null -ne $ReadToken) {
    [Net.NetworkCredential]::new("", $ReadToken).Password
} else {
    ""
}

function Protect-CredentialFile([string]$Path) {
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
        return
    }
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Credential file must not be a symbolic link or reparse point: $Path"
    }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $existingAcl = Get-Acl -LiteralPath $Path
    $owner = $existingAcl.GetOwner([Security.Principal.SecurityIdentifier])
    if ($owner.Value -ne $identity.User.Value) {
        throw "Credential file is not owned by the current Windows user: $Path"
    }
    $acl = [Security.AccessControl.FileSecurity]::new()
    $acl.SetAccessRuleProtection($true, $false)
    $rule = [Security.AccessControl.FileSystemAccessRule]::new(
        $identity.User,
        [Security.AccessControl.FileSystemRights]::FullControl,
        [Security.AccessControl.AccessControlType]::Allow
    )
    $acl.AddAccessRule($rule)
    [IO.FileSystemAclExtensions]::SetAccessControl([IO.FileInfo]::new($Path), $acl)
    $applied = Get-Acl -LiteralPath $Path
    $accessRules = @($applied.GetAccessRules($true, $false, [Security.Principal.SecurityIdentifier]))
    if (-not $applied.AreAccessRulesProtected -or $accessRules.Count -ne 1 -or
        $accessRules[0].IdentityReference.Value -ne $identity.User.Value -or
        $accessRules[0].AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow -or
        $accessRules[0].FileSystemRights -ne [Security.AccessControl.FileSystemRights]::FullControl) {
        throw "Credential file permissions could not be restricted to the current Windows user: $Path"
    }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI is not available. Install or enable Docker Desktop first."
}
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker engine is not running. Start Docker Desktop and retry."
}

$hadEnvFile = Test-Path -LiteralPath $envPath
if (-not $hadEnvFile) {
    [IO.File]::WriteAllText($envPath, "", [Text.UTF8Encoding]::new($false))
}
Protect-CredentialFile $envPath

if ([string]::IsNullOrWhiteSpace($publishTokenValue) -and $hadEnvFile) {
    $existingToken = Get-Content -LiteralPath $envPath |
        Where-Object { $_.StartsWith("CJREPO_PUBLISH_TOKEN=") } |
        Select-Object -First 1
    if ($existingToken) {
        $publishTokenValue = $existingToken.Substring($existingToken.IndexOf("=") + 1)
    }
}
if (-not $DisableReadToken -and [string]::IsNullOrWhiteSpace($readTokenValue) -and $hadEnvFile) {
    $existingReadToken = Get-Content -LiteralPath $envPath |
        Where-Object { $_.StartsWith("CJREPO_READ_TOKEN=") } |
        Select-Object -First 1
    if ($existingReadToken) {
        $readTokenValue = $existingReadToken.Substring($existingReadToken.IndexOf("=") + 1)
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
if ($readTokenValue -and $readTokenValue -notmatch '^[A-Za-z0-9._~-]{16,256}$') {
    throw "ReadToken must contain 16-256 URL-safe characters."
}
foreach ($value in @($Upstream, $upstreamTokenValue)) {
    if ($value.Contains("`r") -or $value.Contains("`n")) {
        throw "Environment values must not contain newlines."
    }
}

& (Join-Path $scriptRoot "prepare.ps1") `
    -WslDistribution $WslDistribution -WslProjectRoot $WslProjectRoot -WslSdkRoot $WslSdkRoot `
    -ServerBinaryPath $ServerBinaryPath

$lines = @(
    "CJREPO_HOST_PORT=$Port",
    "CJREPO_PUBLISH_TOKEN=$publishTokenValue",
    "CJREPO_READ_TOKEN=$readTokenValue",
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
