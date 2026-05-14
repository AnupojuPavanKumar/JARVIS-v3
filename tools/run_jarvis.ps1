[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$JarvisArgs = @()
)

$ErrorActionPreference = "Stop"

$runner = Join-Path $PSScriptRoot "python_entrypoint.ps1"
$entrypoint = Join-Path (Split-Path $PSScriptRoot -Parent) "main.py"

& $runner -ScriptPath $entrypoint -ScriptArgs $JarvisArgs
exit $LASTEXITCODE
