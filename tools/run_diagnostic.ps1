[CmdletBinding()]
param(
    [switch]$DescribePython
)

$ErrorActionPreference = "Stop"

$runner = Join-Path $PSScriptRoot "python_entrypoint.ps1"
$diagnostic = Join-Path $PSScriptRoot "jarvis_diagnostic.py"

if ($DescribePython) {
    & $runner -ScriptPath $diagnostic -DescribeOnly
    exit $LASTEXITCODE
}

& $runner -ScriptPath $diagnostic
exit $LASTEXITCODE
