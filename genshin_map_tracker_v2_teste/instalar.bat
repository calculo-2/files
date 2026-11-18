@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Instalando o Genshin Map Tracker ===
where py >nul 2>nul
if errorlevel 1 (
  echo Python nao encontrado. Instale o Python 3.13 em python.org
  echo marcando "Add python.exe to PATH" e rode este arquivo de novo.
  pause
  exit /b 1
)
if not exist .venv\Scripts\activate.bat (
  py -3.13 -m venv .venv 2>nul || py -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -e ".[web,ocr]"
if errorlevel 1 (
  echo.
  echo A instalacao falhou. Tire um print desta janela e mande.
  pause
  exit /b 1
)
if not exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" (
  echo Chrome nao encontrado: instalando o navegador do Playwright...
  python -m playwright install chromium
)
echo.
echo === Pronto! Agora de dois cliques em diagnostico.bat ===
pause
