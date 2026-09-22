param(
    [string]$Cjpm = "",
    [string]$EnvSetup = "D:\Apps\Cangjie\envsetup.ps1",
    [switch]$SkipServerBuild
)

$ErrorActionPreference = "Stop"
$suiteRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$projectRoot = [IO.Path]::GetFullPath((Join-Path $suiteRoot ".."))

if (Test-Path -LiteralPath $EnvSetup) { . $EnvSetup }
if (-not $env:CANGJIE_STDX_PATH) {
    $env:CANGJIE_STDX_PATH = "D:\Apps\Cangjie\stdx\1.1.3.1\windows_x86_64_cjnative\static\stdx"
}
if ([string]::IsNullOrWhiteSpace($Cjpm)) {
    $Cjpm = Join-Path $projectRoot "cjpm\target\release\bin\cjpm.exe"
}
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python 3 is required for the shared cross-platform integration runner"
}

$total = [Diagnostics.Stopwatch]::StartNew()
$coreArguments = @((Join-Path $suiteRoot "run.py"), "--cjpm", $Cjpm)
if ($SkipServerBuild) { $coreArguments += "--skip-server-build" }

& python @coreArguments
if ($LASTEXITCODE -ne 0) { throw "Core cross-platform integration suites failed" }

Write-Host ""
Write-Host "=== Windows deployment ===" -ForegroundColor Cyan
$deploymentTimer = [Diagnostics.Stopwatch]::StartNew()
& (Join-Path $suiteRoot "deployment\run.ps1") -Cjpm $Cjpm -EnvSetup $EnvSetup
$deploymentTimer.Stop()

$total.Stop()
Write-Host ""
Write-Host "=== CjRepoMesh Windows integration summary ===" -ForegroundColor Green
Write-Host ("Core cross-platform suites  PASS")
Write-Host ("Windows deployment          PASS  {0,8:N2}s" -f $deploymentTimer.Elapsed.TotalSeconds)
Write-Host ("All 5 suites passed in {0:N2} seconds." -f $total.Elapsed.TotalSeconds) -ForegroundColor Green
