# Rebuilds eyeLens.exe with the app icon embedded. Needs the Windows .NET
# Framework C# compiler (present on stock Windows 10/11).
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path $csc)) {
    $csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe'
}
& $csc /nologo /target:winexe /optimize+ /out:"$root\eyeLens.exe" `
    "/win32icon:$root\docs\icon.ico" "$PSScriptRoot\launcher.cs"
