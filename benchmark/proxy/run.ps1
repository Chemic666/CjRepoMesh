param(
    [ValidateRange(3, 100)]
    [int]$ColdIterations = 10,
    [ValidateRange(5, 1000)]
    [int]$WarmIterations = 50,
    [string]$Cjpm = "",
    [string]$EnvSetup = "D:\Apps\Cangjie\envsetup.ps1"
)

$ErrorActionPreference = "Stop"
$benchmarkRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$projectRoot = [IO.Path]::GetFullPath((Join-Path $benchmarkRoot "..\.."))
$serverRoot = Join-Path $projectRoot "server"
$serverExe = Join-Path $serverRoot "target\release\bin\main.exe"
$fixtureRoot = Join-Path $projectRoot "integration-tests\multirepo"
$storage = Join-Path $benchmarkRoot "storage"
$proxyLog = Join-Path $benchmarkRoot "proxy.log"
$proxyErrorLog = Join-Path $benchmarkRoot "proxy-error.log"
$resultsRoot = Join-Path $projectRoot "benchmark\results"
$markdownPath = Join-Path $resultsRoot "proxy-benchmark.md"
$jsonPath = Join-Path $resultsRoot "proxy-benchmark.json"

if ([string]::IsNullOrWhiteSpace($Cjpm)) {
    $Cjpm = Join-Path $projectRoot "cjpm\target\release\bin\cjpm.exe"
}
if (Test-Path -LiteralPath $EnvSetup) { . $EnvSetup }
if (-not $env:CANGJIE_STDX_PATH) {
    $env:CANGJIE_STDX_PATH = "D:\Apps\Cangjie\stdx\1.1.3.1\windows_x86_64_cjnative\static\stdx"
}

