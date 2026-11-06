# Launch the connected cockpit and panel. Reuse existing services without writes.
$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
Set-Location -LiteralPath $taskRoot
$taskLaunchMutex = [System.Threading.Mutex]::new($false, 'Local\AircraftDebuggerA320Launcher')
$taskOwnsMutex = $false

function Get-LocalJson([string]$taskUrl) {
    try { Invoke-RestMethod -Uri $taskUrl -TimeoutSec 2 -UseBasicParsing }
    catch { $null }
}

function Test-LocalListener([int]$taskPort) {
    $taskSocket = New-Object System.Net.Sockets.TcpClient
    try {
        $taskPending = $taskSocket.BeginConnect('127.0.0.1', $taskPort, $null, $null)
        if (-not $taskPending.AsyncWaitHandle.WaitOne(300)) { return $false }
        $taskSocket.EndConnect($taskPending)
        return $true
    } catch { return $false }
    finally { $taskSocket.Dispose() }
}

try {
    try { $taskOwnsMutex = $taskLaunchMutex.WaitOne(0) }
    catch [System.Threading.AbandonedMutexException] { $taskOwnsMutex = $true }
    if (-not $taskOwnsMutex) { exit 0 }
    $taskFlightGear = Join-Path $taskRoot 'work\flightgear\runtime\{app}\bin\fgfs.exe'
    $taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
    $taskConfig = Join-Path $taskRoot 'configs\flightgear-a320.fgfsrc'
    foreach ($taskRequired in @($taskFlightGear, $taskPython, $taskConfig)) {
        if (-not (Test-Path -LiteralPath $taskRequired -PathType Leaf)) {
            throw "Missing simulator component: $taskRequired. See README.md setup instructions."
        }
    }
    $env:FG_HOME = Join-Path $taskRoot 'work\flightgear\home'
    $env:TEMP = Join-Path $taskRoot 'work\flightgear\temp'
    $env:TMP = $env:TEMP
    $taskLogDir = Join-Path $taskRoot 'work\flightgear\launch-logs'
    foreach ($taskDirectory in @($env:FG_HOME, $env:TEMP, $taskLogDir)) {
        New-Item -ItemType Directory -Path $taskDirectory -Force | Out-Null
    }
    $taskRun = [guid]::NewGuid().ToString('N').Substring(0, 10)
    $taskAircraftUrl = 'http://127.0.0.1:8088/json/sim/aircraft?t=y&d=1'
    $taskAircraft = Get-LocalJson $taskAircraftUrl
    if ($null -ne $taskAircraft -and $taskAircraft.value -ne 'A320-200-CFM') {
        throw 'Port 8088 belongs to a different aircraft/service. No running flight was changed.'
    }
    if ($null -eq $taskAircraft) {
        $taskExisting = Get-Process -Name fgfs -ErrorAction SilentlyContinue |
            Where-Object { $_.Path -eq $taskFlightGear }
        if (-not $taskExisting) {
            if (Test-LocalListener 8088) { throw 'Port 8088 is busy. No duplicate cockpit was launched.' }
            # The cockpit is the visible interactive application requested by the user.
            $taskCockpitProcess = Start-Process -FilePath $taskFlightGear -ArgumentList "--config=`"$taskConfig`"" -WorkingDirectory $taskRoot -PassThru `
                -RedirectStandardOutput (Join-Path $taskLogDir "$taskRun-cockpit.out.log") `
                -RedirectStandardError (Join-Path $taskLogDir "$taskRun-cockpit.err.log")
        }
        $taskDeadline = [datetime]::UtcNow.AddSeconds(90)
        do {
            Start-Sleep -Milliseconds 750
            $taskAircraft = Get-LocalJson $taskAircraftUrl
            if ($taskCockpitProcess -and $taskCockpitProcess.HasExited) {
                throw "The cockpit exited during startup. Inspect $taskLogDir."
            }
        } while ($null -eq $taskAircraft -and [datetime]::UtcNow -lt $taskDeadline)
        if ($null -eq $taskAircraft -or $taskAircraft.value -ne 'A320-200-CFM') {
            throw "The A320 property connection did not become ready. Inspect $taskLogDir. No flight was reset."
        }
    }

    $taskPanelUrl = 'http://127.0.0.1:8765'
    $taskPanel = Get-LocalJson "$taskPanelUrl/api/state"
    if ($null -eq $taskPanel) {
        if (Test-LocalListener 8765) { throw 'Port 8765 is busy with an unrecognized service.' }
        $taskPanelProcess = Start-Process -FilePath $taskPython -ArgumentList '-u -B -m aircraft_debugger.sim_panel' -PassThru `
            -WorkingDirectory $taskRoot -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $taskLogDir "$taskRun-panel.out.log") `
            -RedirectStandardError (Join-Path $taskLogDir "$taskRun-panel.err.log")
        $taskDeadline = [datetime]::UtcNow.AddSeconds(15)
        do {
            Start-Sleep -Milliseconds 500
            $taskPanel = Get-LocalJson "$taskPanelUrl/api/state"
            if ($taskPanelProcess.HasExited) { throw "The systems panel exited. Inspect $taskLogDir." }
        } while ($null -eq $taskPanel -and [datetime]::UtcNow -lt $taskDeadline)
    }
    if ($null -eq $taskPanel -or $null -eq $taskPanel.diagnosis) {
        throw "The systems panel did not become ready. Inspect $taskLogDir."
    }
    Start-Process -FilePath $taskPanelUrl | Out-Null
} catch {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Aircraft Debugger launcher') | Out-Null
    exit 1
} finally {
    if ($taskOwnsMutex) { $taskLaunchMutex.ReleaseMutex() }
    $taskLaunchMutex.Dispose()
}
