@echo off
echo Triggering Automation...
cd /d "C:\GST Bot"

rem ?? Add this exact line to force emoji support:
set PYTHONIOENCODING=utf-8

python gst_bot.py >> "C:\GST Bot\midnight_log.txt" 2>&1