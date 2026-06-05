@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion
set "ROOT=%~dp0"
set "PY=python"

:: 1. 自动检测虚拟环境
if exist "%ROOT%.venv\Scripts\python.exe" (
    echo [System] Found virtual environment, using it...
    set "PY=%ROOT%.venv\Scripts\python.exe"
    goto :verify_py
)

echo [System] Virtual environment not found, using global python...
where python >nul 2>nul
if errorlevel 1 (
    echo [Error] Global Python not found in PATH!
    pause
    exit /b 1
)
set "PY=python"

:verify_py
:: 如果不是全局命令 python，则必须是存在的物理文件
if "!PY!" neq "python" (
    if not exist "!PY!" (
        echo [Error] Python executable not found at: "!PY!"
        pause
        exit /b 1
    )
)

set "LOGDIR=%ROOT%logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

echo =======================================
echo    LOF Fund Arbitrage System
echo =======================================
echo.

echo [System] Checking port 5000...
netstat -ano | findstr ":5000 " > nul
if %ERRORLEVEL% equ 0 (
    echo [Warning] Port 5000 is already in use! 
    echo [Cleanup] Attempting to free port 5000...
    for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5000 "') do (
        taskkill /f /pid %%a > nul 2>&1
    )
)

echo [Cleanup] Terminating other Python processes...
taskkill /f /im python.exe > nul 2>&1

set PYTHONIOENCODING=utf-8

echo [1/6] Running daily data update (LOF011)...
"!PY!" -X utf8 LOF011_daily_updater.py
if errorlevel 1 (
    echo [Error] LOF011 failed!
    pause
    exit /b 1
)

echo [2/6] Running static valuation calculation (LOF012)...
"!PY!" -X utf8 LOF012_calculate_static_valuation.py
if errorlevel 1 (
    echo [Error] LOF012 failed!
    pause
    exit /b 1
)

echo [3/6] Starting admin panel (port 5002) in a new window...
start "LOF Admin (5002)" /D "%ROOT%" cmd /k ""!PY!" -X utf8 LOF01_admin_launcher.py"

echo [4/6] Starting data service (port 5000)...
start "LOF Backend (5000)" /D "%ROOT%" cmd /k ""!PY!" -X utf8 LOF02_fetch_trade_data.py"

echo Waiting for initialization (8 sec)...
timeout /t 8 > nul

echo [5/6] Generating report...
pushd "%ROOT%"
set "LOG_DATE=%date:~0,4%%date:~5,2%%date:~8,2%"
"!PY!" -X utf8 LOF03_generate_monitor_html.py > "%LOGDIR%\LOF03_html_generate_%LOG_DATE%.log" 2>&1
if errorlevel 1 (
    echo [Error] 03 failed!
    popd
    pause
    exit /b 1
)
popd
echo Report generated.

echo [6/6] Opening browser...
start "" "http://localhost:5000/"

echo.
echo =======================================
echo System started successfully!
echo Monitor: http://localhost:5000/
echo Admin: http://localhost:5002/
echo =======================================
pause
endlocal
