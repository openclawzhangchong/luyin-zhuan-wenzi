@echo off
title 下载语音识别模型（仅模型缺失时需要运行）
cd /d "%~dp0server"
echo 正在从国内镜像下载 faster-whisper-small 模型（约 460MB，只下载一次）...
python -c "import os;os.environ['HF_ENDPOINT']='https://hf-mirror.com';from huggingface_hub import snapshot_download;snapshot_download(repo_id='Systran/faster-whisper-small',local_dir='models/faster-whisper-small',allow_patterns=['*.bin','*.json','*.txt'])"
echo.
echo [完成] 请运行「启动录音转文字.bat」。
pause
