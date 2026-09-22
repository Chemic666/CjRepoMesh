param(
    [string]$Cjpm = "",
    [string]$EnvSetup = "D:\Apps\Cangjie\envsetup.ps1"
)

$ErrorActionPreference = "Stop"
$testRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$projectRoot = [IO.Path]::GetFullPath((Join-Path $testRoot "..\.."))
$serverRoot = Join-Path $projectRoot "server"
$serverExe = Join-Path $serverRoot "target\release\bin\main.exe"
$fixtureRoot = Join-Path $projectRoot "integration-tests\multirepo"
$appRoot = Join-Path $testRoot "app"
$storage = Join-Path $testRoot "storage"
$proxyOut = Join-Path $testRoot "proxy.stdout.log"
$proxyErr = Join-Path $testRoot "proxy.stderr.log"
$corruptProxyOut = Join-Path $testRoot "proxy-corrupt.stdout.log"
$corruptProxyErr = Join-Path $testRoot "proxy-corrupt.stderr.log"
$upstreamLog = Join-Path $fixtureRoot "low.requests.log"
$corruptUpstreamLog = Join-Path $fixtureRoot "corrupt.requests.log"

if ([string]::IsNullOrWhiteSpace($Cjpm)) {
    $Cjpm = Join-Path $projectRoot "cjpm\target\release\bin\cjpm.exe"
}
if (Test-Path -LiteralPath $EnvSetup) {
    . $EnvSetup
}
if (-not $env:CANGJIE_STDX_PATH) {
    $env:CANGJIE_STDX_PATH = "D:\Apps\Cangjie\stdx\1.1.3.1\windows_x86_64_cjnative\static\stdx"
}
if (-not (Test-Path -LiteralPath $Cjpm)) {
    throw "cjpm executable not found: $Cjpm"
}
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python is required only for the local mock upstream; install it manually before running this test"
}

