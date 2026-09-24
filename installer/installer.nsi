; StreamScanner - NSIS Installer
; Builds StreamScanner-Setup.exe

!ifndef VERSION
  !define VERSION "1.0.0"
!endif
!ifndef EXE_PATH
  !define EXE_PATH "dist\StreamScanner.exe"
!endif
!ifndef OUT_PATH
  !define OUT_PATH "installer\StreamScanner-Setup.exe"
!endif
!ifndef ICON_PATH
  !define ICON_PATH "assets\icon.ico"
!endif

!include "MUI2.nsh"

; این اسکریپت از روت ریپو اجرا می‌شود:
;   makensis installer/installer.nsi

Name "StreamScanner"
OutFile "${OUT_PATH}"
InstallDir "$PROGRAMFILES64\StreamScanner"
InstallDirRegKey HKLM "Software\StreamScanner" "InstallDir"
RequestExecutionLevel admin

VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "StreamScanner"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "LegalCopyright" "thaarfknight-star"
VIAddVersionKey "FileDescription" "StreamScanner Setup"

!define MUI_ABORTWARNING
!define MUI_ICON "${ICON_PATH}"
!define MUI_UNICON "${ICON_PATH}"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_BITMAP "assets\header.bmp"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

Section "Main" SEC_MAIN
  SetOutPath "$INSTDIR"
  ; --- Upgrade from v1.0.0 (was named "MasterStream Scanner") ---
  ; Migrate the server list, then remove the old install location.
  IfFileExists "$PROGRAMFILES64\MasterStream Scanner\servers.json" 0 no_migrate
    CopyFiles /SILENT "$PROGRAMFILES64\MasterStream Scanner\servers.json" "$INSTDIR\"
  no_migrate:
  RMDir /r "$PROGRAMFILES64\MasterStream Scanner"
  Delete "$DESKTOP\MasterStream Scanner.lnk"
  Delete "$SMPROGRAMS\MasterStream Scanner\MasterStream Scanner.lnk"
  Delete "$SMPROGRAMS\MasterStream Scanner\Uninstall.lnk"
  RMDir "$SMPROGRAMS\MasterStream Scanner"
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MasterStream Scanner"
  DeleteRegKey HKLM "Software\MasterStream Scanner"
  File "${EXE_PATH}"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKLM "Software\StreamScanner" "InstallDir" "$INSTDIR"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\StreamScanner" \
                   "DisplayName" "StreamScanner"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\StreamScanner" \
                   "UninstallString" "$INSTDIR\Uninstall.exe"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\StreamScanner" \
                   "DisplayVersion" "${VERSION}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\StreamScanner" \
                   "Publisher" "thaarfknight-star"
SectionEnd

Section "Start Menu Shortcuts"
  CreateDirectory "$SMPROGRAMS\StreamScanner"
  CreateShortcut "$SMPROGRAMS\StreamScanner\StreamScanner.lnk" \
                 "$INSTDIR\StreamScanner.exe" "" "$INSTDIR\StreamScanner.exe" 0
  CreateShortcut "$SMPROGRAMS\StreamScanner\Uninstall.lnk" \
                 "$INSTDIR\Uninstall.exe"
SectionEnd

Section "Desktop Shortcut"
  CreateShortcut "$DESKTOP\StreamScanner.lnk" "$INSTDIR\StreamScanner.exe" \
                 "" "$INSTDIR\StreamScanner.exe" 0
SectionEnd

Section "Uninstall"
  Delete "$INSTDIR\StreamScanner.exe"
  Delete "$INSTDIR\Uninstall.exe"
  Delete "$SMPROGRAMS\StreamScanner\StreamScanner.lnk"
  Delete "$SMPROGRAMS\StreamScanner\Uninstall.lnk"
  Delete "$DESKTOP\StreamScanner.lnk"
  RMDir "$SMPROGRAMS\StreamScanner"
  RMDir "$INSTDIR"
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\StreamScanner"
  DeleteRegKey HKLM "Software\StreamScanner"
SectionEnd
