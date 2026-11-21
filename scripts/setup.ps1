$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    $created = $false
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($version in @('-3.12', '-3.13')) {
            & py $version -m venv .venv
            if ($LASTEXITCODE -eq 0) { $created = $true; break }
        }
    }
    if (-not $created -and (Get-Command python -ErrorAction SilentlyContinue)) {
        & python -m venv .venv
        $created = ($LASTEXITCODE -eq 0)
    }
    if (-not $created) { throw 'Install Python 3.12 (64-bit), then run setup again.' }
}
$pythonExe = Join-Path (Get-Location) '.venv\Scripts\python.exe'
& $pythonExe -c 'import sys; assert (3,12) <= sys.version_info[:2] <= (3,13), "Use Python 3.12 or 3.13 (64-bit)"'
if ($LASTEXITCODE -ne 0) { throw 'Unsupported Python version.' }
$pipArgs = @('install', '--timeout', '180', '--retries', '10', '--progress-bar', 'off', '-r', 'requirements.txt')
# pip 24 does not have resume-retries. Add it only when supported.
$pipHelp = (& $pythonExe -m pip --help 2>&1 | Out-String)
if ($pipHelp -match '--resume-retries') {
    $pipArgs += @('--resume-retries', '10')
}
$installed = $false
for ($attempt = 1; $attempt -le 3; $attempt++) {
    Write-Host "Installing dependencies: attempt $attempt of 3 (network timeout 180 seconds)."
    & $pythonExe -m pip @pipArgs
    if ($LASTEXITCODE -eq 0) {
        $installed = $true
        break
    }
    if ($attempt -lt 3) {
        Write-Host 'Download/install failed. Retrying with the existing pip cache...'
        Start-Sleep -Seconds 3
    }
}
if (-not $installed) {
    throw 'Dependency installation failed after 3 attempts. Check your network and run SETUP_WINDOWS.bat again. Keep .venv and the pip cache.'
}
& $pythonExe manage.py setup
if ($LASTEXITCODE -ne 0) { throw 'Data setup failed. See Kaggle manual download instructions in README.md.' }
