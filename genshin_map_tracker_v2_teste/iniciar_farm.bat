@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Iniciando Genshin Map Tracker (modo completo + farm de especialidades e minerios)...
.venv\Scripts\gmt.exe run --respawnables
pause
