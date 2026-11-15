; Per-user installer for VencordAutoRepair 0.4.0.
; The build script supplies ProjectDir, AppDir, OutputDir, OutputBaseFilename,
; and AppVersion so this file remains usable from local builds and CI.

#ifndef AppVersion
  #define AppVersion "0.4.0"
#endif
#ifndef ProjectDir
  #define ProjectDir ".."
#endif
#ifndef AppDir
  #define AppDir "..\dist\VencordAutoRepair"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif
#ifndef OutputBaseFilename
  #define OutputBaseFilename "VencordAutoRepairSetup"
#endif

#define MyAppName "VencordAutoRepair"
#define MyAppExeName "VencordAutoRepair.exe"
#define MyAppPublisher "Extrautior"
#define MyAppUrl "https://github.com/Extrautior/VencordAutoRepair"

[Setup]
AppId={{6F8B064C-4278-4E7F-9BC8-CA0E05C8A551}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppVerName={#MyAppName} {#AppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppUrl}
AppSupportURL={#MyAppUrl}/issues
AppUpdatesURL={#MyAppUrl}/releases
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseFilename}
SetupIconFile={#ProjectDir}\assets\VencordAutoRepair.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
LicenseFile={#ProjectDir}\LICENSE
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
UsePreviousAppDir=yes
UsePreviousTasks=yes
AllowNoIcons=yes
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
UninstallDisplayName={#MyAppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#AppDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Comment: "Open {#MyAppName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Code]
procedure RunStartupAction(const Parameters, ActionDescription: String);
var
  Executable: String;
  ResultCode: Integer;
begin
  Executable := ExpandConstant('{app}\{#MyAppExeName}');
  if not FileExists(Executable) then
  begin
    SuppressibleMsgBox('VencordAutoRepair could not ' + ActionDescription +
      ' because the application executable is missing. Setup has been stopped.',
      mbError, MB_OK, IDOK);
    Abort;
  end;

  if not Exec(Executable, Parameters, ExpandConstant('{app}'), SW_HIDE,
    ewWaitUntilTerminated, ResultCode) then
  begin
    SuppressibleMsgBox('VencordAutoRepair could not ' + ActionDescription +
      ' because the application could not be started. Setup has been stopped.',
      mbError, MB_OK, IDOK);
    Abort;
  end;

  if ResultCode <> 0 then
  begin
    Log('VencordAutoRepair startup action failed: ' + Parameters +
      ' (exit code ' + IntToStr(ResultCode) + ')');
    SuppressibleMsgBox('VencordAutoRepair could not ' + ActionDescription +
      ' (exit code ' + IntToStr(ResultCode) + '). Setup has been stopped so ' +
      'a startup entry is not left behind or reported incorrectly.',
      mbError, MB_OK, IDOK);
    Abort;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  LaunchResultCode: Integer;
begin
  if CurStep = ssPostInstall then
    RunStartupAction('--refresh-startup', 'refresh startup')
  else if (CurStep = ssDone) and not WizardSilent then
  begin
    if not Exec(ExpandConstant('{app}\{#MyAppExeName}'), '',
      ExpandConstant('{app}'), SW_SHOWNORMAL, ewNoWait, LaunchResultCode) then
      Log('VencordAutoRepair could not be opened after Setup finished.');
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    RunStartupAction('--disable-startup', 'remove startup');
end;


