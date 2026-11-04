@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (
  echo Rode primeiro o instalar.bat
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
gmt run
pause
