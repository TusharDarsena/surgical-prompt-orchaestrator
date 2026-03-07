@echo off
TITLE SPO Launcher
SET "PROJECT_DIR=C:\Users\TUSHAR\Desktop\surgical prompt orchaestrator"

:: Check if directory exists
if not exist "%PROJECT_DIR%" (
    echo [ERROR] Directory not found: %PROJECT_DIR%
    pause
    exit /b
)

echo ==========================================
echo Starting Surgical Prompt Orchestrator...
echo ==========================================
echo.

:: Start Backend (Uvicorn)
echo [1/2] Starting Backend on port 8000...
start "SPO Backend" cmd /c "cd /d %PROJECT_DIR%\spo_backend && python -m uvicorn main:app --reload --port 8000"

:: Buffer for Backend to start
timeout /t 4 /nobreak > nul

:: Start Frontend (Streamlit)
echo [2/2] Starting Frontend on port 8501...
start "SPO Frontend" cmd /c "cd /d %PROJECT_DIR%\spo_frontend && python -m streamlit run app.py"

echo.
echo ------------------------------------------
echo Servers are running!
echo Backend:  http://localhost:8000
echo Frontend: http://localhost:8501
echo ------------------------------------------
echo.
echo Keep this window open or close it; the apps are in their own windows.
pause