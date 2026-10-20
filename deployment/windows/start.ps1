[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8080,
    [string]$Storage = "",
    [string]$PublishToken = "",
    [string]$ReadToken = "",
    [string]$Upstream = "",
    [string]$UpstreamToken = "",
    [ValidateRange(0, 31536000)]
    [long]$ProxyTtlSeconds = 86400,
    [string]$EnvSetup = "",
    [switch]$NoBuild
)

$ErrorActionPreference = "Stop"
$scriptRoot = [IO.Path]::GetFullPath($PSScriptRoot)
. (Join-Path $scriptRoot "common.ps1")
$projectRoot = [IO.Path]::GetFullPath((Join-Path $scriptRoot "..\.."))
$serverRoot = Join-Path $projectRoot "server"
$serverExe = Join-Path $serverRoot "target\release\bin\main.exe"
$runRoot = Join-Path $scriptRoot "run"
$logRoot = Join-Path $scriptRoot "logs"
$statePath = Join-Path $runRoot "cjrepo.json"

if (-not [string]::IsNullOrEmpty($ReadToken) -and [string]::IsNullOrEmpty($PublishToken)) {
    throw "PublishToken is required when ReadToken is set."
}

if (-not [string]::IsNullOrEmpty($Upstream)) {
    $upstreamUri = $null
    if (-not [Uri]::TryCreate($Upstream, [UriKind]::Absolute, [ref]$upstreamUri) -or
        $upstreamUri.Scheme -notin @("http", "https") -or
        $upstreamUri.UserInfo -or $upstreamUri.Query -or $upstreamUri.Fragment) {
        throw "Upstream must be an absolute HTTP(S) URL without embedded credentials, query parameters or fragments. Use -UpstreamToken for authentication."
    }
}

if ([string]::IsNullOrWhiteSpace($Storage)) {
    $Storage = Join-Path $scriptRoot "data"
}
$Storage = [IO.Path]::GetFullPath($Storage)

if (Test-Path -LiteralPath $statePath) {
    $previous = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    $previousProcess = Get-Process -Id ([int]$previous.pid) -ErrorAction SilentlyContinue
    if ($null -ne $previousProcess) {
        if (Test-CjRepoProcessIdentity $previousProcess $previous $serverExe) {
            throw "CjRepo is already running (PID $($previous.pid), port $($previous.port)). Run stop.ps1 first."
        }
        throw "Deployment process identity cannot be verified (PID $($previous.pid)). Inspect the process and state file manually; refusing to overwrite state."
    }
    Remove-Item -LiteralPath $statePath -Force
}

if (@(Get-CjRepoPortListener $Port).Count -ne 0) {
    throw "Port $Port is already in use. Choose another port or stop its owner before starting CjRepo."
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
    "CJREPO_ADDRESS",
    "CJREPO_PORT",
    "CJREPO_STORAGE",
    "CJREPO_PUBLISH_TOKEN",
    "CJREPO_READ_TOKEN",
    "CJREPO_UPSTREAM",
    "CJREPO_UPSTREAM_TOKEN",
    "CJREPO_PROXY_TTL_SECONDS"
)
$oldEnvironment = @{}
foreach ($name in $environmentNames) {
    $oldEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

$process = $null
try {
    # This deployment entry point is local-only, regardless of inherited SDK or shell settings.
    $env:CJREPO_ADDRESS = "127.0.0.1"
    $env:CJREPO_PORT = [string]$Port
    $env:CJREPO_STORAGE = $Storage
    $env:CJREPO_PUBLISH_TOKEN = $PublishToken
    $env:CJREPO_READ_TOKEN = $ReadToken
    $env:CJREPO_UPSTREAM = $Upstream
    $env:CJREPO_UPSTREAM_TOKEN = $UpstreamToken
    $env:CJREPO_PROXY_TTL_SECONDS = [string]$ProxyTtlSeconds

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
        $health = $null
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 1
        } catch {
            # The process can still be starting; retry within the bounded readiness loop.
        }
        if ($health.status -eq "ok" -and $health.service -eq "cjrepo") {
            $listeners = @(Get-CjRepoPortListener $Port)
            if (@($listeners | Where-Object { $_.OwningProcess -ne $process.Id }).Count -ne 0) {
                throw "Health endpoint belongs to another process. Refusing to adopt port $Port."
            }
            $process.Refresh()
            if (-not $process.HasExited -and
                @($listeners | Where-Object { $_.LocalAddress -eq "127.0.0.1" -and $_.OwningProcess -eq $process.Id }).Count -ne 0) {
                $ready = $true
                break
            }
        }
        Start-Sleep -Milliseconds 100
    }
    if (-not $ready) {
        throw "CjRepo did not become healthy. See $stderrPath"
    }

    [ordered]@{
        pid = $process.Id
        executable = [IO.Path]::GetFullPath($serverExe)
        processStartTimeUtc = $process.StartTime.ToUniversalTime().ToString("o")
        port = $Port
        storage = $Storage
        upstream = $Upstream
        proxyTtlSeconds = $ProxyTtlSeconds
        startedAt = [DateTimeOffset]::Now.ToString("o")
    } | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
} catch {
    if ($null -ne $process -and -not $process.HasExited) {
        Stop-Process -InputObject $process -Force -ErrorAction SilentlyContinue
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
