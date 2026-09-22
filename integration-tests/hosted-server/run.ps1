param(
    [string]$Cjpm = "",
    [string]$EnvSetup = "D:\Apps\Cangjie\envsetup.ps1"
)

$ErrorActionPreference = "Stop"
$testRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$projectRoot = [IO.Path]::GetFullPath((Join-Path $testRoot "..\.."))
$serverRoot = Join-Path $projectRoot "server"
$serverExe = Join-Path $serverRoot "target\release\bin\main.exe"
$packageRoot = Join-Path $projectRoot "integration-tests\multirepo\packages\meshdep-v2-low"
$appRoot = Join-Path $testRoot "app"
$storage = Join-Path $testRoot "storage"

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
    if (-not $resolved.StartsWith($testRoot + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove path outside test root: $resolved"
    }
    if (Test-Path -LiteralPath $resolved) {
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}

Remove-TestOutput $storage
Remove-TestOutput (Join-Path $appRoot "cache")
Remove-TestOutput (Join-Path $appRoot "target")
Remove-TestOutput (Join-Path $appRoot "cjpm.lock")

Push-Location $packageRoot
try {
    & $Cjpm bundle
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to bundle hosted registry fixture"
    }
} finally {
    Pop-Location
}

$indexDir = Join-Path $storage "index\default\me\sh"
$artifactDir = Join-Path $storage "artifacts\default\meshdep\2.0.0"
New-Item -ItemType Directory -Path $indexDir -Force | Out-Null
New-Item -ItemType Directory -Path $artifactDir -Force | Out-Null

$metadata = Get-Content -LiteralPath (Join-Path $packageRoot "target\meta-data.json") -Raw | ConvertFrom-Json
$metadata.index | ConvertTo-Json -Compress -Depth 20 |
    Set-Content -LiteralPath (Join-Path $indexDir "meshdep") -Encoding utf8NoBOM
$artifactSource = Join-Path $packageRoot "target\meshdep-2.0.0.cjp"
$artifactTarget = Join-Path $artifactDir "meshdep-2.0.0.cjp"
Copy-Item -LiteralPath $artifactSource -Destination $artifactTarget

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
$env:CJREPO_PORT = "39200"
$env:CJREPO_STORAGE = $storage
$serverProcess = $null
try {
    $serverProcess = Start-Process -FilePath $serverExe -WorkingDirectory $serverRoot `
        -WindowStyle Hidden -PassThru

    $ready = $false
    foreach ($attempt in 1..30) {
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:39200/health"
            if ($health.status -eq "ok") {
                $ready = $true
                break
            }
        } catch {
            Start-Sleep -Milliseconds 100
        }
    }
    if (-not $ready) {
        throw "CjRepo Server did not become ready"
    }
    Write-Host "PASS Cangjie server health check"

    $indexResponse = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:39200/index/me/sh/meshdep"
    $indexContent = if ($indexResponse.Content -is [byte[]]) {
        [Text.Encoding]::UTF8.GetString($indexResponse.Content)
    } else {
        [string]$indexResponse.Content
    }
    if ($indexResponse.StatusCode -ne 200 -or -not $indexContent.Contains('"version":"2.0.0"')) {
        throw "Hosted index response was invalid"
    }
    Write-Host "PASS hosted index download"

    $downloadPath = Join-Path $testRoot "downloaded.cjp"
    Remove-TestOutput $downloadPath
    Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:39200/pkg/meshdep/2.0.0" `
        -OutFile $downloadPath
    if ((Get-FileHash -Algorithm SHA256 $downloadPath).Hash -ne
        (Get-FileHash -Algorithm SHA256 $artifactSource).Hash) {
        throw "Hosted artifact checksum mismatch"
    }
    Write-Host "PASS hosted artifact download and checksum"

    Push-Location $appRoot
    try {
        $runOutput = (& $Cjpm run 2>&1 | Out-String)
        $runExit = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($runExit -ne 0 -or -not $runOutput.Contains("low-2.0.0")) {
        throw "End-to-end cjpm build failed:`n$runOutput"
    }
    Write-Host "PASS enhanced cjpm resolves and runs a package from CjRepo Server"
    Write-Host "All hosted registry integration tests passed."
} finally {
    if ($null -ne $serverProcess) {
        Stop-Process -Id $serverProcess.Id -Force -ErrorAction SilentlyContinue
    }
    $env:CJREPO_PORT = $oldPort
    $env:CJREPO_STORAGE = $oldStorage
}
