; Inno Setup: установщик PTO_Setup.exe (jrsoftware.org/isinfo.php). Данные программы хранятся в %USERPROFILE%\.smetagaz и при обновлении не затрагиваются.
[Setup]
AppName=ПТО
AppVersion=4.9.0
DefaultDirName={autopf}\ПТО
DefaultGroupName=ПТО
OutputDir=..\dist
OutputBaseFilename=PTO_Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
#ifexist "..\smetagaz\assets\icon.ico"
SetupIconFile=..\smetagaz\assets\icon.ico
#endif
[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
[Files]
Source: "..\dist\ПТО\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
#ifexist "..\dist\ПТО\PTO_Server.exe"
Source: "server_autostart\*"; DestDir: "{app}\server_autostart"; Flags: ignoreversion
#endif
[Icons]
Name: "{group}\ПТО"; Filename: "{app}\PTO.exe"
Name: "{autodesktop}\ПТО"; Filename: "{app}\PTO.exe"
#ifexist "..\dist\ПТО\PTO_Server.exe"
Name: "{group}\ПТО Сервер"; Filename: "{app}\PTO_Server.exe"
Name: "{group}\ПТО Сервер — настроить автозапуск"; Filename: "{app}\server_autostart\Настроить_автозапуск_сервера.bat"
#endif
[Run]
Filename: "{app}\PTO.exe"; Description: "Запустить ПТО"; Flags: postinstall nowait
