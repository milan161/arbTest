@echo off
title ArbNext Dashboard Launcher
echo ========================================
echo  Starting ArbNext Unified Dashboard...
echo ========================================

set SCRIPT_DIR=%~dp0
set SCRIPT_DIR=%SCRIPT_DIR:~0,-1%

:: Kill leftover backend on port 8000
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1
timeout /t 2 /nobreak > nul

:: Start Backend
echo [1/2] Starting Backend (port 8000)...
start "ArbNext Backend" cmd /k "cd /d "%SCRIPT_DIR%\backend" && python main.py"

:: Start Frontend
echo [2/2] Starting Frontend (port 5173)...
start "ArbNext Frontend" cmd /k "cd /d "%SCRIPT_DIR%\frontend" && npm run dev"

echo.
echo ========================================
echo  Backend: http://127.0.0.1:8000
echo  Frontend: http://localhost:5173
echo ========================================
timeout /t 3 /nobreak > nul
start http://localhost:5173
echo Done.
pause>nul
