param(
    [string]$Cjpm = "",
    [string]$EnvSetup = "D:\Apps\Cangjie\envsetup.ps1"
)

$ErrorActionPreference = "Stop"
$testRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$projectRoot = [IO.Path]::GetFullPath((Join-Path $testRoot "..\.."))

if ([string]::IsNullOrWhiteSpace($Cjpm)) {
    $Cjpm = Join-Path $projectRoot "cjpm\target\release\bin\cjpm.exe"
}

if (Test-Path -LiteralPath $EnvSetup) {
    . $EnvSetup
}
if (-not $env:CANGJIE_STDX_PATH) {
    $env:CANGJIE_STDX_PATH = "D:\Apps\Cangjie\stdx\1.1.3.1\windows_x86_64_cjnative\static\stdx"
}
if (-not $env:MINGW_PATH) {
    $env:MINGW_PATH = "D:\Apps\Cangjie\build-tools\llvm-mingw-20220906-msvcrt-x86_64"
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

function Reset-App([string]$name) {
    $app = Join-Path $testRoot $name
    Remove-TestOutput (Join-Path $app "cache")
    Remove-TestOutput (Join-Path $app "target")
    Remove-TestOutput (Join-Path $app "cjpm.lock")
}

function Invoke-Cjpm([string]$workDir, [string[]]$arguments, [bool]$expectSuccess = $true) {
    Push-Location $workDir
    try {
        $text = (& $Cjpm @arguments 2>&1 | Out-String)
        $exitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($expectSuccess -and $exitCode -ne 0) {
        throw "cjpm $($arguments -join ' ') failed in ${workDir}:`n$text"
    }
    if (-not $expectSuccess -and $exitCode -eq 0) {
        throw "cjpm $($arguments -join ' ') unexpectedly succeeded in $workDir"
    }
    return [pscustomobject]@{ ExitCode = $exitCode; Output = $text }
}

function Invoke-WithRepositories(
    [string]$appName,
    [array]$repositories,
    [string[]]$arguments,
    [bool]$expectSuccess = $true
) {
    $processes = @()
    try {
        foreach ($repository in $repositories) {
            $processes += Start-Process -FilePath "python" `
                -ArgumentList @((Join-Path $testRoot "server.py"), $repository.Port, $repository.Mode) `
                -WorkingDirectory $testRoot -WindowStyle Hidden -PassThru
        }
        Start-Sleep -Seconds 1
        return Invoke-Cjpm (Join-Path $testRoot $appName) $arguments $expectSuccess
    } finally {
        foreach ($process in $processes) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
    }
}

function Assert-Output([object]$result, [string]$expected) {
    if (-not $result.Output.Contains($expected)) {
        throw "Expected output '$expected', got:`n$($result.Output)"
    }
}

foreach ($package in @(
    "meshdep-v1-high",
    "meshdep-v1-low",
    "meshdep-v2-low",
    "company-auth-v1-private",
    "company-auth-v9-public"
)) {
    Invoke-Cjpm (Join-Path $testRoot "packages\$package") @("bundle") | Out-Null
}

$high = @{ Port = 39141; Mode = "high" }
$low = @{ Port = 39142; Mode = "low" }
$missing = @{ Port = 39143; Mode = "missing" }
$serverError = @{ Port = 39143; Mode = "server-error" }
$unauthorized = @{ Port = 39144; Mode = "unauthorized" }
$token = @{ Port = 39145; Mode = "token" }
$private = @{ Port = 39146; Mode = "private" }
$privateMissing = @{ Port = 39146; Mode = "missing" }
$public = @{ Port = 39147; Mode = "public" }

Reset-App "app"
$result = Invoke-WithRepositories "app" @($high, $low) @("run")
Assert-Output $result "low-2.0.0"
Write-Host "PASS highest compatible version across repositories"

Reset-App "app-pinned"
$result = Invoke-WithRepositories "app-pinned" @($high, $low) @("run")
Assert-Output $result "high-1.0.0"
Write-Host "PASS repository priority breaks duplicate-version ties"

Reset-App "app-fallback"
$result = Invoke-WithRepositories "app-fallback" @($missing, $low) @("run")
Assert-Output $result "low-2.0.0"
Write-Host "PASS 404 fallback"

Reset-App "app-fallback"
$result = Invoke-WithRepositories "app-fallback" @($serverError, $low) @("run")
Assert-Output $result "low-2.0.0"
Assert-Output $result "trying the next repository"
Write-Host "PASS 5xx fallback"

Reset-App "app-auth-barrier"
$lowLog = Join-Path $testRoot "low.requests.log"
Remove-TestOutput $lowLog
$result = Invoke-WithRepositories "app-auth-barrier" @($unauthorized, $low) @("run") $false
if ((Test-Path -LiteralPath $lowLog) -and (Get-Item -LiteralPath $lowLog).Length -gt 0) {
    throw "401 security barrier failed: lower-priority repository was accessed"
}
Assert-Output $result "status 401"
Write-Host "PASS 401 blocks fallback"

Reset-App "app-token"
Remove-Item Env:CJREPOMESH_TEST_TOKEN -ErrorAction SilentlyContinue
$result = Invoke-Cjpm (Join-Path $testRoot "app-token") @("check") $false
Assert-Output $result "environment variable 'CJREPOMESH_TEST_TOKEN'"
$env:CJREPOMESH_TEST_TOKEN = "secret-token"
$result = Invoke-WithRepositories "app-token" @($token) @("run")
Assert-Output $result "high-1.0.0"
Write-Host "PASS token-env authentication"

Reset-App "app-namespace"
$publicLog = Join-Path $testRoot "public.requests.log"
Remove-TestOutput $publicLog
$result = Invoke-WithRepositories "app-namespace" @($private, $public) @("run")
Assert-Output $result "private-1.0.0"
if ((Test-Path -LiteralPath $publicLog) -and (Get-Item -LiteralPath $publicLog).Length -gt 0) {
    throw "exclusive namespace route accessed the public repository"
}

Reset-App "app-namespace"
Remove-TestOutput $publicLog
$result = Invoke-WithRepositories "app-namespace" @($privateMissing, $public) @("run") $false
Assert-Output $result "status 404"
if ((Test-Path -LiteralPath $publicLog) -and (Get-Item -LiteralPath $publicLog).Length -gt 0) {
    throw "exclusive namespace route fell back to the public repository"
}
Write-Host "PASS exclusive namespace dependency-confusion protection"

Reset-App "app-legacy"
$result = Invoke-WithRepositories "app-legacy" @($low) @("run")
Assert-Output $result "low-2.0.0"
Invoke-WithRepositories "app-legacy" @($low) @("update") | Out-Null
$legacyRoot = Join-Path $testRoot "app-legacy\cache\repository"
if (-not (Test-Path -LiteralPath (Join-Path $legacyRoot "index\default\me\sh\meshdep"))) {
    throw "legacy repository.home index path was not preserved"
}
if (Test-Path -LiteralPath (Join-Path $legacyRoot "registries")) {
    throw "legacy repository.home unexpectedly used multi-registry cache layout"
}
Write-Host "PASS legacy repository.home compatibility"

Write-Host "All multi-registry integration tests passed."
