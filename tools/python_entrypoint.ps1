[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ScriptPath,

    [string[]]$ScriptArgs = @(),

    [switch]$DescribeOnly
)

$ErrorActionPreference = "Stop"

function Read-PyVenvConfig {
    param([string]$ConfigPath)

    $values = @{}
    if (-not (Test-Path -LiteralPath $ConfigPath)) {
        return $values
    }

    foreach ($line in Get-Content -LiteralPath $ConfigPath) {
        if ($line -notmatch "=") {
            continue
        }

        $parts = $line -split "=", 2
        $values[$parts[0].Trim()] = $parts[1].Trim()
    }

    return $values
}

function Test-PythonCandidate {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $false
    }

    if (-not (Test-Path -LiteralPath $Path)) {
        return $false
    }

    try {
        $null = & $Path -c "import sys; print(sys.executable)" 2>$null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

function New-PythonCandidate {
    param(
        [string]$Source,
        [string]$Path,
        [hashtable]$Metadata
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $null
    }

    return [pscustomobject]@{
        Source   = $Source
        Path     = $Path
        Metadata = $Metadata
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$resolvedScriptPath = (Resolve-Path -LiteralPath $ScriptPath).Path

$candidateList = New-Object System.Collections.Generic.List[object]

foreach ($venvName in @("venv311", "venv")) {
    $venvDir = Join-Path $repoRoot $venvName
    $cfgPath = Join-Path $venvDir "pyvenv.cfg"
    $cfg = Read-PyVenvConfig -ConfigPath $cfgPath
    $launcherPath = Join-Path $venvDir "Scripts\python.exe"

    $candidate = New-PythonCandidate -Source "$venvName launcher" -Path $launcherPath -Metadata @{
        type = "launcher"
        venv = $venvName
        config = $cfgPath
    }
    if ($null -ne $candidate) {
        $candidateList.Add($candidate)
    }

    $baseExecutable = $cfg["executable"]
    $candidate = New-PythonCandidate -Source "$venvName base" -Path $baseExecutable -Metadata @{
        type = "base"
        venv = $venvName
        config = $cfgPath
    }
    if ($null -ne $candidate) {
        $candidateList.Add($candidate)
    }
}

$seen = @{}
$candidates = foreach ($candidate in $candidateList) {
    $key = $candidate.Path.ToLowerInvariant()
    if ($seen.ContainsKey($key)) {
        continue
    }
    $seen[$key] = $true
    $candidate
}

$probedCandidates = foreach ($candidate in $candidates) {
    [pscustomobject]@{
        Source   = $candidate.Source
        Path     = $candidate.Path
        Metadata = $candidate.Metadata
        Working  = (Test-PythonCandidate -Path $candidate.Path)
    }
}

if ($DescribeOnly) {
    $probedCandidates
    $global:LASTEXITCODE = 0
    return
}

$working = $probedCandidates | Where-Object { $_.Working } | Select-Object -First 1

if ($null -eq $working) {
    throw "No working Python interpreter was found for this repo. Check tools\jarvis_diagnostic.py for launcher details."
}

Write-Host "Using Python: $($working.Path)"
Write-Host "Source: $($working.Source)"

Push-Location $repoRoot
try {
    $previousBootstrapVenv = $env:JARVIS_BOOTSTRAP_VENV
    $previousPythonSource = $env:JARVIS_PYTHON_SOURCE

    if ($working.Metadata -and $working.Metadata.ContainsKey("venv")) {
        $env:JARVIS_BOOTSTRAP_VENV = [string]$working.Metadata["venv"]
    }
    else {
        Remove-Item Env:JARVIS_BOOTSTRAP_VENV -ErrorAction SilentlyContinue
    }

    $env:JARVIS_PYTHON_SOURCE = [string]$working.Source

    & $working.Path $resolvedScriptPath @ScriptArgs
    exit $LASTEXITCODE
}
finally {
    if ($null -ne $previousBootstrapVenv) {
        $env:JARVIS_BOOTSTRAP_VENV = $previousBootstrapVenv
    }
    else {
        Remove-Item Env:JARVIS_BOOTSTRAP_VENV -ErrorAction SilentlyContinue
    }

    if ($null -ne $previousPythonSource) {
        $env:JARVIS_PYTHON_SOURCE = $previousPythonSource
    }
    else {
        Remove-Item Env:JARVIS_PYTHON_SOURCE -ErrorAction SilentlyContinue
    }
    Pop-Location
}
