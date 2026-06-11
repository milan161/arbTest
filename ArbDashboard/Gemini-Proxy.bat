@echo off
chcp 65001 >nul
title PowerShell 代理配置（Gemini CLI 专用）
echo ========================================
echo   Gemini CLI 专用 PowerShell 代理配置
echo   代理端口：127.0.0.1:10808
echo ========================================
echo.
echo 正在打开 PowerShell 并配置代理...
echo.

:: 启动 PowerShell 并自动执行代理配置命令
powershell -NoExit -Command ^
"$env:HTTP_PROXY = 'http://127.0.0.1:10808'; $env:HTTPS_PROXY = 'http://127.0.0.1:10808'; $env:NO_PROXY = 'localhost,127.0.0.1'; Write-Host '✅ 代理配置成功！当前 PowerShell 会话已启用代理'; Write-Host '👉 现在可以直接运行 gemini 命令登录了'; Write-Host '👉 关闭此窗口后代理自动失效，不影响其他程序'"

pause