# Run with Windows PowerShell: Invoke-Pester -Script <this file> -EnableExit
# Exercise the deployment script in an isolated layout; never start or stop a real service.
$startSource = Join-Path $PSScriptRoot "..\..\deployment\windows\start.ps1"

Describe "Windows deployment address isolation" {
    BeforeEach {
        $script:originalAddress = [Environment]::GetEnvironmentVariable("CJREPO_ADDRESS", "Process")
        $script:deploymentRoot = Join-Path $TestDrive "deployment\windows"
        $serverBin = Join-Path $TestDrive "server\target\release\bin"
        New-Item -ItemType Directory -Force -Path $script:deploymentRoot, $serverBin | Out-Null
        Copy-Item -LiteralPath $startSource -Destination (Join-Path $script:deploymentRoot "start.ps1")
        Copy-Item -LiteralPath (Join-Path (Split-Path $startSource) "common.ps1") -Destination $script:deploymentRoot
        Set-Content -LiteralPath (Join-Path $serverBin "main.exe") -Value "fixture only"
        $script:setupPath = Join-Path $TestDrive "envsetup.ps1"
        Set-Content -LiteralPath $script:setupPath -Value "# no SDK required for this test"
        $global:CjRepoStartEnvironmentTestState = @{ ChildAddress = $null; FailLaunch = $false; Launched = $false }
        Mock Start-Process {
            $global:CjRepoStartEnvironmentTestState.ChildAddress = $env:CJREPO_ADDRESS
            if ($global:CjRepoStartEnvironmentTestState.FailLaunch) { throw "simulated launch failure" }
            $global:CjRepoStartEnvironmentTestState.Launched = $true
            $fakeProcess = [pscustomobject]@{ Id = 2147483000; HasExited = $false; StartTime = [DateTime]::UtcNow }
            $fakeProcess | Add-Member -MemberType ScriptMethod -Name Refresh -Value {}
            return $fakeProcess
        }
        Mock Invoke-RestMethod { return @{ status = "ok"; service = "cjrepo" } }
        Mock Get-NetTCPConnection {
            if ($global:CjRepoStartEnvironmentTestState.Launched) {
                return [pscustomobject]@{ LocalPort = 8080; LocalAddress = "127.0.0.1"; OwningProcess = 2147483000 }
            }
        }
    }

    AfterEach {
        [Environment]::SetEnvironmentVariable("CJREPO_ADDRESS", $script:originalAddress, "Process")
        Remove-Variable -Name CjRepoStartEnvironmentTestState -Scope Global -ErrorAction SilentlyContinue
    }

    It "overrides an inherited public bind and restores the caller environment" {
        $env:CJREPO_ADDRESS = "0.0.0.0"
        & (Join-Path $script:deploymentRoot "start.ps1") -NoBuild -EnvSetup $script:setupPath
        $global:CjRepoStartEnvironmentTestState.ChildAddress | Should Be "127.0.0.1"
        $env:CJREPO_ADDRESS | Should Be "0.0.0.0"
    }

    It "does not leave an address variable behind when the caller had none" {
        Remove-Item Env:CJREPO_ADDRESS -ErrorAction SilentlyContinue
        & (Join-Path $script:deploymentRoot "start.ps1") -NoBuild -EnvSetup $script:setupPath
        $global:CjRepoStartEnvironmentTestState.ChildAddress | Should Be "127.0.0.1"
        (Test-Path Env:CJREPO_ADDRESS) | Should Be $false
    }

    It "restores the caller environment if process creation fails" {
        $env:CJREPO_ADDRESS = "0.0.0.0"
        $global:CjRepoStartEnvironmentTestState.FailLaunch = $true
        { & (Join-Path $script:deploymentRoot "start.ps1") -NoBuild -EnvSetup $script:setupPath } |
            Should Throw "simulated launch failure"
        $global:CjRepoStartEnvironmentTestState.ChildAddress | Should Be "127.0.0.1"
        $env:CJREPO_ADDRESS | Should Be "0.0.0.0"
    }
}
