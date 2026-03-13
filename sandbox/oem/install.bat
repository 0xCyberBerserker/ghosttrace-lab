@echo off
setlocal

set SCRIPT_ROOT=%~dp0
set LOG_DIR=%SCRIPT_ROOT%logs
set LOG_FILE=%LOG_DIR%\install-bootstrap.log
set TASK_NAME_START=AIReverseLabFullLabOnStart
set TASK_NAME_LOGON=AIReverseLabFullLabOnLogon
set MARKER_FILE=%LOG_DIR%\install-bat-ran.txt
set TASK_CMD=powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\OEM\install_full_lab.ps1

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo install.bat executed at %DATE% %TIME%>"%MARKER_FILE%"
echo [%DATE% %TIME%] Scheduling first-boot reverse lab provisioning...>>"%LOG_FILE%"

schtasks /Create /F /RU SYSTEM /RL HIGHEST /SC ONSTART /DELAY 0000:30 /TN "%TASK_NAME_START%" /TR "%TASK_CMD%" >>"%LOG_FILE%" 2>&1
if errorlevel 1 (
  echo [%DATE% %TIME%] Failed to create scheduled task %TASK_NAME_START%.>>"%LOG_FILE%"
  exit /b 1
)

schtasks /Create /F /RU SYSTEM /RL HIGHEST /SC ONLOGON /TN "%TASK_NAME_LOGON%" /TR "%TASK_CMD%" >>"%LOG_FILE%" 2>&1
if errorlevel 1 (
  echo [%DATE% %TIME%] Failed to create scheduled task %TASK_NAME_LOGON%.>>"%LOG_FILE%"
  exit /b 1
)

schtasks /Run /TN "%TASK_NAME_START%" >>"%LOG_FILE%" 2>&1
echo [%DATE% %TIME%] Scheduled tasks %TASK_NAME_START% and %TASK_NAME_LOGON% created. Startup task triggered immediately.>>"%LOG_FILE%"

endlocal
exit /b 0
