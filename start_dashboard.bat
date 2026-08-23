@echo off
title ArbNext Dashboard Launcher

:: [AI-2026-08-20] 启动前确认客户端已开：Enter 继续 / Esc 退出批处理
powershell -NoProfile -Command "$Host.UI.RawUI.FlushInputBuffer(); Write-Host ''; Write-Host '【启动前检查】请先确保以下客户端已启动：' -ForegroundColor Yellow; Write-Host '   - IB Gateway  (美股行情)' -ForegroundColor White; Write-Host '   - 富途 OpenD  (外盘 ETF 10档)' -ForegroundColor White; Write-Host '   - 通达信      (A股盘口)' -ForegroundColor White; Write-Host '   - 银河 QMT   (LOF 下单通道)' -ForegroundColor White; Write-Host ''; Write-Host '按 [Enter] 确认已启动并继续, 按 [Esc] 退出去启动客户端' -ForegroundColor Cyan; while($true){$k=$Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown'); if($k.VirtualKeyCode -eq 13){break} if($k.VirtualKeyCode -eq 27){exit 1}}"
if errorlevel 1 (
  echo [已取消] 你选择退出。请启动上述客户端后重新运行本批处理。
  exit /b
)

echo ========================================
echo  Starting ArbNext Unified Dashboard...
echo ========================================

set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
:: [AI-2026-08-20] 本脚本已上移至 src\ 层，实际项目根目录在 ArbDashboard 子目录，故统一定位到 PROJ_DIR
set "PROJ_DIR=%SCRIPT_DIR%\ArbDashboard"
set "VENV=%PROJ_DIR%\.venv\Scripts"
set "PY=%VENV%\python.exe"
set "BACKEND=%PROJ_DIR%\backend"
set "FRONTEND=%PROJ_DIR%\frontend"

:: [AI-2026-08-17] 清空 PYTHONPATH：防止继承外层终端（如国金 QMT）注入的 GJQMT 路径，
:: 否则其老版本 defusedxml 会因 PYTHONPATH 在 sys.path 中先于 venv 而覆盖 venv 包，导致导入 V7 报 XMLParser 错误。
set "PYTHONPATH="

:: Kill leftover backend (8000) and frontend (5173) ports
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5173 ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1
timeout /t 2 /nobreak > nul

:: Start Backend (STRICTLY project venv — 禁止回退到系统/WorkBuddy python，否则 IB/富途/冻结调度器缺失依赖静默失效)
echo [1/2] Starting Backend (port 8000)...
if exist "%PY%" (
  start "ArbNext Backend" cmd /k "cd /d %BACKEND% && %PY% main.py"
) else (
  echo [FATAL] 找不到项目虚拟环境解释器: %PY%
  echo [FATAL] 请勿回退到系统 python（缺 ibapi/apscheduler 会导致 IB 行情与冻结调度器失效）
  echo [FATAL] 请确认 ArbDashboard/.venv 存在；或用 .venv\Scripts\python.exe 直接启动 main.py
  pause
  exit /b 1
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
