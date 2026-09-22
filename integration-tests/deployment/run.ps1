param(
    [string]$Cjpm = "",
    [string]$EnvSetup = "D:\Apps\Cangjie\envsetup.ps1"
)

$ErrorActionPreference = "Stop"
$testRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$projectRoot = [IO.Path]::GetFullPath((Join-Path $testRoot "..\.."))
$deploymentRoot = Join-Path $projectRoot "deployment\windows"
$startScript = Join-Path $deploymentRoot "start.ps1"
$stopScript = Join-Path $deploymentRoot "stop.ps1"
$doctorScript = Join-Path $deploymentRoot "doctor.ps1"
$packageRoot = Join-Path $projectRoot "integration-tests\multirepo\packages\meshdep-v2-low"
$storage = Join-Path $testRoot "storage"
$download = Join-Path $testRoot "downloaded.cjp"
$port = 39600

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

& $stopScript | Out-Null
Remove-TestOutput $storage
Remove-TestOutput $download

Push-Location $packageRoot
try {
    & $Cjpm bundle
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to bundle deployment fixture"
    }
} finally {
    Pop-Location
}

$metadataBytes = [IO.File]::ReadAllBytes((Join-Path $packageRoot "target\meta-data.json"))
$artifactPath = Join-Path $packageRoot "target\meshdep-2.0.0.cjp"
$artifactBytes = [IO.File]::ReadAllBytes($artifactPath)
$frame = [IO.MemoryStream]::new()
try {
    $frame.WriteByte(1)
    $frame.Write([BitConverter]::GetBytes([int]$metadataBytes.Length))
    $frame.Write($metadataBytes)
    $frame.WriteByte(1)
    $frame.Write([BitConverter]::GetBytes([int]$artifactBytes.Length))
    $frame.Write($artifactBytes)
    $publishBody = $frame.ToArray()
} finally {
    $frame.Dispose()
}

try {
    & $startScript -Port $port -Storage $storage -PublishToken "deployment-token" -NoBuild
    & $doctorScript
    if ($LASTEXITCODE -ne 0) {
        throw "Deployment doctor failed after first start"
    }
    Write-Host "PASS one-command deployment starts a healthy CjRepo process"

    Invoke-WebRequest -UseBasicParsing -Method Post -Uri "http://127.0.0.1:$port/pkg/meshdep" `
        -Headers @{ Authorization = "deployment-token" } -Body $publishBody | Out-Null
    Write-Host "PASS package is published to the deployed registry"

    & $stopScript
    & $startScript -Port $port -Storage $storage -PublishToken "deployment-token" -NoBuild
    Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$port/pkg/meshdep/2.0.0" `
        -OutFile $download
    if ((Get-FileHash -Algorithm SHA256 $download).Hash -ne
        (Get-FileHash -Algorithm SHA256 $artifactPath).Hash) {
        throw "Persisted artifact checksum mismatch after restart"
    }
    Write-Host "PASS registry data survives stop and restart"
    Write-Host "All one-command deployment integration tests passed."
} finally {
    & $stopScript -ErrorAction SilentlyContinue | Out-Null
}
