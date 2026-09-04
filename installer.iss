; Infinity — Inno Setup 6
[Setup]
AppId={{8E4C2A91-6B17-4F3D-9C58-7A1B2C3D4E5F}
AppName=Infinity
AppVersion=2.3.5
AppPublisher=Infinity
DefaultDirName={autopf}\Infinity
DefaultGroupName=Infinity
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=Infinity-Setup-2.3.5
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\SandClaimer.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin

[Languages]
Name: "cn"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "nuitka-out\SandClaimer.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Infinity"; Filename: "{app}\SandClaimer.exe"
Name: "{group}\{cm:UninstallProgram,Infinity}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Infinity"; Filename: "{app}\SandClaimer.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\SandClaimer.exe"; Description: "{cm:LaunchProgram,Infinity}"; Flags: nowait postinstall skipifsilent
