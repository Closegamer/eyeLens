; Inno Setup script for the eyeLens desktop app.
; Build with scripts/build_installer.ps1 so AppVersion is filled in.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{F1AAE574-6377-46F7-B91E-30CADA1EC1E9}
AppName=eyeLens
AppVersion={#AppVersion}
AppPublisher=eyeLens contributors
AppPublisherURL=https://github.com/Closegamer/eyeLens
AppSupportURL=https://github.com/Closegamer/eyeLens/issues
AppUpdatesURL=https://github.com/Closegamer/eyeLens/releases
DefaultDirName={autopf}\eyeLens
DefaultGroupName=eyeLens
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=eyeLens-{#AppVersion}-setup
SetupIconFile=..\docs\icon.ico
UninstallDisplayIcon={app}\eyeLens.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
Source: "..\dist\eyeLens\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\eyeLens"; Filename: "{app}\eyeLens.exe"
Name: "{autodesktop}\eyeLens"; Filename: "{app}\eyeLens.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\eyeLens"; ValueType: string; ValueName: "InstallDir"; ValueData: "{app}"; Flags: uninsdeletekey

[Run]
Filename: "{app}\eyeLens.exe"; Description: "{cm:LaunchProgram,eyeLens}"; Flags: nowait postinstall skipifsilent
