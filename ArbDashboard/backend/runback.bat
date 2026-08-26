@echo off
REM [AI-2026-08-03] 仅前台启动后端（Ctrl+C 后回到 backend 目录，贴合手动调试习惯），强制使用项目 .venv 解释器（禁止回退系统/WorkBuddy python，否则 IB 行情与冻结调度器静默失效）
set "VENV=%~dp0..\.venv\Scripts\python.exe"
if not exist "%VENV%" (
  echo [FATAL] 找不到项目虚拟环境: %VENV%
  echo 请勿用系统 python 启动（缺 ibapi/apscheduler 会导致 IB 行情与冻结调度器失效）
  pause
  exit /b 1
)
REM [AI-2026-08-03] 启动前释放 8000 端口：本项目仅后端使用 8000。若被残留进程占用，
REM 会导致 .venv 后端因 Errno 10048 起不来、IB 行情静默失效。强杀任何 8000 占用者再启动。
powershell -NoProfile -Command "$p=(Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue).OwningProcess | Where-Object { $_ -ne $null -and $_ -ne 0 }; if($p){$p | ForEach-Object { Write-Host ('[runback] 释放占用 8000 的残留进程 PID ' + $_); Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }}"
:: 等待 8000 端口真正释放（最多 10 秒）再启动后端，杜绝旧进程赖着导致新进程绑端口失败
powershell -NoProfile -Command "for($i=0;$i -lt 10;$i++){ if(-not (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)){ break }; Start-Sleep -Seconds 1 }"
set "PYTHONPATH="
cd /d "%~dp0"
"%VENV%" main.py
