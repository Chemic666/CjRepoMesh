[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8080,
    [string]$Storage = "",
    [string]$PublishToken = "",
    [string]$Upstream = "",
    [string]$UpstreamToken = "",
    [string]$EnvSetup = "",
    [switch]$NoBuild
)

$ErrorActionPreference = "Stop"
$scriptRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$projectRoot = [IO.Path]::GetFullPath((Join-Path $scriptRoot "..\.."))
$serverRoot = Join-Path $projectRoot "server"
$serverExe = Join-Path $serverRoot "target\release\bin\main.exe"
$runRoot = Join-Path $scriptRoot "run"
$logRoot = Join-Path $scriptRoot "logs"
$statePath = Join-Path $runRoot "cjrepo.json"

if ([string]::IsNullOrWhiteSpace($Storage)) {
    $Storage = Join-Path $scriptRoot "data"
}
$Storage = [IO.Path]::GetFullPath($Storage)

function Get-ProcessPath([int]$ProcessId) {
    try {
        return (Get-Process -Id $ProcessId -ErrorAction Stop).Path
    } catch {
        return $null
    }
}

if (Test-Path -LiteralPath $statePath) {
    $previous = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    $actualPath = Get-ProcessPath ([int]$previous.pid)
    if ($actualPath -and
        [IO.Path]::GetFullPath($actualPath).Equals([IO.Path]::GetFullPath([string]$previous.executable),
            [StringComparison]::OrdinalIgnoreCase)) {
        throw "CjRepo is already running (PID $($previous.pid), port $($previous.port)). Run stop.ps1 first."
    }
    Remove-Item -LiteralPath $statePath -Force
}

if ([string]::IsNullOrWhiteSpace($EnvSetup)) {
    $localSetup = "D:\Apps\Cangjie\envsetup.ps1"
    if (Test-Path -LiteralPath $localSetup) {
        $EnvSetup = $localSetup
    }
}
if (-not [string]::IsNullOrWhiteSpace($EnvSetup)) {
    if (-not (Test-Path -LiteralPath $EnvSetup)) {
        throw "Cangjie environment setup script not found: $EnvSetup"
    }
    . $EnvSetup
}

if (-not $NoBuild) {
    if (-not (Get-Command cjpm -ErrorAction SilentlyContinue)) {
        throw "cjpm is not available. Load the Cangjie environment or pass -EnvSetup."
    }
    if (-not $env:CANGJIE_STDX_PATH) {
        throw "CANGJIE_STDX_PATH is not set. Configure the stdx library before deployment."
    }
    Push-Location $serverRoot
    try {
        & cjpm build
        if ($LASTEXITCODE -ne 0) {
            throw "CjRepo Server build failed with exit code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
}

if (-not (Test-Path -LiteralPath $serverExe)) {
    throw "CjRepo Server executable not found: $serverExe"
}

New-Item -ItemType Directory -Force -Path $Storage, $runRoot, $logRoot | Out-Null
$stdoutPath = Join-Path $logRoot "cjrepo.out.log"
$stderrPath = Join-Path $logRoot "cjrepo.err.log"

$environmentNames = @(
    "CJREPO_PORT",
    "CJREPO_STORAGE",
    "CJREPO_PUBLISH_TOKEN",
    "CJREPO_UPSTREAM",
    "CJREPO_UPSTREAM_TOKEN"
)
$oldEnvironment = @{}
foreach ($name in $environmentNames) {
    $oldEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

$process = $null
try {
    $env:CJREPO_PORT = [string]$Port
    $env:CJREPO_STORAGE = $Storage
    $env:CJREPO_PUBLISH_TOKEN = $PublishToken
    $env:CJREPO_UPSTREAM = $Upstream
    $env:CJREPO_UPSTREAM_TOKEN = $UpstreamToken

    $process = Start-Process -FilePath $serverExe -WorkingDirectory $serverRoot `
        -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath `
        -WindowStyle Hidden -PassThru
} finally {
    foreach ($name in $environmentNames) {
        $oldValue = $oldEnvironment[$name]
        if ($null -eq $oldValue) {
            Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
        } else {
            Set-Item -LiteralPath "Env:$name" -Value $oldValue
        }
    }
}

try {
    $ready = $false
    foreach ($attempt in 1..50) {
        $process.Refresh()
        if ($process.HasExited) {
            throw "CjRepo exited during startup with code $($process.ExitCode). See $stderrPath"
        }
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 1
            if ($health.status -eq "ok" -and $health.service -eq "cjrepo") {
                $ready = $true
                break
            }
        } catch {
            Start-Sleep -Milliseconds 100
        }
    }
    if (-not $ready) {
        throw "CjRepo did not become healthy. See $stderrPath"
    }

    [ordered]@{
        pid = $process.Id
        executable = [IO.Path]::GetFullPath($serverExe)
        port = $Port
        storage = $Storage
        upstream = $Upstream
        startedAt = [DateTimeOffset]::Now.ToString("o")
    } | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
} catch {
    if ($null -ne $process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
    throw
}

Write-Host "CjRepo is ready: http://127.0.0.1:$Port"
Write-Host "Storage: $Storage"
Write-Host "Process: $($process.Id)"
Write-Host "Health:  http://127.0.0.1:$Port/health"
if ([string]::IsNullOrWhiteSpace($PublishToken)) {
    Write-Warning "Publishing is currently unauthenticated. Restart with -PublishToken for shared environments."
}
