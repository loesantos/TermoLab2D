; Instalador do TermoLab2D (NSIS 3). Gerado por build_windows.py, que define
; VERSION, STAGE (pasta montada), OUTDIR e SIZE_KB.
Target amd64-unicode   ; instalador 64 bits (o programa também é 64 bits)
SetCompressor /SOLID lzma
SetCompressorDictSize 64

!include "MUI2.nsh"

!define APPNAME "TermoLab2D"
!define PUBLISHER "TermoLab2D"
!define UNINSTKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}"

Name "${APPNAME} ${VERSION}"
OutFile "${OUTDIR}\${APPNAME}-${VERSION}-instalador.exe"
InstallDir "$LOCALAPPDATA\Programs\${APPNAME}"
InstallDirRegKey HKCU "Software\${APPNAME}" "InstallDir"
RequestExecutionLevel user
BrandingText "${APPNAME} — termodinâmica partícula a partícula"

VIProductVersion "${VIVERSION}"
VIAddVersionKey /LANG=1046 "ProductName" "${APPNAME}"
VIAddVersionKey /LANG=1046 "FileDescription" "Instalador do ${APPNAME}"
VIAddVersionKey /LANG=1046 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=1046 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=1046 "LegalCopyright" "${APPNAME}"

!define MUI_ICON "${STAGE}\icone.ico"
!define MUI_UNICON "${STAGE}\icone.ico"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "Instalação do ${APPNAME} ${VERSION}"
!define MUI_WELCOMEPAGE_TEXT "O ${APPNAME} é um laboratório didático de termodinâmica e mecânica estatística: um gás bidimensional simulado partícula a partícula, com casos como expansão livre, teorema H, mistura de gases, condução de calor e compressão por pistão.$\r$\n$\r$\nA instalação é feita só para o seu usuário e não precisa de permissão de administrador. Tudo o que é necessário (inclusive o Python) vai junto.$\r$\n$\r$\nClique em Avançar para continuar."
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Abrir o ${APPNAME} agora"
!define MUI_FINISHPAGE_RUN_FUNCTION RunApp
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\app\Manual_TermoLab2D.pdf"
!define MUI_FINISHPAGE_SHOWREADME_TEXT "Abrir o manual (PDF)"
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${STAGE}\app\LICENSE"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "PortugueseBR"

Function RunApp
  SetOutPath "$INSTDIR\app"
  Exec '"$INSTDIR\python\pythonw.exe" "$INSTDIR\app\interface.py"'
FunctionEnd

Section "${APPNAME} (obrigatório)" SecMain
  SectionIn RO
  ; atualização: remove a versão anterior do programa (não toca em resultados do usuário)
  RMDir /r "$INSTDIR\app"
  RMDir /r "$INSTDIR\python"
  SetOutPath "$INSTDIR"
  File "${STAGE}\icone.ico"
  SetOutPath "$INSTDIR\python"
  File /r "${STAGE}\python\*.*"
  SetOutPath "$INSTDIR\app"
  File /r "${STAGE}\app\*.*"

  ; atalhos no menu Iniciar (diretório de trabalho = app)
  SetOutPath "$INSTDIR\app"
  CreateDirectory "$SMPROGRAMS\${APPNAME}"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk" "$INSTDIR\python\pythonw.exe" '"$INSTDIR\app\interface.py"' "$INSTDIR\icone.ico" 0 SW_SHOWNORMAL "" "Termodinâmica partícula a partícula"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\Manual do ${APPNAME}.lnk" "$INSTDIR\app\Manual_TermoLab2D.pdf"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\Desinstalar o ${APPNAME}.lnk" "$INSTDIR\Desinstalar.exe"

  WriteUninstaller "$INSTDIR\Desinstalar.exe"
  WriteRegStr HKCU "Software\${APPNAME}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINSTKEY}" "Publisher" "${PUBLISHER}"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayIcon" "$INSTDIR\icone.ico"
  WriteRegStr HKCU "${UNINSTKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTKEY}" "UninstallString" '"$INSTDIR\Desinstalar.exe"'
  WriteRegStr HKCU "${UNINSTKEY}" "QuietUninstallString" '"$INSTDIR\Desinstalar.exe" /S'
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoRepair" 1
  WriteRegDWORD HKCU "${UNINSTKEY}" "EstimatedSize" ${SIZE_KB}
SectionEnd

Section "Atalho na área de trabalho" SecDesktop
  SetOutPath "$INSTDIR\app"
  CreateShortCut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\python\pythonw.exe" '"$INSTDIR\app\interface.py"' "$INSTDIR\icone.ico" 0 SW_SHOWNORMAL "" "Termodinâmica partícula a partícula"
SectionEnd

LangString DESC_Main ${LANG_PORTUGUESEBR} "O programa, o Python e as bibliotecas necessárias, o manual e os exemplos."
LangString DESC_Desktop ${LANG_PORTUGUESEBR} "Cria um atalho do ${APPNAME} na área de trabalho."
!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecMain} $(DESC_Main)
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} $(DESC_Desktop)
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Section "Uninstall"
  Delete "$DESKTOP\${APPNAME}.lnk"
  RMDir /r "$SMPROGRAMS\${APPNAME}"
  RMDir /r "$INSTDIR\app"
  RMDir /r "$INSTDIR\python"
  Delete "$INSTDIR\icone.ico"
  Delete "$INSTDIR\Desinstalar.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "${UNINSTKEY}"
  DeleteRegKey HKCU "Software\${APPNAME}"
SectionEnd
