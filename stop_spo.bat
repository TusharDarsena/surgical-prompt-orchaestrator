@echo off
TITLE SPO Terminator
echo ==========================================
echo Stopping Surgical Prompt Orchestrator...
echo ==========================================
echo.

:: Kill Backend on 8000
echo Finding and stopping Backend (Port 8000)...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000') do (
    taskkill /f /pid %%a 2>nul
    echo Stopped process PID: %%a
)

:: Kill Frontend on 8501
echo Finding and stopping Frontend (Port 8501)...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8501') do (
    taskkill /f /pid %%a 2>nul
    echo Stopped process PID: %%a
)

:: Also kill the terminal windows by title to ensure reloaders are stopped and windows close
echo Closing SPO terminal windows...
taskkill /f /t /fi "WINDOWTITLE eq SPO Backend*" >nul 2>&1
taskkill /f /t /fi "WINDOWTITLE eq SPO Frontend*" >nul 2>&1

echo.
echo ------------------------------------------
echo Cleanup complete. All SPO services stopped.
echo ------------------------------------------
timeout /t 3
exit