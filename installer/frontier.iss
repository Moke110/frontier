#ifndef AppVersion
  #define AppVersion "0.1.0-preview.1"
#endif
#ifndef NumericVersion
  #define NumericVersion "0.1.0.0"
#endif
#ifndef PackageDir
  #error PackageDir must name a built Frontier distribution
#endif
[Setup]
AppId={{FB7ABBA7-2DAB-43D9-8C17-7F164304E919}
AppName=Frontier
AppVersion={#AppVersion}
VersionInfoVersion={#NumericVersion}
DefaultDirName={localappdata}\Programs\Frontier
DefaultGroupName=Frontier
DisableDirPage=no
PrivilegesRequired=lowest
MinVersion=10.0
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
OutputDir=output
OutputBaseFilename=Frontier-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
AppMutex=Local\FrontierConsoleRunning
UninstallDisplayIcon={app}\runtime\python.exe
[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
[Files]
Source: "{#PackageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{userprograms}\Frontier"; Filename: "{app}\runtime\python.exe"; Parameters: "-X utf8 -m hostrun.cli --code ""{app}"" console"; WorkingDir: "{app}"
Name: "{userdesktop}\Frontier"; Filename: "{app}\runtime\python.exe"; Parameters: "-X utf8 -m hostrun.cli --code ""{app}"" console"; WorkingDir: "{app}"; Tasks: desktopicon
