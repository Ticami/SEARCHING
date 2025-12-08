@echo off
cd /d "%~dp0"

echo ==========================================
echo 🚀 INICIANDO SEARCHING PROJECT
echo ==========================================

:: Ativar venv
cd backend
if not exist venv (
    echo Criando ambiente virtual...
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install -r requirements.txt
) else (
    call venv\Scripts\activate.bat
)
start "BACKEND" cmd /k "python server.py"
cd ..

cd frontend
start "FRONTEND" cmd /k "npm run dev"
cd ..

start http://localhost:5173