function Remove-BenchmarkOutput([string]$Path) {
    $resolved = [IO.Path]::GetFullPath($Path)
    if (-not $resolved.StartsWith($benchmarkRoot + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove path outside benchmark root: $resolved"
    }
    if (Test-Path -LiteralPath $resolved) {
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}

function Invoke-Get([Net.Http.HttpClient]$Client, [string]$Uri) {
    $response = $Client.GetAsync($Uri).GetAwaiter().GetResult()
    try {
        if ([int]$response.StatusCode -ne 200) {
            throw "GET ${Uri} failed with $($response.StatusCode)"
        }
        $null = $response.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
    } finally {
        $response.Dispose()
    }
}

function Measure-Pair([Net.Http.HttpClient]$Client) {
    $watch = [Diagnostics.Stopwatch]::StartNew()
    Invoke-Get $Client "http://127.0.0.1:39700/index/me/sh/meshdep"
    Invoke-Get $Client "http://127.0.0.1:39700/pkg/meshdep/2.0.0"
    $watch.Stop()
    return $watch.Elapsed.TotalMilliseconds
}

function Get-Stats([double[]]$Samples) {
    $ordered = @($Samples | Sort-Object)
    $median = if ($ordered.Count % 2 -eq 0) {
        ($ordered[$ordered.Count / 2 - 1] + $ordered[$ordered.Count / 2]) / 2
    } else {
        $ordered[[Math]::Floor($ordered.Count / 2)]
    }
    $p95Index = [Math]::Max(0, [Math]::Ceiling($ordered.Count * 0.95) - 1)
    return [ordered]@{
        iterations = $ordered.Count
        medianMs = [Math]::Round($median, 3)
        p95Ms = [Math]::Round($ordered[$p95Index], 3)
        averageMs = [Math]::Round(($ordered | Measure-Object -Average).Average, 3)
        minMs = [Math]::Round($ordered[0], 3)
        maxMs = [Math]::Round($ordered[-1], 3)
        samplesMs = @($Samples | ForEach-Object { [Math]::Round($_, 3) })
    }
}

foreach ($fixture in @("meshdep-v1-low", "meshdep-v2-low")) {
    Push-Location (Join-Path $fixtureRoot "packages\$fixture")
    try {
        & $Cjpm bundle | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Failed to bundle benchmark fixture $fixture" }
    } finally { Pop-Location }
}

Push-Location $serverRoot
try {
    & cjpm build | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "CjRepo Server build failed" }
} finally { Pop-Location }

Remove-BenchmarkOutput $storage
Remove-BenchmarkOutput $proxyLog
Remove-BenchmarkOutput $proxyErrorLog
New-Item -ItemType Directory -Force -Path $resultsRoot | Out-Null

$oldPort = $env:CJREPO_PORT
$oldStorage = $env:CJREPO_STORAGE
$oldUpstream = $env:CJREPO_UPSTREAM
$oldTtl = $env:CJREPO_PROXY_TTL_SECONDS
$env:CJREPO_PORT = "39700"
$env:CJREPO_STORAGE = $storage
$env:CJREPO_UPSTREAM = "http://127.0.0.1:39701"
$env:CJREPO_PROXY_TTL_SECONDS = "86400"
$upstreamProcess = $null
$proxyProcess = $null
$client = $null
try {
    $upstreamProcess = Start-Process -FilePath "python" `
        -ArgumentList @((Join-Path $fixtureRoot "server.py"), 39701, "low") `
        -WorkingDirectory $fixtureRoot -WindowStyle Hidden -PassThru
    $proxyProcess = Start-Process -FilePath $serverExe -WorkingDirectory $serverRoot `
        -WindowStyle Hidden -RedirectStandardOutput $proxyLog `
        -RedirectStandardError $proxyErrorLog -PassThru

    $ready = $false
    foreach ($attempt in 1..50) {
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:39700/health"
            if ($health.status -eq "ok") { $ready = $true; break }
        } catch { Start-Sleep -Milliseconds 100 }
    }
    if (-not $ready) { throw "Benchmark proxy did not become ready" }

    $client = [Net.Http.HttpClient]::new()
    $coldSamples = @()
    foreach ($iteration in 1..$ColdIterations) {
        Remove-BenchmarkOutput $storage
        $coldSamples += Measure-Pair $client
    }
    $warmSamples = @()
    foreach ($iteration in 1..$WarmIterations) {
        $warmSamples += Measure-Pair $client
    }

    $cold = Get-Stats ([double[]]$coldSamples)
    $warm = Get-Stats ([double[]]$warmSamples)
    $speedup = [Math]::Round($cold.medianMs / $warm.medianMs, 2)
    $result = [ordered]@{
        measuredAt = [DateTimeOffset]::Now.ToString("o")
        machine = $env:COMPUTERNAME
        os = [Environment]::OSVersion.VersionString
        processorCount = [Environment]::ProcessorCount
        scenario = "Local index + meshdep 2.0.0 artifact HTTP round trip"
        cold = $cold
        warm = $warm
        medianSpeedup = $speedup
    }
    $result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $jsonPath -Encoding UTF8

    $report = @"
# CjRepo Proxy Benchmark

> 实测时间：$($result.measuredAt)  
> 主机：$($result.machine)；$($result.os)；$($result.processorCount) logical processors  
> 场景：本地 HTTP 请求一个包索引及 `meshdep 2.0.0` 制品。Cold 每轮清空服务端缓存；Warm 使用已校验缓存。

| 场景 | 轮次 | Median | P95 | Average | Min | Max |
|---|---:|---:|---:|---:|---:|---:|
| Cold / Cache MISS | $($cold.iterations) | $($cold.medianMs) ms | $($cold.p95Ms) ms | $($cold.averageMs) ms | $($cold.minMs) ms | $($cold.maxMs) ms |
| Warm / Cache HIT | $($warm.iterations) | $($warm.medianMs) ms | $($warm.p95Ms) ms | $($warm.averageMs) ms | $($warm.minMs) ms | $($warm.maxMs) ms |

Median speedup: **${speedup}x**

该结果衡量本机、无公网抖动条件下 CjRepo Proxy 自身的缓存路径差异，不代表官方中心仓的互联网延迟。原始样本保存在 proxy-benchmark.json，任何性能数字都可由 benchmark/proxy/run.ps1 重跑复验。
"@
    $report | Set-Content -LiteralPath $markdownPath -Encoding UTF8
    Write-Host "Cold median: $($cold.medianMs) ms; P95: $($cold.p95Ms) ms"
    Write-Host "Warm median: $($warm.medianMs) ms; P95: $($warm.p95Ms) ms"
    Write-Host "Median speedup: ${speedup}x"
    Write-Host "Report: $markdownPath"
} finally {
    if ($null -ne $client) { $client.Dispose() }
    if ($null -ne $upstreamProcess) { Stop-Process -Id $upstreamProcess.Id -Force -ErrorAction SilentlyContinue }
    if ($null -ne $proxyProcess) { Stop-Process -Id $proxyProcess.Id -Force -ErrorAction SilentlyContinue }
    $env:CJREPO_PORT = $oldPort
    $env:CJREPO_STORAGE = $oldStorage
    $env:CJREPO_UPSTREAM = $oldUpstream
    $env:CJREPO_PROXY_TTL_SECONDS = $oldTtl
}
