@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (
  echo Rode primeiro o instalar.bat
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
echo Este passo baixa o mapa de Teyvat do site (uma vez so, uns 30 minutos).
echo Pode usar o PC normalmente enquanto isso. Se fechar, rode de novo: continua de onde parou.
echo.
gmt preparar-mapa
echo.
pause
