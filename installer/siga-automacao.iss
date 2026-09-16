; Instalador do SIGA Automação (Inno Setup).
;
; Pré-requisito: gerar o build antes de compilar este script —
;   python web/build.py
;   pyinstaller siga-automacao.spec
; O PyInstaller produz um build "onedir" (pasta dist\siga-automacao\ com o .exe e a
; pasta _internal\ de dependências) — por isso o [Files] copia a pasta inteira, e não
; um único arquivo, diferente do antigo instalador anterior à migração para pywebview.
;
; Requisito de runtime no computador do usuário: Microsoft Edge WebView2 Runtime (já
; vem com o Windows 11 e o Windows 10 atualizado). Este instalador não verifica nem
; empacota o WebView2 — se for necessário no futuro, ver o Evergreen Bootstrapper da
; Microsoft.

#define MyAppName "SIGA Automacao"
#define MyAppVersion "2.11.2"
#define MyAppExeName "siga-automacao.exe"

[Setup]
AppId={{8B0C2C2E-1A84-4B4B-9F46-2A6B8C5B3D71}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
DefaultDirName={localappdata}\Programs\SIGA Automacao
DefaultGroupName=SIGA Automacao
AllowNoIcons=yes
SetupIconFile=..\images\icons\siga-automacao.ico
OutputDir=..\dist\installer
OutputBaseFilename=Setup {#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Files]
Source: "..\dist\siga-automacao\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\images\icons\siga-automacao.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
; Planilha-base COD/EMPRESA/CNPJ: copiada só na primeira instalação (onlyifdoesntexist)
; — numa atualização, o escritório já pode ter editado esse arquivo (cliente novo, CNPJ
; que mudou), e sobrescrever silenciosamente destruiria essa edição.
Source: "..\COD EMP CNPJ.xlsx"; DestDir: "{app}"; Flags: onlyifdoesntexist

[Icons]
Name: "{userdesktop}\SIGA Automacao"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\siga-automacao.ico"; IconIndex: 0
Name: "{userprograms}\SIGA Automacao\SIGA Automacao"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\siga-automacao.ico"; IconIndex: 0
Name: "{userprograms}\SIGA Automacao\Desinstalar SIGA Automacao"; Filename: "{uninstallexe}"; IconFilename: "{uninstallexe}"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na area de trabalho"; GroupDescription: "Atalhos adicionais:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Executar SIGA Automacao"; Flags: nowait postinstall skipifsilent
