<#
.SYNOPSIS
Runs the JARVIS-v3 Integration Tests safely.

.DESCRIPTION
This script sets the JARVIS_CI environment variable to 1. 
This puts JARVIS into "Safe CI Mode", ensuring that dangerous shell
commands trigger an automatic denial instead of blocking on a UI popup.
It then executes the main integration test script.
#>

$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " JARVIS-v3 LOCAL CI: INTEGRATION TESTS " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Starting tests in Safe CI Mode..." -ForegroundColor Green

# Set safe mode flag
$env:JARVIS_CI = "1"

# Execute integration tests
try {
    # Using the project's venv python to execute
    if (Test-Path "venv\Scripts\python.exe") {
        & "venv\Scripts\python.exe" tests\agent_integration_test.py
    } elseif (Test-Path "venv311\Scripts\python.exe") {
        & "venv311\Scripts\python.exe" tests\agent_integration_test.py
    } else {
        Write-Host "Virtual environment not found! Run setup scripts first." -ForegroundColor Red
        exit 1
    }

    if ($LASTEXITCODE -eq 0) {
        Write-Host "INTEGRATION TESTS PASSED" -ForegroundColor Green
    } else {
        Write-Host "INTEGRATION TESTS FAILED with code $LASTEXITCODE" -ForegroundColor Red
    }
} finally {
    # Remove safe mode flag to not poison current shell
    Remove-Item Env:\JARVIS_CI -ErrorAction SilentlyContinue
}

exit $LASTEXITCODE
