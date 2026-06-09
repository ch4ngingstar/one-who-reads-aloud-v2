@echo off
start "Backend"  /D "%~dp0src" powershell -NoExit -Command "python -m uvicorn api:app --port 8000 --reload"
start "Frontend" /D "%~dp0ui"  powershell -NoExit -Command "npm run dev"
timeout /t 5 /nobreak >nul
start "" "http://localhost:3000"
