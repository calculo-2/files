@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (
  echo Rode primeiro o instalar.bat
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
echo Deixe o Genshin aberto (tela cheia). Este teste leva uns 2 minutos.
echo.
gmt diagnostico
echo.
echo Mande o arquivo .zip indicado acima.
pause
