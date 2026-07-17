param(
    [string]$PythonPath = "C:\Users\lacin\AppData\Local\Programs\Python\Python312\python.exe",
    [switch]$RunChecks
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPath = Join-Path $scriptDir ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"

if (-not (Test-Path $PythonPath)) {
    throw "Python interpreter not found at '$PythonPath'. Pass -PythonPath or install Python 3.12.x."
}

if (Test-Path $venvPath) {
    Write-Host "Removing existing virtual environment at $venvPath"
    Remove-Item $venvPath -Recurse -Force
}

Write-Host "Creating virtual environment at $venvPath"
& $PythonPath -m venv $venvPath

Write-Host "Upgrading pip"
& $venvPython -m pip install --upgrade pip

Write-Host "Installing backend dependencies"
& $venvPython -m pip install -e "$scriptDir[dev]"

if ($RunChecks) {
    Write-Host "Running tests"
    & $venvPython -m pytest

    Write-Host "Running lint"
    & $venvPython -m ruff check $scriptDir
}

Write-Host ""
Write-Host "Bootstrap completed."
Write-Host "Activate with:"
Write-Host "  $venvPath\Scripts\Activate.ps1"