function Remove-TestOutput([string]$path) {
    $resolved = [IO.Path]::GetFullPath($path)
    $allowedRoots = @($testRoot, $fixtureRoot)
    if (-not ($allowedRoots | Where-Object {
        $resolved.StartsWith($_ + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase)
    })) {
        throw "Refusing to remove path outside test roots: $resolved"
    }
    if (Test-Path -LiteralPath $resolved) {
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}

function Reset-App {
    Remove-TestOutput (Join-Path $appRoot "cache")
    Remove-TestOutput (Join-Path $appRoot "target")
    Remove-TestOutput (Join-Path $appRoot "cjpm.lock")
}

function Invoke-App {
    Push-Location $appRoot
    try {
        $output = (& $Cjpm run 2>&1 | Out-String)
        $exitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($exitCode -ne 0 -or -not $output.Contains("low-2.0.0")) {
        throw "Proxy-backed cjpm run failed:`n$output"
    }
}

function Invoke-ConcurrentGet([string]$Uri, [int]$Count) {
    $client = [Net.Http.HttpClient]::new()
    $responses = @()
    try {
        $tasks = @()
        foreach ($requestNumber in 1..$Count) {
            $tasks += $client.GetAsync($Uri)
        }
        [Threading.Tasks.Task]::WaitAll([Threading.Tasks.Task[]]$tasks)
        foreach ($task in $tasks) {
            $response = $task.Result
            $responses += $response
            if ([int]$response.StatusCode -ne 200) {
                throw "Concurrent GET failed for ${Uri}: $($response.StatusCode)"
            }
            $null = $response.Content.ReadAsByteArrayAsync().Result
        }
    } finally {
        foreach ($response in $responses) {
            $response.Dispose()
        }
        $client.Dispose()
    }
}

foreach ($fixture in @("meshdep-v1-low", "meshdep-v2-low")) {
    Push-Location (Join-Path $fixtureRoot "packages\$fixture")
    try {
        & $Cjpm bundle
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to bundle proxy fixture $fixture"
        }
    } finally {
        Pop-Location
    }
}

Remove-TestOutput $storage
Remove-TestOutput $proxyOut
Remove-TestOutput $proxyErr
Remove-TestOutput $corruptProxyOut
Remove-TestOutput $corruptProxyErr
Remove-TestOutput $upstreamLog
Remove-TestOutput $corruptUpstreamLog
Reset-App

Push-Location $serverRoot
try {
    cjpm build
    if ($LASTEXITCODE -ne 0) {
        throw "CjRepo Server build failed"
    }
} finally {
    Pop-Location
}

$oldPort = $env:CJREPO_PORT
$oldStorage = $env:CJREPO_STORAGE
$oldUpstream = $env:CJREPO_UPSTREAM
$env:CJREPO_PORT = "39300"
$env:CJREPO_STORAGE = $storage
$env:CJREPO_UPSTREAM = "http://127.0.0.1:39301"
$upstreamProcess = $null
$proxyProcess = $null
try {
    $upstreamProcess = Start-Process -FilePath "python" `
        -ArgumentList @((Join-Path $fixtureRoot "server.py"), 39301, "low") `
        -WorkingDirectory $fixtureRoot -WindowStyle Hidden -PassThru
    $proxyProcess = Start-Process -FilePath $serverExe -WorkingDirectory $serverRoot `
        -WindowStyle Hidden -RedirectStandardOutput $proxyOut -RedirectStandardError $proxyErr -PassThru

    $ready = $false
    foreach ($attempt in 1..50) {
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:39300/health"
            if ($health.status -eq "ok") {
                $ready = $true
                break
            }
        } catch {
            Start-Sleep -Milliseconds 100
        }
    }
    if (-not $ready) {
        throw "CjRepo Proxy did not become ready"
    }

    Invoke-ConcurrentGet "http://127.0.0.1:39300/index/me/sh/meshdep" 8
    Invoke-ConcurrentGet "http://127.0.0.1:39300/pkg/meshdep/2.0.0" 8
    $concurrentRequests = @(Get-Content -LiteralPath $upstreamLog)
    if (($concurrentRequests | Where-Object { $_ -eq "GET /index/me/sh/meshdep" }).Count -ne 1 -or
        ($concurrentRequests | Where-Object { $_ -eq "GET /pkg/meshdep/2.0.0" }).Count -ne 1) {
        throw "Concurrent cache fill was not collapsed: $($concurrentRequests -join ', ')"
    }
    Write-Host "PASS concurrent proxy requests produce one verified upstream fill"

    Invoke-App
    $indexCache = Join-Path $storage "index\default\me\sh\meshdep"
    $artifactCache = Join-Path $storage "artifacts\default\meshdep\2.0.0\meshdep-2.0.0.cjp"
    if (-not (Test-Path -LiteralPath $indexCache) -or -not (Test-Path -LiteralPath $artifactCache)) {
        throw "Proxy MISS did not populate index and artifact caches"
    }
    $firstRequests = @(Get-Content -LiteralPath $upstreamLog)
    if (($firstRequests | Where-Object { $_ -eq "GET /index/me/sh/meshdep" }).Count -ne 1 -or
        ($firstRequests | Where-Object { $_ -eq "GET /pkg/meshdep/2.0.0" }).Count -ne 1) {
        throw "Unexpected upstream request set after cache MISS: $($firstRequests -join ', ')"
    }
    Write-Host "PASS proxy cache MISS fetches and validates index and artifact"

    Stop-Process -Id $upstreamProcess.Id -Force
    $upstreamProcess = $null
    Reset-App
    Invoke-App
    $secondRequests = @(Get-Content -LiteralPath $upstreamLog)
    if ($secondRequests.Count -ne $firstRequests.Count) {
        throw "Proxy cache HIT unexpectedly contacted the stopped upstream"
    }
    Write-Host "PASS proxy cache HIT supports an offline build"

    Stop-Process -Id $proxyProcess.Id -Force
    $proxyProcess = $null
    Remove-TestOutput $storage
    Reset-App
    $env:CJREPO_UPSTREAM = "http://127.0.0.1:39302"
    $upstreamProcess = Start-Process -FilePath "python" `
        -ArgumentList @((Join-Path $fixtureRoot "server.py"), 39302, "corrupt") `
        -WorkingDirectory $fixtureRoot -WindowStyle Hidden -PassThru
    $proxyProcess = Start-Process -FilePath $serverExe -WorkingDirectory $serverRoot `
        -WindowStyle Hidden -RedirectStandardOutput $corruptProxyOut `
        -RedirectStandardError $corruptProxyErr -PassThru

    $ready = $false
    foreach ($attempt in 1..50) {
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:39300/health"
            if ($health.status -eq "ok") {
                $ready = $true
                break
            }
        } catch {
            Start-Sleep -Milliseconds 100
        }
    }
    if (-not $ready) {
        throw "CjRepo Proxy did not restart for corruption test"
    }

    Push-Location $appRoot
    try {
        $corruptOutput = (& $Cjpm run 2>&1 | Out-String)
        $corruptExit = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    $corruptArtifactCache = Join-Path $storage "artifacts\default\meshdep\2.0.0\meshdep-2.0.0.cjp"
    if ($corruptExit -eq 0 -or -not $corruptOutput.Contains("status 502") -or
        (Test-Path -LiteralPath $corruptArtifactCache)) {
        throw "Proxy did not safely reject the corrupt upstream artifact:`n$corruptOutput"
    }
    Write-Host "PASS proxy rejects a corrupt upstream artifact without caching it"
    Write-Host "All proxy registry integration tests passed."
} finally {
    if ($null -ne $upstreamProcess) {
        Stop-Process -Id $upstreamProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($null -ne $proxyProcess) {
        Stop-Process -Id $proxyProcess.Id -Force -ErrorAction SilentlyContinue
    }
    $env:CJREPO_PORT = $oldPort
    $env:CJREPO_STORAGE = $oldStorage
    $env:CJREPO_UPSTREAM = $oldUpstream
}
