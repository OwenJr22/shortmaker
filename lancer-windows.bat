@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv" (
  echo Premiere installation, ca peut prendre quelques minutes...
  python -m venv .venv || (echo Python est introuvable. Installe-le depuis python.org en cochant "Add to PATH". & pause & exit /b)
  call .venv\Scripts\activate.bat
  python -m pip install --upgrade pip
  pip install -r requirements.txt
) else (
  call .venv\Scripts\activate.bat
)
python app.py
pause
