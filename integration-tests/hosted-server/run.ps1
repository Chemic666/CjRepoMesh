param(
    [string]$Cjpm = "",
    [string]$EnvSetup = "D:\Apps\Cangjie\envsetup.ps1"
)

$ErrorActionPreference = "Stop"
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
if (Test-Path -LiteralPath $EnvSetup) { . $EnvSetup }
if (-not $env:CANGJIE_STDX_PATH) {
    $env:CANGJIE_STDX_PATH = "D:\Apps\Cangjie\stdx\1.1.3.1\windows_x86_64_cjnative\static\stdx"
}
if ([string]::IsNullOrWhiteSpace($Cjpm)) {
    $Cjpm = Join-Path $projectRoot "cjpm\target\release\bin\cjpm.exe"
}
& python (Join-Path $projectRoot "integration-tests\run.py") --suite hosted --cjpm $Cjpm
if ($LASTEXITCODE -ne 0) { throw "Hosted repository integration suite failed" }
