@echo off
rem Abre o SEARCHING com dados FICTICIOS de demonstracao (nao usa nem altera os seus dados reais).
cd /d "%~dp0..\backend"

set SEARCHING_DB=%CD%\data\demo.db
set SEARCHING_PRINTS=%CD%\data\demo\prints

if not exist venv\Scripts\python.exe (
    echo Ambiente virtual nao encontrado. Rode iniciar_searching.bat uma vez para cria-lo.
    pause
    exit /b 1
)

rem Pillow so e necessario para gerar os prints sinteticos
venv\Scripts\python.exe -c "import PIL" 2>nul || venv\Scripts\python.exe -m pip install -q "Pillow>=10.1"
if not exist data\demo.db venv\Scripts\python.exe -m searching.demo

start "DEMO - BACKEND" cmd /k "venv\Scripts\python.exe server.py"
cd /d "%~dp0..\frontend"
start "DEMO - FRONTEND" cmd /k "npm run dev"
timeout /t 5 >nul
start http://localhost:5173
