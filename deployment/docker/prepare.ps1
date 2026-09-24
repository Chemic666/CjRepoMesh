# Copyright (c) 2026 CjRepoMesh contributors.
# Licensed under the Apache License, Version 2.0.

[CmdletBinding()]
param(
    [string]$WslDistribution = "CjRepoMesh",
    [string]$WslProjectRoot = "/home/chemic/work/CjRepoMesh-src",
    [string]$WslSdkRoot = "/home/chemic/apps/cangjie-1.1.3",
    [string]$ServerBinaryPath = ""
)

$ErrorActionPreference = "Stop"
$scriptRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$contextRoot = Join-Path $scriptRoot ".build-context"

function Convert-ToWslUnc([string]$LinuxPath) {
    if (-not $LinuxPath.StartsWith("/")) {
        throw "WSL path must be absolute: $LinuxPath"
    }
    $relative = $LinuxPath.TrimStart("/").Replace("/", "\")
    return "\\wsl.localhost\$WslDistribution\$relative"
}

$architecture = (& wsl.exe --distribution $WslDistribution -- uname -m | Select-Object -Last 1).Trim()
if ($LASTEXITCODE -ne 0 -or $architecture -ne "x86_64") {
    throw "Docker packaging currently requires an x86_64 WSL distribution; detected '$architecture'."
}

$linuxRuntime = "$WslSdkRoot/runtime/lib/linux_x86_64_cjnative"
$sources = [ordered]@{
    "cjrepo" = "$WslProjectRoot/server/target/release/bin/main"
    "libcangjie-runtime.so" = "$linuxRuntime/libcangjie-runtime.so"
    "libboundscheck.so" = "$linuxRuntime/libboundscheck.so"
}

New-Item -ItemType Directory -Force -Path $contextRoot | Out-Null
foreach ($name in $sources.Keys) {
    $source = if ($name -eq "cjrepo" -and -not [string]::IsNullOrWhiteSpace($ServerBinaryPath)) {
        [IO.Path]::GetFullPath($ServerBinaryPath)
    } else {
        Convert-ToWslUnc $sources[$name]
    }
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Required Linux artifact not found: $source"
    }
    Copy-Item -LiteralPath $source -Destination (Join-Path $contextRoot $name) -Force
}

$manifest = foreach ($name in $sources.Keys) {
    $path = Join-Path $contextRoot $name
    $item = Get-Item -LiteralPath $path
    $hash = Get-FileHash -LiteralPath $path -Algorithm SHA256
    [ordered]@{ file = $name; bytes = $item.Length; sha256 = $hash.Hash.ToLowerInvariant() }
}
[IO.File]::WriteAllText(
    (Join-Path $contextRoot "manifest.json"),
    ($manifest | ConvertTo-Json),
    [Text.UTF8Encoding]::new($false)
)

Write-Host "Docker build context prepared with runtime from WSL distribution '$WslDistribution'."
$manifest | Format-Table -AutoSize
