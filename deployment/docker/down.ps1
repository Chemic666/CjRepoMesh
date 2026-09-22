# Copyright (c) 2026 CjRepoMesh contributors.
# Licensed under the Apache License, Version 2.0.

[CmdletBinding()]
param([switch]$PurgeData)

$ErrorActionPreference = "Stop"
$scriptRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$envPath = Join-Path $scriptRoot ".env"
$arguments = @("compose", "--project-directory", $scriptRoot)
if (Test-Path -LiteralPath $envPath) {
    $arguments += @("--env-file", $envPath)
}
$arguments += @("down")
if ($PurgeData) {
    $arguments += "--volumes"
}

& docker @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose shutdown failed."
}
if ($PurgeData) {
    Write-Host "CjRepo container and persistent Docker volume were removed."
} else {
    Write-Host "CjRepo container was removed; persistent package data was retained."
}
