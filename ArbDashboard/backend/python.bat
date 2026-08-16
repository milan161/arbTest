@echo off
REM [AI-2026-08-03] 目录级 python 重定向：让 backend 目录下的 `python` 强制指向项目 .venv，
REM 避免误用系统/WorkBuddy python 导致 IB 行情与冻结调度器静默失效。
REM 仅在本目录生效（cmd 当前目录优先于 PATH），不污染全局环境。等价于 runback.bat 的底层机制。
"%~dp0..\.venv\Scripts\python.exe" %*
