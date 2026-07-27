@echo off
title ArbNext Dashboard Launcher
echo ========================================
echo  Starting ArbNext Unified Dashboard...
echo ========================================

set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "VENV=%SCRIPT_DIR%\.venv\Scripts"
set "PY=%VENV%\python.exe"
set "BACKEND=%SCRIPT_DIR%\backend"
set "FRONTEND=%SCRIPT_DIR%\frontend"

:: Kill leftover backend (8000) and frontend (5173) ports
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5173 ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1
timeout /t 2 /nobreak > nul

:: Start Backend (use project venv)
echo [1/2] Starting Backend (port 8000)...
if exist "%PY%" (
  start "ArbNext Backend" cmd /k "cd /d %BACKEND% && %PY% main.py"
) else (
  echo [WARN] venv python not found at %PY%, falling back to system python
  start "ArbNext Backend" cmd /k "cd /d %BACKEND% && python main.py"
)

:: Wait for backend to start (fixed wait; this program does NOT do health-check)
echo Waiting 8 seconds for backend to be ready...
timeout /t 8 /nobreak > nul

:: Start Frontend
echo [2/2] Starting Frontend (port 5173)...
start "ArbNext Frontend" cmd /k "cd /d %FRONTEND% && npm run dev"

echo.
echo ========================================
echo  Backend : http://127.0.0.1:8000
echo  Frontend: http://localhost:5173
echo ========================================
timeout /t 3 /nobreak > nul
start http://localhost:5173
echo Done.
