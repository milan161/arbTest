@echo off
chcp 65001 > nul
setlocal
set "ROOT=%~dp0"
set "PY=C:\Users\milan\AppData\Local\Programs\Python\Python311\python.exe"
set "LOGDIR=%ROOT%logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

echo =======================================
echo    LOF 基金套利系统 - 一键启动程序
echo =======================================
echo.

if not exist "%PY%" (
  echo [错误] 找不到 Python，请检查路径是否正确: %PY%
  pause > nul
  exit /b 1
)

echo [清理] 正在结束可能残留的后台进程，彻底释放 5000 端口...
taskkill /f /im python.exe > nul 2>&1

set PYTHONIOENCODING=utf-8

echo [0/6] 正在获取今日最新基础数据 (011)...
echo (这一步需要10-30秒，请稍候...)
"%PY%" -X utf8 LOF011_generate_basic_data.py > "%LOGDIR%\011_auto.log" 2>&1
echo 011 执行完毕！

echo [1/6] 正在获取今日LOF历史数据 (012)...
echo (这一步需要10-30秒，请稍候...)
"%PY%" -X utf8 LOF012_generate_lof_data.py > "%LOGDIR%\012_auto.log" 2>&1
echo 012 执行完毕！

echo [2/6] 启动维护面板后台 (端口 5002)...
start "LOF Admin (5002)" /D "%ROOT%" cmd /k ""%PY%" -X utf8 LOF01_admin_launcher.py"

echo [3/6] 启动实时数据与行情服务 (端口 5000)...
start "LOF Backend (5000)" /D "%ROOT%" cmd /k ""%PY%" -X utf8 LOF02_fetch_trade_data.py"

echo 等待后台服务初始化及IB连接握手 (8秒)...
timeout /t 8 > nul

echo [4/6] 正在检查历史数据并生成今日监控报表...
echo (如果需要爬取新数据，这一步可能需要10-20秒，请稍候...)
pushd "%ROOT%"
"%PY%" -X utf8 LOF03_generate_monitor_html.py > "%LOGDIR%\html_generate.log" 2>&1
popd
echo 报表生成完毕！

echo [5/6] 自动打开浏览器...
start "" "http://localhost:5000/"

echo.
echo =======================================
echo 系统已全部启动完毕！
echo 监控看板地址: http://localhost:5000/
echo 维护后台地址: http://localhost:5002/
echo.
echo (提示：已自动运行 011 和 012 获取今日最新数据)
echo (提示：后台服务已在隐藏窗口运行，关闭此黑色窗口不会影响系统运行。)
echo =======================================
pause > nul
endlocal