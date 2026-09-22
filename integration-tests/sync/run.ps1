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
$mirrorStorage = Join-Path $testRoot "mirror-storage"
$destinationStorage = Join-Path $testRoot "destination-storage"
$appRoot = Join-Path $testRoot "app"
$upstreamLog = Join-Path $fixtureRoot "low.requests.log"
$mirrorManifest = Join-Path $testRoot "mirror-manifest.txt"
$invalidMirrorManifest = Join-Path $testRoot "mirror-manifest-invalid.txt"

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

function Wait-Health([int]$port) {
    foreach ($attempt in 1..50) {
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health"
            if ($health.status -eq "ok") {
                return
            }
        } catch {
            Start-Sleep -Milliseconds 100
        }
    }
    throw "Repository on port $port did not become ready"
}

foreach ($fixture in @("meshdep-v1-low", "meshdep-v2-low")) {
    Push-Location (Join-Path $fixtureRoot "packages\$fixture")
    try {
        & $Cjpm bundle
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to bundle sync fixture $fixture"
        }
    } finally {
        Pop-Location
    }
}

foreach ($path in @(
    $mirrorStorage,
    $destinationStorage,
    (Join-Path $appRoot "cache"),
    (Join-Path $appRoot "target"),
    (Join-Path $appRoot "cjpm.lock"),
    $upstreamLog
)) {
    Remove-TestOutput $path
}

Push-Location $serverRoot
try {
    cjpm build
    if ($LASTEXITCODE -ne 0) {
        throw "CjRepo Server build failed"
    }
} finally {
    Pop-Location
}

$savedEnvironment = @{
    CJREPO_PORT = $env:CJREPO_PORT
    CJREPO_STORAGE = $env:CJREPO_STORAGE
    CJREPO_UPSTREAM = $env:CJREPO_UPSTREAM
    CJREPO_PUBLISH_TOKEN = $env:CJREPO_PUBLISH_TOKEN
    CJREPO_SYNC_DESTINATION_TOKEN = $env:CJREPO_SYNC_DESTINATION_TOKEN
}
$processes = [Collections.Generic.List[Diagnostics.Process]]::new()
try {
    $upstream = Start-Process -FilePath "python" `
        -ArgumentList @((Join-Path $fixtureRoot "server.py"), 39401, "low") `
        -WorkingDirectory $fixtureRoot -WindowStyle Hidden -PassThru
    $processes.Add($upstream)
    Start-Sleep -Milliseconds 500

    $env:CJREPO_STORAGE = $mirrorStorage
    $mirrorOutput = (& $serverExe mirror-manifest "http://127.0.0.1:39401" $mirrorManifest 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0 -or -not $mirrorOutput.Contains("total=2 succeeded=2 failed=0")) {
        throw "Mirror manifest command failed:`n$mirrorOutput"
    }
    $firstRequestCount = @(Get-Content -LiteralPath $upstreamLog).Count

    $mirrorAgain = (& $serverExe mirror-manifest "http://127.0.0.1:39401" $mirrorManifest 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0 -or -not $mirrorAgain.Contains("total=2 succeeded=2 failed=0") -or
        @($mirrorAgain -split "result=SKIP").Count -ne 3 -or
        @(Get-Content -LiteralPath $upstreamLog).Count -ne $firstRequestCount) {
        throw "Idempotent mirror check failed:`n$mirrorAgain"
    }

    $invalidMirror = (& $serverExe mirror-manifest "http://127.0.0.1:39401" $invalidMirrorManifest 2>&1 | Out-String)
    if ($LASTEXITCODE -eq 0 -or -not $invalidMirror.Contains("total=2 succeeded=1 failed=1") -or
        @(Get-Content -LiteralPath $upstreamLog).Count -ne $firstRequestCount) {
        throw "Mirror manifest failure summary check failed:`n$invalidMirror"
    }
    Write-Host "PASS batch mirror manifest is checksum-verified, idempotent and reports partial failure"

    Stop-Process -Id $upstream.Id -Force
    $processes.Remove($upstream) | Out-Null

    $env:CJREPO_PORT = "39501"
    $env:CJREPO_STORAGE = $mirrorStorage
    $env:CJREPO_UPSTREAM = $null
    $env:CJREPO_PUBLISH_TOKEN = $null
    $source = Start-Process -FilePath $serverExe -WorkingDirectory $serverRoot -WindowStyle Hidden -PassThru
    $processes.Add($source)

    $env:CJREPO_PORT = "39502"
    $env:CJREPO_STORAGE = $destinationStorage
    $env:CJREPO_PUBLISH_TOKEN = "sync-token"
    $destination = Start-Process -FilePath $serverExe -WorkingDirectory $serverRoot -WindowStyle Hidden -PassThru
    $processes.Add($destination)
    Wait-Health 39501
    Wait-Health 39502

    $env:CJREPO_SYNC_DESTINATION_TOKEN = "sync-token"
    $syncOutput = (& $serverExe sync-manifest "http://127.0.0.1:39501" "http://127.0.0.1:39502" $mirrorManifest 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0 -or -not $syncOutput.Contains("total=2 succeeded=2 failed=0") -or
        @($syncOutput -split "result=SYNCED").Count -ne 3) {
        throw "Repository sync manifest failed:`n$syncOutput"
    }
    $syncAgain = (& $serverExe sync-manifest "http://127.0.0.1:39501" "http://127.0.0.1:39502" $mirrorManifest 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0 -or -not $syncAgain.Contains("total=2 succeeded=2 failed=0") -or
        @($syncAgain -split "result=SKIP").Count -ne 3) {
        throw "Idempotent repository sync manifest failed:`n$syncAgain"
    }

    $invalidSync = (& $serverExe sync-manifest "http://127.0.0.1:39501" "http://127.0.0.1:39502" $invalidMirrorManifest 2>&1 | Out-String)
    if ($LASTEXITCODE -eq 0 -or -not $invalidSync.Contains("total=2 succeeded=1 failed=1")) {
        throw "Repository sync manifest failure summary check failed:`n$invalidSync"
    }
    Write-Host "PASS batch CjRepo-to-CjRepo sync is authenticated, idempotent and reports partial failure"

    Stop-Process -Id $source.Id -Force
    $processes.Remove($source) | Out-Null
    Push-Location $appRoot
    try {
        $appOutput = (& $Cjpm run 2>&1 | Out-String)
        $appExit = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($appExit -ne 0 -or -not $appOutput.Contains("low-2.0.0")) {
        throw "Synced destination could not build while source was offline:`n$appOutput"
    }
    Write-Host "PASS synced destination builds while the source repository is offline"
    Write-Host "All mirror and repository sync integration tests passed."
} finally {
    foreach ($process in $processes) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
    foreach ($entry in $savedEnvironment.GetEnumerator()) {
        Set-Item -Path "Env:$($entry.Key)" -Value $entry.Value
    }
}
