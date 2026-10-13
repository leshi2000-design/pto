; Inno Setup: установщик SmetaGaz_Setup.exe (jrsoftware.org/isinfo.php). Данные программы хранятся в %USERPROFILE%\.smetagaz и при обновлении не затрагиваются.
[Setup]
AppName=СМЕТА-ГАЗ
AppVersion=3.4.1
DefaultDirName={autopf}\СМЕТА-ГАЗ
DefaultGroupName=СМЕТА-ГАЗ
OutputDir=..\dist
OutputBaseFilename=SmetaGaz_Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
[Files]
Source: "..\dist\СМЕТА-ГАЗ\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
[Icons]
Name: "{group}\СМЕТА-ГАЗ"; Filename: "{app}\SmetaGaz.exe"
Name: "{autodesktop}\СМЕТА-ГАЗ"; Filename: "{app}\SmetaGaz.exe"
[Run]
Filename: "{app}\SmetaGaz.exe"; Description: "Запустить СМЕТА-ГАЗ"; Flags: postinstall nowait
