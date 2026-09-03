; Sand ???????????Inno Setup 6?
[Setup]
AppName=Sand ?????
AppVersion=2.2.8
AppPublisher=SandClaimer
DefaultDirName={autopf}\SandClaimer
DefaultGroupName=Sand ?????
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=SandClaimer-Setup-2.2.8
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
Name: "{group}\Sand ?????"; Filename: "{app}\SandClaimer.exe"
Name: "{group}\{cm:UninstallProgram,Sand ?????}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Sand ?????"; Filename: "{app}\SandClaimer.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\SandClaimer.exe"; Description: "{cm:LaunchProgram,Sand ?????}"; Flags: nowait postinstall skipifsilent
