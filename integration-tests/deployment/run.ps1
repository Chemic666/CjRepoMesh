param(
    [string]$Cjpm = "",
    [string]$EnvSetup = "D:\Apps\Cangjie\envsetup.ps1"
)

$ErrorActionPreference = "Stop"
$testRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$projectRoot = [IO.Path]::GetFullPath((Join-Path $testRoot "..\.."))
$deploymentSource = Join-Path $projectRoot "deployment\windows"
$temporaryParent = [IO.Path]::GetFullPath((Join-Path $testRoot "..\.tmp"))
$runRoot = Join-Path $temporaryParent ("deployment-" + [Guid]::NewGuid().ToString("N"))
$deploymentRoot = Join-Path $runRoot "deployment\windows"
$startScript = Join-Path $deploymentRoot "start.ps1"
$stopScript = Join-Path $deploymentRoot "stop.ps1"
$doctorScript = Join-Path $deploymentRoot "doctor.ps1"
$packageSource = Join-Path $projectRoot "integration-tests\multirepo\packages\meshdep-v2-low"
$packageRoot = Join-Path $runRoot "fixture"
$storage = Join-Path $runRoot "storage"
$download = Join-Path $runRoot "downloaded.cjp"
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
$Cjpm = (Resolve-Path -LiteralPath $Cjpm).Path

$serverSource = Join-Path $projectRoot "server\target\release\bin\main.exe"
if (-not (Test-Path -LiteralPath $serverSource)) { throw "Build the server before running deployment tests." }
$resolvedRunRoot = [IO.Path]::GetFullPath($runRoot)
if (-not $resolvedRunRoot.StartsWith($temporaryParent + [IO.Path]::DirectorySeparatorChar,
    [StringComparison]::OrdinalIgnoreCase)) { throw "Invalid isolated deployment test root." }

New-Item -ItemType Directory -Force -Path $deploymentRoot, $packageRoot,
    (Join-Path $runRoot "server\target\release\bin") | Out-Null
Get-ChildItem -LiteralPath $deploymentSource -Filter *.ps1 | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $deploymentRoot
}
Copy-Item -LiteralPath $serverSource -Destination (Join-Path $runRoot "server\target\release\bin\main.exe")
Copy-Item -LiteralPath (Join-Path $packageSource "src") -Destination $packageRoot -Recurse
Copy-Item -LiteralPath (Join-Path $packageSource "cjpm.toml") -Destination $packageRoot
Copy-Item -LiteralPath (Join-Path $packageSource "README.md") -Destination $packageRoot

try {
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
        $lengthBytes = [BitConverter]::GetBytes([int]$metadataBytes.Length)
        $frame.Write($lengthBytes, 0, $lengthBytes.Length)
        $frame.Write($metadataBytes, 0, $metadataBytes.Length)
        $frame.WriteByte(1)
        $lengthBytes = [BitConverter]::GetBytes([int]$artifactBytes.Length)
        $frame.Write($lengthBytes, 0, $lengthBytes.Length)
        $frame.Write($artifactBytes, 0, $artifactBytes.Length)
        $publishBody = $frame.ToArray()
    } finally {
        $frame.Dispose()
    }

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
    # If stopping fails, leave the isolated state and logs available for inspection.
    & $stopScript | Out-Null
    Remove-Item -LiteralPath $resolvedRunRoot -Recurse -Force
    if (@(Get-ChildItem -LiteralPath $temporaryParent -Force).Count -eq 0) {
        Remove-Item -LiteralPath $temporaryParent -Force
    }
}
