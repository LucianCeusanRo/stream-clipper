; Stream Clipper - classic Windows installer (Inno Setup 6). Built by .github/workflows/build-windows.yml.
; Runs as administrator (v1.3.2): some PCs block parts of the setup without it (long pip paths need
; LongPathsEnabled, locked-down folders, antivirus prompts). Files still go to the user's own folder, so the
; built-in updater can replace them, and a scheduled task "Stream Clipper" (highest privileges) lets the
; shortcuts start the app elevated WITHOUT a UAC prompt each time (no popup over a game).
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
[Setup]
AppId={{EDC34330-4CD9-4825-A07E-56579E7C4F40}
AppName=Stream Clipper
AppVersion={#AppVersion}
AppPublisher=Lucian Ceusan
AppPublisherURL=https://github.com/LucianCeusanRo/stream-clipper
DefaultDirName={localappdata}\Programs\Stream Clipper
DefaultGroupName=Stream Clipper
DisableProgramGroupPage=yes
PrivilegesRequired=admin
UsedUserAreasWarning=no
CloseApplications=yes
OutputDir=..\dist
OutputBaseFilename=StreamClipper-Setup-v{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\Stream Clipper.exe
LicenseFile=..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Registry]
; pip installs (.venv\Lib\site-packages\...) can exceed the old 260-character path limit -> "No such file" errors
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\FileSystem"; ValueType: dword; ValueName: "LongPathsEnabled"; ValueData: 1

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "model"; Description: "Download the speech model now (~500 MB, otherwise on first use)"; GroupDescription: "Setup:"
Name: "browser"; Description: "Install the browser used for TikTok posting"; GroupDescription: "Setup:"

[Files]
Source: "..\stage\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
Name: "{app}\data"; Flags: uninsneveruninstall

[Icons]
Name: "{group}\Stream Clipper"; Filename: "{app}\Stream Clipper.exe"; WorkingDir: "{app}"
Name: "{group}\Uninstall Stream Clipper"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Stream Clipper"; Filename: "{app}\Stream Clipper.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\setup.bat"; Parameters: "step python"; WorkingDir: "{app}"; StatusMsg: "Installing Python (portable)..."; Flags: runhidden waituntilterminated
Filename: "{app}\setup.bat"; Parameters: "step ffmpeg"; WorkingDir: "{app}"; StatusMsg: "Installing ffmpeg..."; Flags: runhidden waituntilterminated
Filename: "{app}\setup.bat"; Parameters: "step deno"; WorkingDir: "{app}"; StatusMsg: "Installing deno (for yt-dlp)..."; Flags: runhidden waituntilterminated
Filename: "{app}\setup.bat"; Parameters: "step venv"; WorkingDir: "{app}"; StatusMsg: "Creating the Python environment..."; Flags: runhidden waituntilterminated
Filename: "{app}\setup.bat"; Parameters: "step packages"; WorkingDir: "{app}"; StatusMsg: "Installing packages (a few minutes)..."; Flags: runhidden waituntilterminated
Filename: "{app}\setup.bat"; Parameters: "step browser"; WorkingDir: "{app}"; StatusMsg: "Installing the posting browser..."; Flags: runhidden waituntilterminated; Tasks: browser
Filename: "{app}\setup.bat"; Parameters: "step model"; WorkingDir: "{app}"; StatusMsg: "Downloading the speech model..."; Flags: runhidden waituntilterminated; Tasks: model
Filename: "{app}\Stream Clipper.exe"; Description: "Start Stream Clipper"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\schtasks.exe"; Parameters: "/delete /tn ""Stream Clipper"" /f"; Flags: runhidden; RunOnceId: "DelTask"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\bin"

[Code]
function XmlEsc(S: String): String;
begin
  Result := S;
  StringChangeEx(Result, '&', '&amp;', True);
  StringChangeEx(Result, '<', '&lt;', True);
  StringChangeEx(Result, '>', '&gt;', True);
end;

{ "Stream Clipper" task: highest privileges, started on demand by the launcher (schtasks /run) -> elevated
  without a UAC prompt. No trigger: autostart still uses HKCU\...\Run -> launcher -> this task. }
procedure CreateElevatedTask();
var
  X: TArrayOfString;
  F, Exe: String;
  R: Integer;
begin
  F := ExpandConstant('{tmp}\sc-task.xml');
  Exe := ExpandConstant('{app}\Stream Clipper.exe');
  SetArrayLength(X, 1);
  X[0] := '<?xml version="1.0" encoding="UTF-8"?>' +
    '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">' +
    '<RegistrationInfo><Description>Starts Stream Clipper with administrator rights without a UAC prompt.</Description></RegistrationInfo>' +
    '<Principals><Principal id="Author"><UserId>' + XmlEsc(GetUserNameString) + '</UserId><LogonType>InteractiveToken</LogonType><RunLevel>HighestAvailable</RunLevel></Principal></Principals>' +
    '<Settings><MultipleInstancesPolicy>Parallel</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>' +
    '<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><AllowHardTerminate>false</AllowHardTerminate><StartWhenAvailable>false</StartWhenAvailable>' +
    '<AllowStartOnDemand>true</AllowStartOnDemand><Enabled>true</Enabled><Hidden>false</Hidden><ExecutionTimeLimit>PT0S</ExecutionTimeLimit><Priority>5</Priority></Settings>' +
    '<Actions Context="Author"><Exec><Command>' + XmlEsc(Exe) + '</Command><Arguments>--elevated</Arguments>' +
    '<WorkingDirectory>' + XmlEsc(ExpandConstant('{app}')) + '</WorkingDirectory></Exec></Actions></Task>';
  if SaveStringsToUTF8File(F, X, False) then
  begin
    if not Exec(ExpandConstant('{sys}\schtasks.exe'), '/create /tn "Stream Clipper" /xml "' + F + '" /f', '', SW_HIDE, ewWaitUntilTerminated, R) or (R <> 0) then
      Log('schtasks /create failed: ' + IntToStr(R) + ' (the launcher falls back to a normal UAC prompt)');
    DeleteFile(F);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    CreateElevatedTask();
    { an older per-user (v1.3.1 and earlier) install registered itself under HKCU: drop that duplicate "Apps" entry }
    RegDeleteKeyIncludingSubkeys(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{EDC34330-4CD9-4825-A07E-56579E7C4F40}_is1');
  end;
end;
