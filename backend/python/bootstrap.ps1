param(
    [string]$PythonPath = "",
    [switch]$RunChecks
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPath = Join-Path $scriptDir ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"

function Invoke-Step {
    param(
        [string]$Label,
        [scriptblock]$Command
    )

    Write-Host $Label
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE."
    }
}

$pythonCommand = $null
$pythonArguments = @()

if ($PythonPath) {
    if (-not (Test-Path $PythonPath)) {
        throw "Python interpreter not found at '$PythonPath'."
    }
    $pythonCommand = $PythonPath
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCommand = (Get-Command py).Source
    $pythonArguments = @("-3.12")
} elseif (Get-Command python3.12 -ErrorAction SilentlyContinue) {
    $pythonCommand = (Get-Command python3.12).Source
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCommand = (Get-Command python).Source
} else {
    throw "Python 3.12 was not found. Install it or pass -PythonPath."
}

$pythonVersion = & $pythonCommand @pythonArguments -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0 -or $pythonVersion.Trim() -ne "3.12") {
    throw "Expected Python 3.12, but '$pythonCommand' reported '$pythonVersion'."
}

if (Test-Path $venvPath) {
    Write-Host "Removing existing virtual environment at $venvPath"
    Remove-Item $venvPath -Recurse -Force
}

Invoke-Step "Creating virtual environment at $venvPath" {
    & $pythonCommand @pythonArguments -m venv $venvPath
}

Invoke-Step "Upgrading pip" {
    & $venvPython -m pip install --upgrade pip
}

Invoke-Step "Installing backend dependencies" {
    & $venvPython -m pip install -e "$scriptDir[dev]"
}

if ($RunChecks) {
    Invoke-Step "Running backend quality checks" {
        & $venvPython (Join-Path $scriptDir "scripts\check.py")
    }
}

Write-Host ""
Write-Host "Bootstrap completed."
Write-Host "Activate with:"
Write-Host "  $venvPath\Scripts\Activate.ps1"
