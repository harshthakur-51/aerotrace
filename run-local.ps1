[CmdletBinding()]
param(
    [string]$Config,
    [switch]$NoOpen
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw 'Local Python environment is missing. Follow the setup instructions in README.md.'
}

# Keep reproducible caches and generated runs inside this checkout.
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:MPLCONFIGDIR = Join-Path $projectRoot 'work\matplotlib'
$null = New-Item -ItemType Directory -Path $env:MPLCONFIGDIR -Force
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$runSuffix = [guid]::NewGuid().ToString('N').Substring(0, 6)
$outputPath = Join-Path $projectRoot "results\local-$stamp-$runSuffix"
$simArguments = @('-B', '-m', 'aircraft_debugger', '--output', $outputPath, '--plot')
if ($Config) {
    $configPath = (Resolve-Path -LiteralPath $Config -ErrorAction Stop).ProviderPath
    $simArguments += @('--config', $configPath)
}

Write-Host 'Running the local hydraulic experiment: healthy, leak, and pressure-sensor bias.'
Write-Host 'Current pressure and actuator relationships are illustrative model assumptions.'
& $pythonPath @simArguments
if ($LASTEXITCODE -ne 0) {
    throw "Simulator exited with code $LASTEXITCODE."
}

$plotPath = Join-Path $outputPath 'comparison.png'
Write-Host "Saved results: $outputPath"
if (-not $NoOpen) {
    try {
        Invoke-Item -LiteralPath $plotPath -ErrorAction Stop
    }
    catch {
        Write-Warning "The run succeeded, but the graph could not be opened automatically: $plotPath"
    }
}
