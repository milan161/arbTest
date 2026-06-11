@echo off
echo Starting ArbNext Unified Dashboard...

:: Start Backend in a new window
start "ArbNext Backend" cmd /k "cd backend && d:\Study\arbTest\.venv\Scripts\python.exe main.py"

:: Wait for backend to start (10 seconds to ensure backend is fully ready)
echo Waiting for backend to start...
timeout /t 10 /nobreak > nul

:: Start Frontend in a new window
start "ArbNext Frontend" cmd /k "cd frontend && npm run dev"

echo Dashboard is starting. 
echo Backend: http://127.0.0.1:8000
echo Frontend: http://localhost:5173

:: Open browser after 3 seconds
timeout /t 3 /nobreak > nul
start http://localhost:5173

pause
