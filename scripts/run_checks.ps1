$ErrorActionPreference = "Stop"
Set-Location -LiteralPath (Join-Path $PSScriptRoot "..")

if (Test-Path -LiteralPath ".\venv\Scripts\python.exe") {
    $python = ".\venv\Scripts\python.exe"
} else {
    $python = "python"
}

& $python -m compileall app.py core collection downloading integrations media pipeline screening services scripts tests
& $python -m unittest discover -s tests
& $python scripts\check_setup.py --mode basic

