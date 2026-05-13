@echo off
chcp 65001 > nul
setlocal
set "ROOT=%~dp0"
set "PY=python"
set "LOGDIR=%ROOT%logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

echo =======================================
echo    LOF 基金套利系统 - 一键启动程序
echo =======================================
echo.

where %PY% >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [错误] 找不到 Python 环境，请确保 Python 已安装并添加到系统 PATH。
    pause > nul
    exit /b 1
)

REM 数据库自动创建由 Python 代码处理
echo [系统] 检查数据库...不存在则自动创建。

echo [清理] 正在终止残留的 Python 进程，释放 5000 端口...
taskkill /f /im python.exe > nul 2>&1

set PYTHONIOENCODING=utf-8

echo [0/6] 执行每日数据更新 (011)...
echo (需要 10-30 秒，请稍候...)
"%PY%" -X utf8 LOF011_daily_updater.py
if errorlevel 1 (
    echo [错误] 011 脚本执行失败！
    pause > nul
    exit /b 1
)
echo 011 执行完毕。

echo [1/6] 执行静态估值计算 (012)...
echo (需要 10-30 秒，请稍候...)
"%PY%" -X utf8 LOF012_calculate_static_valuation.py
if errorlevel 1 (
    echo [错误] 012 脚本执行失败！
    pause > nul
    exit /b 1
)
echo 012 执行完毕。

echo [2/6] 启动管理面板 (端口 5002)...
start "LOF Admin (5002)" /D "%ROOT%" cmd /k ""%PY%" -X utf8 LOF01_admin_launcher.py"

echo [3/6] 启动实时数据服务 (端口 5000)...
start "LOF Backend (5000)" /D "%ROOT%" cmd /k ""%PY%" -X utf8 LOF02_fetch_trade_data.py"

echo 等待服务初始化 (8 秒)...
timeout /t 8 > nul

echo [4/6] 生成监控报表...
pushd "%ROOT%"
"%PY%" -X utf8 LOF03_generate_monitor_html.py > "%LOGDIR%\html_generate.log" 2>&1
if errorlevel 1 (
    echo [错误] 03 脚本执行失败，请检查日志！
    pause > nul
    exit /b 1
)
popd
echo 报表生成完毕。

echo [5/6] 打开浏览器...
start "" "http://localhost:5000/"

echo.
echo =======================================
echo 系统已全部启动完毕！
echo 监控面板: http://localhost:5000/
echo 管理后台: http://localhost:5002/
echo =======================================
pause > nul
endlocal
