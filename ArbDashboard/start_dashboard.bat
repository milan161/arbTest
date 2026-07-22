@echo off
setlocal enabledelayedexpansion
title ArbNext Dashboard Launcher
echo ========================================
echo  Starting ArbNext Unified Dashboard...
echo ========================================

:: 【AI-2026-07-22】改用 %~dp0 相对路径，消除硬编码依赖
set SCRIPT_DIR=%~dp0
set SCRIPT_DIR=%SCRIPT_DIR:~0,-1%

:: ===== 环境检测 =====
echo.
echo --- Environment Check ---

:: 1. Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Python 未安装！请安装 Python 3.11 或 3.12
    echo       下载: https://www.python.org/downloads/
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo [OK] Python %PY_VER%

:: 2. Node.js
node --version >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Node.js 未安装！请安装 Node.js 18+
    echo       下载: https://nodejs.org/
    pause
    exit /b 1
)
for /f %%v in ('node --version') do set NODE_VER=%%v
echo [OK] Node %NODE_VER%

:: 3. npm
npm --version >nul 2>&1
if errorlevel 1 (
    echo [FAIL] npm 未安装！
    pause
    exit /b 1
)
for /f %%v in ('npm --version') do set NPM_VER=%%v
echo [OK] npm %NPM_VER%

:: 4. 检测 Python 虚拟环境
set VENV_DIR=%SCRIPT_DIR%\..\.venv
if exist "%VENV_DIR%\Scripts\python.exe" (
    set PYTHON_EXE=%VENV_DIR%\Scripts\python.exe
    echo [OK] 使用虚拟环境: %VENV_DIR%
) else (
    set PYTHON_EXE=python
    echo [WARN] 未找到虚拟环境，使用系统 Python
)

:: 5. pip install（跳过已安装的）
echo.
echo --- Installing Python Dependencies ---
if exist "%SCRIPT_DIR%\backend\requirements.txt" (
    "%PYTHON_EXE%" -m pip install -r "%SCRIPT_DIR%\backend\requirements.txt" -q 2>nul
    echo [OK] Python 依赖检查完成
) else (
    echo [WARN] 未找到 requirements.txt，跳过
)

:: 6. npm install（跳过已安装的）
echo.
echo --- Installing Frontend Dependencies ---
if exist "%SCRIPT_DIR%\frontend\package.json" (
    cd /d "%SCRIPT_DIR%\frontend"
    npm install --silent 2>nul
    echo [OK] Frontend 依赖检查完成
) else (
    echo [WARN] 未找到 package.json，跳过
)

:: ===== 启动 =====
echo.
echo --- Starting Services ---

:: Kill any leftover backend process on port 8000 first
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
    echo  Killing old process PID: %%a
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 2 /nobreak > nul

:: Start Backend in a new window
echo [1/3] Starting Backend (port 8000)...
start "ArbNext Backend" cmd /k "cd /d "%SCRIPT_DIR%\backend" && "%PYTHON_EXE%" main.py"

:: Health check retry loop (waits up to 30 seconds)
echo Waiting for backend to start (checking every 2s, max 30s)...
for /l %%i in (1,1,15) do (
    timeout /t 2 /nobreak > nul
    for /f %%j in ('curl -s -o nul -w %%{http_code} http://127.0.0.1:8000/api/system/milestones 2^>nul') do (
        if "%%j"=="200" (
            echo Backend is ready! (attempt %%i)
            goto :backend_ready
        )
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
start "ArbNext Frontend" cmd /k "cd /d "%SCRIPT_DIR%\frontend" && npm run dev"

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
