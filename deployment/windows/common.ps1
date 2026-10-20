# Shared identity checks for the local Windows deployment entry points.
function Test-CjRepoProcessIdentity($Process, $State, [string]$ExpectedExecutable) {
    try {
        if ([string]::IsNullOrEmpty([string]$State.processStartTimeUtc)) { return $false }
        # Bind this Process object to its OS handle before checking identity or killing it.
        $null = $Process.Handle
        $expected = [IO.Path]::GetFullPath($ExpectedExecutable)
        $recorded = [IO.Path]::GetFullPath([string]$State.executable)
        $actual = [IO.Path]::GetFullPath([string]$Process.Path)
        # PowerShell 7 can deserialize ISO timestamps as DateTime; casting those
        # to a display string loses subsecond precision. Compare UTC ticks instead.
        $recordedStart = if ($State.processStartTimeUtc -is [DateTime]) {
            $State.processStartTimeUtc.ToUniversalTime()
        } else {
            [DateTimeOffset]::Parse([string]$State.processStartTimeUtc,
                [Globalization.CultureInfo]::InvariantCulture).UtcDateTime
        }
        return $recorded.Equals($expected, [StringComparison]::OrdinalIgnoreCase) -and
            $actual.Equals($expected, [StringComparison]::OrdinalIgnoreCase) -and
            ($Process.StartTime.ToUniversalTime().Ticks -eq $recordedStart.Ticks)
    } catch {
        return $false
    }
}

function Get-CjRepoPortListener([int]$Port) {
    # Enumerating listeners also distinguishes an empty port from a failed OS query.
    Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object {
        $_.LocalPort -eq $Port -and $_.LocalAddress -in @("127.0.0.1", "0.0.0.0", "::", "::ffff:127.0.0.1")
    }
}
