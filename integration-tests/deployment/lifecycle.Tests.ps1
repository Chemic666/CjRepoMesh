# Windows PowerShell / Pester 3.4. No real process is launched or stopped.
$deploymentSource = Join-Path $PSScriptRoot "..\..\deployment\windows"

Describe "Windows deployment lifecycle" {
    BeforeEach {
        $fixtureRoot = Join-Path $TestDrive ([Guid]::NewGuid().ToString("N"))
        $script:deploymentRoot = Join-Path $fixtureRoot "deployment\windows"
        $script:serverExe = Join-Path $fixtureRoot "server\target\release\bin\main.exe"
        $script:statePath = Join-Path $script:deploymentRoot "run\cjrepo.json"
        New-Item -ItemType Directory -Force -Path (Split-Path $script:serverExe),
            (Split-Path $script:statePath) | Out-Null
        Get-ChildItem -LiteralPath $deploymentSource -Filter *.ps1 | ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $script:deploymentRoot
        }
        Set-Content -LiteralPath $script:serverExe -Value "fixture only"
        $script:setupPath = Join-Path $fixtureRoot "envsetup.ps1"
        Set-Content -LiteralPath $script:setupPath -Value "# isolated test"
        $script:storage = Join-Path $fixtureRoot "data"
        New-Item -ItemType Directory -Force -Path $script:storage | Out-Null
        # Keep the real Process type so Pester 3 can bind Stop-Process -InputObject.
        $fakeProcess = New-Object System.Diagnostics.Process
        # Remove PowerShell's type-data Path property before attaching fixture values.
        $fakeProcess.PSObject.TypeNames.Clear()
        $properties = @{
            Id = 2147483000; Path = $script:serverExe; HasExited = $false; Handle = 1
            StartTime = [DateTime]::Parse("2026-10-20T02:00:00Z").ToUniversalTime()
        }
        foreach ($name in $properties.Keys) {
            $fakeProcess | Add-Member NoteProperty $name $properties[$name] -Force
        }
        $fakeProcess | Add-Member ScriptMethod Refresh {} -Force
        $fakeProcess | Add-Member ScriptMethod WaitForExit { param($timeout) return $true } -Force
        $global:CjRepoLifecycleTest = @{
            Process = $fakeProcess; Launched = $false; Occupied = $false
            WrongOwner = $false; Stopped = $false; NoExit = $false
        }
        Mock Start-Process {
            $global:CjRepoLifecycleTest.Launched = $true
            return $global:CjRepoLifecycleTest.Process
        }
        Mock Get-Process { return $global:CjRepoLifecycleTest.Process }
        Mock Stop-Process { $global:CjRepoLifecycleTest.Stopped = $true }
        Mock Invoke-RestMethod { return @{ status = "ok"; service = "cjrepo" } }
        Mock Get-NetTCPConnection {
            if ($global:CjRepoLifecycleTest.Occupied -or $global:CjRepoLifecycleTest.WrongOwner) {
                return [pscustomobject]@{ LocalPort = 39610; LocalAddress = "127.0.0.1"; OwningProcess = 9999 }
            }
            if ($global:CjRepoLifecycleTest.Launched) {
                return [pscustomobject]@{
                    LocalPort = 39610; LocalAddress = "127.0.0.1"; OwningProcess = 2147483000
                }
            }
        }
        Mock Start-Sleep {}
    }

    AfterEach {
        Remove-Variable CjRepoLifecycleTest -Scope Global -ErrorAction SilentlyContinue
    }

    function Write-DeploymentState([string]$StartTime) {
        @{
            pid = 2147483000; executable = $script:serverExe; port = 39610
            storage = $script:storage; processStartTimeUtc = $StartTime
        } | ConvertTo-Json | Set-Content -LiteralPath $script:statePath -Encoding UTF8
    }

    It "rejects an occupied port before launching a process" {
        $global:CjRepoLifecycleTest.Occupied = $true
        { & (Join-Path $script:deploymentRoot "start.ps1") -Port 39610 -Storage $script:storage `
                -NoBuild -EnvSetup $script:setupPath } | Should Throw "already in use"
        $global:CjRepoLifecycleTest.Launched | Should Be $false
    }

    It "does not accept another process health response after the port preflight" {
        Mock Invoke-RestMethod {
            $global:CjRepoLifecycleTest.WrongOwner = $true
            return @{ status = "ok"; service = "cjrepo" }
        }
        { & (Join-Path $script:deploymentRoot "start.ps1") -Port 39610 -Storage $script:storage `
                -NoBuild -EnvSetup $script:setupPath } | Should Throw "another process"
        (Test-Path -LiteralPath $script:statePath) | Should Be $false
        $global:CjRepoLifecycleTest.Stopped | Should Be $true
    }

    It "records the actual process start time after a successful start" {
        & (Join-Path $script:deploymentRoot "start.ps1") -Port 39610 -Storage $script:storage `
            -NoBuild -EnvSetup $script:setupPath
        $state = Get-Content -LiteralPath $script:statePath -Raw | ConvertFrom-Json
        $state.processStartTimeUtc | Should Be ($global:CjRepoLifecycleTest.Process.StartTime.ToString("o"))
    }

    It "refuses to stop a reused PID even when the executable path matches" {
        Write-DeploymentState "2026-10-19T02:00:00.0000000Z"
        { & (Join-Path $script:deploymentRoot "stop.ps1") } | Should Throw "identity"
        $global:CjRepoLifecycleTest.Stopped | Should Be $false
        (Test-Path -LiteralPath $script:statePath) | Should Be $true
    }

    It "refuses to stop a legacy state without process identity" {
        Write-DeploymentState ""
        { & (Join-Path $script:deploymentRoot "stop.ps1") } | Should Throw "identity"
        $global:CjRepoLifecycleTest.Stopped | Should Be $false
    }

    It "stops a matching process and preserves its stored data" {
        Write-DeploymentState ($global:CjRepoLifecycleTest.Process.StartTime.ToString("o"))
        $marker = Join-Path $script:storage "keep.txt"
        Set-Content -LiteralPath $marker -Value "data"
        & (Join-Path $script:deploymentRoot "stop.ps1")
        $global:CjRepoLifecycleTest.Stopped | Should Be $true
        (Test-Path -LiteralPath $script:statePath) | Should Be $false
        (Get-Content -LiteralPath $marker) | Should Be "data"
    }

    It "preserves deployment state if stopping times out" {
        Write-DeploymentState ($global:CjRepoLifecycleTest.Process.StartTime.ToString("o"))
        $global:CjRepoLifecycleTest.Process | Add-Member ScriptMethod WaitForExit `
            { param($timeout) return $false } -Force
        { & (Join-Path $script:deploymentRoot "stop.ps1") } | Should Throw "did not exit"
        (Test-Path -LiteralPath $script:statePath) | Should Be $true
    }

    It "doctor rejects a reused PID before requesting health" {
        Write-DeploymentState "2026-10-19T02:00:00.0000000Z"
        & (Join-Path $script:deploymentRoot "doctor.ps1")
        $LASTEXITCODE | Should Be 1
        Assert-MockCalled Invoke-RestMethod -Times 0 -Exactly -Scope It
    }

    It "doctor rejects a health endpoint owned by another process" {
        Write-DeploymentState ($global:CjRepoLifecycleTest.Process.StartTime.ToString("o"))
        $global:CjRepoLifecycleTest.WrongOwner = $true
        & (Join-Path $script:deploymentRoot "doctor.ps1")
        $LASTEXITCODE | Should Be 1
    }

    It "does not overwrite an unverifiable live deployment state" {
        Write-DeploymentState "2026-10-19T02:00:00.0000000Z"
        $before = Get-Content -LiteralPath $script:statePath -Raw
        { & (Join-Path $script:deploymentRoot "start.ps1") -Port 39610 -Storage $script:storage `
                -NoBuild -EnvSetup $script:setupPath } | Should Throw "identity"
        (Get-Content -LiteralPath $script:statePath -Raw) | Should Be $before
        $global:CjRepoLifecycleTest.Launched | Should Be $false
    }

    It "replaces stale state only when its process no longer exists" {
        Write-DeploymentState "2026-10-19T02:00:00.0000000Z"
        Mock Get-Process { return $null }
        & (Join-Path $script:deploymentRoot "start.ps1") -Port 39610 -Storage $script:storage `
            -NoBuild -EnvSetup $script:setupPath
        $state = Get-Content -LiteralPath $script:statePath -Raw | ConvertFrom-Json
        $state.processStartTimeUtc | Should Be ($global:CjRepoLifecycleTest.Process.StartTime.ToString("o"))
    }

    It "fails closed if the OS listener query fails" {
        Mock Get-NetTCPConnection { throw "listener query unavailable" }
        { & (Join-Path $script:deploymentRoot "start.ps1") -Port 39610 -Storage $script:storage `
                -NoBuild -EnvSetup $script:setupPath } | Should Throw "listener query unavailable"
        $global:CjRepoLifecycleTest.Launched | Should Be $false
    }

    It "doctor accepts the recorded live process and its own listener" {
        Write-DeploymentState ($global:CjRepoLifecycleTest.Process.StartTime.ToString("o"))
        $global:CjRepoLifecycleTest.Launched = $true
        & (Join-Path $script:deploymentRoot "doctor.ps1")
        $LASTEXITCODE | Should Be 0
    }

    It "rejects unsafe upstream URLs before launching" -TestCases @(
        @{ Value = "https://user:fixture-secret@example.invalid" }
        @{ Value = "https://example.invalid?token=fixture-secret" }
        @{ Value = "https://example.invalid#fixture-secret" }
        @{ Value = "file:///C:/fixture" }
    ) {
        param($Value)
        { & (Join-Path $script:deploymentRoot "start.ps1") -Port 39610 -Storage $script:storage `
                -NoBuild -EnvSetup $script:setupPath -Upstream $Value } | Should Throw "Upstream must"
        $global:CjRepoLifecycleTest.Launched | Should Be $false
        (Test-Path -LiteralPath $script:statePath) | Should Be $false
    }
}

Describe "Deployment process timestamp comparison" {
    It "accepts a JSON timestamp already converted to DateTime without losing precision" {
        . (Join-Path $deploymentSource "common.ps1")
        $expected = Join-Path $TestDrive "main.exe"
        $time = [DateTime]::Parse("2026-10-20T02:00:00.1234567Z").ToUniversalTime()
        $process = [pscustomobject]@{ Path = $expected; StartTime = $time; Handle = 1 }
        $state = [pscustomobject]@{ executable = $expected; processStartTimeUtc = $time }
        (Test-CjRepoProcessIdentity $process $state $expected) | Should Be $true
    }

    It "rejects a one-tick difference in a typed timestamp" {
        . (Join-Path $deploymentSource "common.ps1")
        $expected = Join-Path $TestDrive "main.exe"
        $time = [DateTime]::Parse("2026-10-20T02:00:00.1234567Z").ToUniversalTime()
        $process = [pscustomobject]@{ Path = $expected; StartTime = $time; Handle = 1 }
        $state = [pscustomobject]@{ executable = $expected; processStartTimeUtc = $time.AddTicks(1) }
        (Test-CjRepoProcessIdentity $process $state $expected) | Should Be $false
    }
}
