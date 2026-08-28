$ErrorActionPreference = "Stop"
Set-Location -LiteralPath (Join-Path $PSScriptRoot "..")

$zipPath = Join-Path (Get-Location) "tk_closed_loop_upload.zip"
if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}

$excludeDirs = @(
    "\venv\",
    "\__pycache__\",
    "\data\",
    "\uploads\",
    "\outputs\",
    "\runtime\"
)

$excludeFiles = @(
    ".env",
    "config.json",
    "tk_closed_loop_upload.zip"
)

$files = Get-ChildItem -Recurse -File | Where-Object {
    $full = $_.FullName
    $name = $_.Name
    $relative = $full.Substring((Get-Location).Path.Length)
    -not ($excludeDirs | Where-Object { $relative.Contains($_) }) -and
    -not ($excludeFiles -contains $name) -and
    -not ($name.EndsWith(".pyc"))
}

Compress-Archive -Path $files.FullName -DestinationPath $zipPath
Get-Item -LiteralPath $zipPath | Select-Object FullName, Length
