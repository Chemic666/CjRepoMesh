param(
    [string]$Cjpm = "",
    [string]$EnvSetup = "D:\Apps\Cangjie\envsetup.ps1"
)

$ErrorActionPreference = "Stop"
$suiteRoot = [IO.Path]::GetFullPath($PSScriptRoot)

$suites = @(
    [ordered]@{ Name = "Multi-repository cjpm"; Script = "multirepo\run.ps1" },
    [ordered]@{ Name = "Hosted repository"; Script = "hosted-server\run.ps1" },
    [ordered]@{ Name = "Proxy repository"; Script = "proxy\run.ps1" },
    [ordered]@{ Name = "Repository sync"; Script = "sync\run.ps1" },
    [ordered]@{ Name = "Windows deployment"; Script = "deployment\run.ps1" }
)

$results = @()
$total = [Diagnostics.Stopwatch]::StartNew()

foreach ($suite in $suites) {
    $scriptPath = Join-Path $suiteRoot $suite.Script
    if (-not (Test-Path -LiteralPath $scriptPath)) {
        throw "Integration test entry not found: $scriptPath"
    }

    Write-Host ""
    Write-Host "=== $($suite.Name) ===" -ForegroundColor Cyan
    $timer = [Diagnostics.Stopwatch]::StartNew()

    & $scriptPath -Cjpm $Cjpm -EnvSetup $EnvSetup

    $timer.Stop()
    $results += [PSCustomObject]@{
        Suite = $suite.Name
        Result = "PASS"
        Seconds = [Math]::Round($timer.Elapsed.TotalSeconds, 2)
    }
}

$total.Stop()
Write-Host ""
Write-Host "=== CjRepoMesh integration summary ===" -ForegroundColor Green
$results | Format-Table -AutoSize
Write-Host ("All {0} suites passed in {1:N2} seconds." -f $results.Count, $total.Elapsed.TotalSeconds) -ForegroundColor Green
