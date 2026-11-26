; Stream Clipper - classic Windows installer (Inno Setup 6). Built by .github/workflows/build-windows.yml.
; Per-user install (no admin), so the built-in updater can replace files later.
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
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=StreamClipper-Setup-v{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\Stream Clipper.exe
LicenseFile=..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

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

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\bin"
