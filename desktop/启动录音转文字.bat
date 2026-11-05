@echo off
title 录音转文字工作台
cd /d "%~dp0server"
python server.py
if errorlevel 1 (
  echo.
  echo [启动失败] 请截图本窗口内容联系维护人。
  echo 检查：电脑上是否安装 Python 3.13（本产品依赖其内置库）。
  pause
)
