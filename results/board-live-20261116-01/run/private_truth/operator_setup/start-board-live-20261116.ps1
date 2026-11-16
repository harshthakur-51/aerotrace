param([string]$Name = 'board-live-20261116-01')

# Launch the pinned FlightGear A320 and fly it to the declared condition. No fault is set here.
$ErrorActionPreference = 'Stop'
$taskCode = (Get-Location).Path
$taskSim = 'Z:\aircraft-debugger'
$taskTrial = Join-Path $taskCode "work\$Name"
$taskReference = Join-Path $taskSim 'results\pressure-pair-20261106-01\private_truth\operator_setup'
$taskSettingsPath = 'results/pressure-v2-protocol-20261106-01/qualification-B.json'
$taskSettings = Get-Content -LiteralPath $taskSettingsPath -Raw | ConvertFrom-Json
if (Test-Path -LiteralPath $taskTrial) { throw 'Experiment folder already exists' }
if (Get-Process fgfs -ErrorAction SilentlyContinue) { throw 'Existing FlightGear process requires inspection' }
if (Get-NetTCPConnection -State Listen -LocalPort 8088 -ErrorAction SilentlyContinue) { throw 'Native property port already occupied' }
New-Item -ItemType Directory -Path $taskTrial | Out-Null
Copy-Item -LiteralPath (Join-Path $taskReference 'wait_for_startup.py') -Destination $taskTrial
$taskAltitude = $taskSettings.altitude_target_ft
$taskSpeed = $taskSettings.airspeed_target_kt
$taskAscii = New-Object Text.ASCIIEncoding
$taskPrepare = [IO.File]::ReadAllText((Join-Path $taskReference 'prepare_flight.py'))
[IO.File]::WriteAllText((Join-Path $taskTrial 'prepare_flight.py'),
    $taskPrepare.Replace('fmgc.Input.alt.setValue(10000)',"fmgc.Input.alt.setValue($taskAltitude)").Replace('fmgc.Input.kts.setValue(250)',"fmgc.Input.kts.setValue($taskSpeed)").Replace('target10000ft/250kt',"target ${taskAltitude}ft/${taskSpeed}kt"), $taskAscii)
$taskWatch = [IO.File]::ReadAllText((Join-Path $taskReference 'wait_for_condition.py'))
[IO.File]::WriteAllText((Join-Path $taskTrial 'wait_for_condition.py'),
    $taskWatch.Replace('configs/airborne-qualification-settings.json',$taskSettingsPath), $taskAscii)

$env:FG_HOME = Join-Path $taskSim 'work\flightgear\home'
$env:TEMP = Join-Path $taskSim 'work\flightgear\temp'
$env:TMP = $env:TEMP
$env:PYTHONPATH = $taskCode
$taskConfig = '--config=Z:/aircraft-debugger/configs/flightgear-a320.fgfsrc'
$taskCockpit = Start-Process -FilePath (Join-Path $taskSim 'work\flightgear\runtime\{app}\bin\fgfs.exe') -ArgumentList $taskConfig -WorkingDirectory $taskSim -PassThru -RedirectStandardOutput (Join-Path $taskTrial 'cockpit.out.log') -RedirectStandardError (Join-Path $taskTrial 'cockpit.err.log')
@{process_id=$taskCockpit.Id; config=$taskConfig; git_head=(git rev-parse HEAD); launched_utc=[DateTime]::UtcNow.ToString('o'); qualification=$taskSettingsPath; flight_group=$Name} |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskTrial 'launch.json') -Encoding ascii
$taskOwnedListener = $false
for ($taskAttempt = 0; $taskAttempt -lt 90; $taskAttempt++) {
    if ($taskCockpit.HasExited) { throw 'FlightGear exited before property connection' }
    $taskListener = Get-NetTCPConnection -State Listen -LocalPort 8088 -ErrorAction SilentlyContinue
    if ($taskListener) {
        if ($taskListener.OwningProcess -ne $taskCockpit.Id) { throw 'Property connection belongs to another process' }
        $taskOwnedListener = $true
        break
    }
    Start-Sleep -Seconds 1
}
if (-not $taskOwnedListener) { throw 'Owned property connection did not become available' }
python -B -u (Join-Path $taskTrial 'wait_for_startup.py') > (Join-Path $taskTrial 'startup.log')
if ($LASTEXITCODE -ne 0) { throw 'Ground readiness failed' }
python -B -u (Join-Path $taskTrial 'prepare_flight.py') > (Join-Path $taskTrial 'setup.log')
if ($LASTEXITCODE -ne 0) { throw 'Native setup failed' }
python -B -u (Join-Path $taskTrial 'wait_for_condition.py') > (Join-Path $taskTrial 'settling.log')
if ($LASTEXITCODE -ne 0) { throw 'Airborne settling failed' }
Get-Content -LiteralPath (Join-Path $taskTrial 'settling.log') -Tail 1
