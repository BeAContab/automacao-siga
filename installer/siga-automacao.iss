#define MyAppName "SIGA Automacao"
#define MyAppVersion "1.1.0"
#define MyAppExeName "siga-automacao-gui.exe"

[Setup]
AppId={{8B0C2C2E-1A84-4B4B-9F46-2A6B8C5B3D71}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
DefaultDirName={localappdata}\Programs\SIGA Automacao
DefaultGroupName=SIGA Automacao
AllowNoIcons=yes
OutputDir=..\dist\installer
OutputBaseFilename=SIGA-Automacao-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{userdesktop}\SIGA Automacao"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userprograms}\SIGA Automacao\SIGA Automacao"; Filename: "{app}\{#MyAppExeName}"
Name: "{userprograms}\SIGA Automacao\Desinstalar SIGA Automacao"; Filename: "{uninstallexe}"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na area de trabalho"; GroupDescription: "Atalhos adicionais:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Executar SIGA Automacao"; Flags: nowait postinstall skipifsilent
