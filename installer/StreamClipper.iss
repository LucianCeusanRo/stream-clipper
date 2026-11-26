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
function PsQ(S: String): String;
begin
  Result := S;
  StringChangeEx(Result, '''', '''''', True);
end;

procedure CreateElevatedTask();
var
  X, P: TArrayOfString;
  F, L, S1, Exe: String;
  Msg: AnsiString;
  R: Integer;
  Ok: Boolean;
begin
  F := ExpandConstant('{tmp}\sc-task.xml');
  L := ExpandConstant('{tmp}\sc-task.log');
  S1 := ExpandConstant('{tmp}\sc-task.ps1');
  Exe := ExpandConstant('{app}\Stream Clipper.exe');
  Ok := False;
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
    { through cmd so schtasks' own error text lands in the install log }
    if Exec(ExpandConstant('{cmd}'), '/c ""' + ExpandConstant('{sys}\schtasks.exe') + '" /create /tn "Stream Clipper" /xml "' + F + '" /f > "' + L + '" 2>&1"',
            '', SW_HIDE, ewWaitUntilTerminated, R) and (R = 0) then
      Ok := True
    else
    begin
      if LoadStringFromFile(L, Msg) then Log('schtasks /xml said: ' + String(Msg));
      Log('schtasks /create /xml failed (' + IntToStr(R) + '), trying Register-ScheduledTask');
    end;
    DeleteFile(F);
  end;
  if not Ok then
  begin
    { same settings via PowerShell: allowed on battery, no 3-day limit, highest privileges, only while signed in }
    SetArrayLength(P, 6);
    P[5] := 'exit 0';
    P[0] := '$ErrorActionPreference = ''Stop''';
    P[1] := '$a = New-ScheduledTaskAction -Execute ''' + PsQ(Exe) + ''' -Argument ''--elevated'' -WorkingDirectory ''' + PsQ(ExpandConstant('{app}')) + '''';
    P[2] := '$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances Parallel';
    P[3] := '$p = New-ScheduledTaskPrincipal -UserId ''' + PsQ(GetUserNameString) + ''' -LogonType Interactive -RunLevel Highest';
    P[4] := 'Register-ScheduledTask -TaskName ''Stream Clipper'' -Action $a -Settings $s -Principal $p -Force | Out-Null';
    if SaveStringsToUTF8File(S1, P, False) then
    begin
      if Exec(ExpandConstant('{cmd}'), '/c "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + S1 + '" > "' + L + '" 2>&1"',
              '', SW_HIDE, ewWaitUntilTerminated, R) and (R = 0) then
        Ok := True
      else
      begin
        if LoadStringFromFile(L, Msg) then Log('Register-ScheduledTask said: ' + String(Msg));
        Log('elevated task not created (' + IntToStr(R) + '): the launcher falls back to a normal UAC prompt');
      end;
      DeleteFile(S1);
    end;
  end;
  DeleteFile(L);
  if Ok then Log('elevated scheduled task "Stream Clipper" created');
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
