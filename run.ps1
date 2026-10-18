param(
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
    & $python -m pip install -r requirements.txt
}

& $python -m uvicorn main:app --reload --host 127.0.0.1 --port $Port
