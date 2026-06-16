@echo off
setlocal enabledelayedexpansion
title ArbNext Dashboard Launcher
echo ========================================
echo  Starting ArbNext Unified Dashboard...
echo ========================================

:: Kill any leftover backend process on port 8000 first
echo [Pre-check] Cleaning port 8000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
    echo  Killing old process PID: %%a
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 2 /nobreak > nul

:: Start Backend in a new window (visible so user can see errors)
echo [1/3] Starting Backend (port 8000)...
start "ArbNext Backend" cmd /k "cd /d D:\Study\arbTest\ArbDashboard\backend && D:\Study\arbTest\.venv\Scripts\python.exe main.py"

:: Health check retry loop (waits up to 30 seconds)
echo Waiting for backend to start (checking every 2s, max 30s)...
for /l %%i in (1,1,15) do (
    timeout /t 2 /nobreak > nul
    curl -s -o nul -w %%{http_code} http://127.0.0.1:8000/api/system/milestones 2>nul | findstr "200" >nul
    if !errorlevel! equ 0 (
        echo Backend is ready! (attempt %%i)
        goto :backend_ready
    )
)

echo.
echo WARNING: Backend did not respond within 30 seconds.
echo Check the 'ArbNext Backend' window for error messages.
pause
exit /b 1

:backend_ready
echo [2/3] Backend health check PASSED

:: Start Frontend in a new window
echo [3/3] Starting Frontend (port 5173)...
start "ArbNext Frontend" cmd /k "cd /d D:\Study\arbTest\ArbDashboard\frontend && npm run dev"

echo.
echo ========================================
echo  Backend: http://127.0.0.1:8000
echo  Frontend: http://localhost:5173
echo ========================================
echo.

:: Open browser after 3 seconds
timeout /t 3 /nobreak > nul
start http://localhost:5173

echo Done. Keep both windows open.
echo Close this window or press any key to exit.
pause>nul
