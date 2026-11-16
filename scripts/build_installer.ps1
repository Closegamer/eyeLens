# Builds dist\eyeLens\ (PyInstaller) and dist\eyeLens-<version>-setup.exe (Inno Setup).
# Pass -Iscc when Inno Setup is not in a standard location.
param(
    [string]$Iscc = $env:ISCC
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$version = (Select-String -Path (Join-Path $root 'pyproject.toml') `
        -Pattern '^version\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value

if (-not $Iscc) {
    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
    )
    $Iscc = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
}
if (-not $Iscc -or -not (Test-Path $Iscc)) {
    throw 'ISCC.exe not found. Install Inno Setup 6 or pass -Iscc <path>.'
}

$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }

Push-Location $root
try {
    & $python -m PyInstaller --noconfirm --clean --windowed --name eyeLens `
        --icon (Join-Path $root 'docs\icon.ico') `
        --add-data "$(Join-Path $root 'models\face_landmarker.task');models" `
        --paths $root --distpath (Join-Path $root 'dist') `
        --workpath (Join-Path $root 'build\pyinstaller') `
        --specpath (Join-Path $root 'build\pyinstaller') `
        --log-level WARN (Join-Path $root 'scripts\frozen_entry.py')
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }

    & $Iscc "/DAppVersion=$version" (Join-Path $root 'installer\eyeLens.iss')
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup failed.' }
} finally {
    Pop-Location
}

$setup = Join-Path $root "dist\eyeLens-$version-setup.exe"
if (-not (Test-Path $setup)) { throw "Installer was not created at $setup" }
Get-Item $setup | Select-Object FullName, Length
