@echo off
set "SH=%~dp0check_deploy.sh"
echo Checking NAS deploy package...
bash "%SH%"
echo.
echo PASSED: upload this folder to NAS and create the Compose project.
echo FAILED: edit .env with notepad, then run this again.
pause
