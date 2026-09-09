@echo off
REM Digital Twin API Startup Script for Windows
REM Production deployment with uvicorn

REM Set default port if not specified
if "%PORT%"=="" set PORT=8000

REM Set environment variables for production
set PYTHONPATH=%PYTHONPATH%;%CD%
set ENVIRONMENT=production

REM Create logs directory if it doesn't exist
if not exist logs mkdir logs

echo Starting Digital Twin API Server...
echo Port: %PORT%
echo Environment: %ENVIRONMENT%
echo Timestamp: %date% %time%

REM Start the FastAPI application with uvicorn
uvicorn api.main:app --host 0.0.0.0 --port %PORT% --workers 1 --log-level info
