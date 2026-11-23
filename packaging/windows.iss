; Compile with tools/build_windows.py so the package paths and versions match.
#ifndef AppVersion
  #error AppVersion must be supplied with /DAppVersion
#endif
#ifndef NumericVersion
  #error NumericVersion must be supplied with /DNumericVersion
#endif
#ifndef PackageDir
  #error PackageDir must be supplied with /DPackageDir
#endif
#ifndef OutputDir
  #error OutputDir must be supplied with /DOutputDir
#endif
#define ProjectRoot AddBackslash(SourcePath) + ".."

[Setup]
; "{{" escapes a literal "{". Keep this AppId unchanged across releases.
AppId={{449A7BDC-D374-4AAB-8D31-D699214AC088}
AppName=Wisc
AppVersion={#AppVersion}
AppPublisher=Wisc
AppPublisherURL=https://github.com/wisc-launcher/wisc
AppSupportURL=https://github.com/wisc-launcher/wisc/issues
AppUpdatesURL=https://github.com/wisc-launcher/wisc/releases
VersionInfoVersion={#NumericVersion}.0
VersionInfoCompany=Wisc
VersionInfoProductName=Wisc
DefaultDirName={autopf}\Wisc
DefaultGroupName=Wisc
UsePreviousGroup=no
DisableProgramGroupPage=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
UsePreviousPrivileges=yes
UsePreviousAppDir=yes
UsePreviousTasks=yes
DisableDirPage=auto
AlwaysShowDirOnReadyPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile={#ProjectRoot}\LICENSE
SetupIconFile={#ProjectRoot}\.assets\icons\wisc.ico
UninstallDisplayIcon={app}\Wisc.exe
OutputDir={#OutputDir}
OutputBaseFilename=Wisc-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "{#PackageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Wisc"; Filename: "{app}\Wisc.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Wisc"; Filename: "{app}\Wisc.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\Wisc.exe"; Description: "Launch Wisc"; Flags: nowait postinstall skipifsilent

[Code]
var
  OldBundleInventory: String;

procedure RemoveLegacyShortcut(const ShortcutPath: String);
var
  Shell, Shortcut: Variant;
begin
  if not FileExists(ShortcutPath) then
    Exit;
  try
    Shell := CreateOleObject('WScript.Shell');
    Shortcut := Shell.CreateShortcut(ShortcutPath);
    { Only remove a shortcut belonging to this same installation. }
    if CompareText(Shortcut.TargetPath, ExpandConstant('{app}\Gr8Launcher.exe')) = 0 then
      DeleteFile(ShortcutPath);
  except
    { An inaccessible or edited shortcut can be left in place safely. }
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExistingInventory: String;
begin
  Result := '';
  ExistingInventory := ExpandConstant('{app}\bundle-manifest.json');
  if FileExists(ExistingInventory) then
  begin
    OldBundleInventory := ExpandConstant('{tmp}\old-bundle-manifest.json');
    if not CopyFile(ExistingInventory, OldBundleInventory, False) then
      Result := 'Could not preserve the launcher bundle inventory. Close other launcher copies and try again.';
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  CleanupExitCode: Integer;
begin
  if (CurStep = ssPostInstall) and (OldBundleInventory <> '') then
  begin
    if not Exec(ExpandConstant('{app}\updater.exe'),
      '--cleanup-installed "' + OldBundleInventory + '" "' + ExpandConstant('{app}') + '"',
      ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, CleanupExitCode) then
      RaiseException('Could not finish cleaning up the previous launcher bundle. Run setup again to repair it.');
    if CleanupExitCode <> 0 then
      RaiseException('The launcher bundle needs repair. Run setup again before launching.');
  end;
  if CurStep = ssPostInstall then
  begin
    RemoveLegacyShortcut(ExpandConstant('{autodesktop}\Gr8 Launcher.lnk'));
    RemoveLegacyShortcut(ExpandConstant('{autoprograms}\Gr8 Projects\Gr8 Launcher.lnk'));
    RemoveDir(ExpandConstant('{autoprograms}\Gr8 Projects'));
  end;
end;
