@echo off
chcp 65001 >nul
cd /d "%~dp0"
.venv\Scripts\gmt.exe seguranca
echo.
.venv\Scripts\gmt.exe categorias
pause
