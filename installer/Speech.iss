#define MyAppName "Speech"
#define MyAppExeName "Speech.exe"
#define MyAppPublisher "andresleecom"
#define MyAppURL "https://github.com/andresleecom/speech"
#define MyAppVersion GetEnv("APP_VERSION")
#if MyAppVersion == ""
#define MyAppVersion "0.1.1"
#endif
#define MySourceDir "..\dist\Speech"

[Setup]
AppId={{F09E5C26-79E7-45BC-9CE2-42B20895D7C1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist\installer
OutputBaseFilename=Speech-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
RestartApplications=no

[Files]
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Belt and braces behind the uninstall in [Code]. On a first install there is
; nothing to uninstall, and an uninstall can fail or be interrupted, but the new
; build must never inherit files from the old one either way. Without this,
; installs only ever overlaid: four speech-*.dist-info directories and two
; tqdm-*.dist-info directories had piled up across releases.
[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
{ The GUID below must stay identical to AppId in [Setup]; Inno derives the
  uninstall key from it. SetupSetting("AppId") cannot be used here because it
  returns the directive text verbatim, including the doubled brace that escapes
  the literal '{', which would build the wrong key. A test asserts the two
  match. }
const
  PreviousUninstallKey =
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\' +
    '{F09E5C26-79E7-45BC-9CE2-42B20895D7C1}_is1';

procedure ReadPreviousInstall(var Uninstaller: String; var Location: String);
var
  Value: String;
begin
  Uninstaller := '';
  Location := '';
  if RegQueryStringValue(HKCU, PreviousUninstallKey, 'UninstallString', Value) then
  begin
    Uninstaller := RemoveQuotes(Value);
    RegQueryStringValue(HKCU, PreviousUninstallKey, 'InstallLocation', Location);
  end
  else if RegQueryStringValue(HKLM, PreviousUninstallKey, 'UninstallString', Value) then
  begin
    Uninstaller := RemoveQuotes(Value);
    RegQueryStringValue(HKLM, PreviousUninstallKey, 'InstallLocation', Location);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Uninstaller, Location, PreviousExe: String;
  ResultCode, Waited: Integer;
begin
  // Always returns '': a non-empty result aborts setup, and aborting an update
  // is the worst outcome available. The updater has already closed Speech, so
  // the user would be left with nothing running. If the uninstall does not work
  // out, carry on and let [InstallDelete] clear the old files instead.
  Result := '';

  ReadPreviousInstall(Uninstaller, Location);
  if (Uninstaller = '') or (not FileExists(Uninstaller)) then
    exit;

  if not Exec(Uninstaller, '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '',
      SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    exit;

  if Location = '' then
    Location := ExpandConstant('{app}');
  PreviousExe := AddBackslash(Location) + '{#MyAppExeName}';

  // Inno's uninstaller relaunches itself from a temporary copy so that it can
  // delete its own executable, so the Exec above can return while removal is
  // still in progress. Wait for the old executable to actually disappear
  // instead of trusting that return, but never wait forever.
  Waited := 0;
  while FileExists(PreviousExe) and (Waited < 30000) do
  begin
    Sleep(250);
    Waited := Waited + 250;
  end;
end;
