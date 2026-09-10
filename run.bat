@echo off
chcp 65001 >nul
title NORD bot
cd /d "%~dp0"

if not exist ".env" (
  echo Fayl .env yok. .env.example dosyasini .env olarak kopyalayip BOT_TOKEN yazin.
  pause
  exit /b 1
)

python -m pip install -q -r requirements.txt
python bot.py
pause
