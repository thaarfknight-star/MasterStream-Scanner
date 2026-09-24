; MasterStream Scanner - NSIS Installer
; Builds MasterStreamScanner-Setup.exe

!ifndef VERSION
  !define VERSION "1.0.0"
!endif

!include "MUI2.nsh"

; این اسکریپت از روت ریپو اجرا می‌شود:
;   makensis installer/installer.nsi

Name "MasterStream Scanner"
OutFile "installer\MasterStreamScanner-Setup.exe"
InstallDir "$PROGRAMFILES64\MasterStream Scanner"
InstallDirRegKey HKLM "Software\MasterStream Scanner" "InstallDir"
RequestExecutionLevel admin

VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "MasterStream Scanner"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "LegalCopyright" "thaarfknight-star"
VIAddVersionKey "FileDescription" "MasterStream Scanner Setup"

!define MUI_ABORTWARNING
!define MUI_ICON "${NSISDIR}\Contrib\Graphics\Icons\modern-install.ico"
!define MUI_UNICON "${NSISDIR}\Contrib\Graphics\Icons\modern-uninstall.ico"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

Section "Main" SEC_MAIN
  SetOutPath "$INSTDIR"
  File "dist\MasterStreamScanner.exe"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKLM "Software\MasterStream Scanner" "InstallDir" "$INSTDIR"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MasterStream Scanner" \
                   "DisplayName" "MasterStream Scanner"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MasterStream Scanner" \
                   "UninstallString" "$INSTDIR\Uninstall.exe"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MasterStream Scanner" \
                   "DisplayVersion" "${VERSION}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MasterStream Scanner" \
                   "Publisher" "thaarfknight-star"
SectionEnd

Section "Start Menu Shortcuts"
  CreateDirectory "$SMPROGRAMS\MasterStream Scanner"
  CreateShortcut "$SMPROGRAMS\MasterStream Scanner\MasterStream Scanner.lnk" \
                 "$INSTDIR\MasterStreamScanner.exe"
  CreateShortcut "$SMPROGRAMS\MasterStream Scanner\Uninstall.lnk" \
                 "$INSTDIR\Uninstall.exe"
SectionEnd

Section "Desktop Shortcut"
  CreateShortcut "$DESKTOP\MasterStream Scanner.lnk" "$INSTDIR\MasterStreamScanner.exe"
SectionEnd

Section "Uninstall"
  Delete "$INSTDIR\MasterStreamScanner.exe"
  Delete "$INSTDIR\Uninstall.exe"
  Delete "$SMPROGRAMS\MasterStream Scanner\MasterStream Scanner.lnk"
  Delete "$SMPROGRAMS\MasterStream Scanner\Uninstall.lnk"
  Delete "$DESKTOP\MasterStream Scanner.lnk"
  RMDir "$SMPROGRAMS\MasterStream Scanner"
  RMDir "$INSTDIR"
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MasterStream Scanner"
  DeleteRegKey HKLM "Software\MasterStream Scanner"
SectionEnd
