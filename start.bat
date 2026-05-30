@echo off
REM Windows one-click launcher.
REM Double-click in Explorer or run from cmd: start.bat
setlocal

cd /d "%~dp0"

if not exist ".env" (
  echo [!] .env not found.
  if exist ".env.example" (
    copy /Y ".env.example" ".env" >nul
    echo [i] copied .env.example to .env
    echo [!] Please open .env, fill in DAILY_NEWS_AGENT_API_KEY, then re-run start.bat.
  ) else (
    echo [x] .env.example is also missing. Cannot continue.
  )
  pause
  exit /b 1
)

where docker >nul 2>nul
if errorlevel 1 (
  echo [x] Docker is not installed or not in PATH. Install Docker Desktop first.
  pause
  exit /b 1
)

echo [i] building image and starting container ...
docker compose up -d --build
if errorlevel 1 (
  echo [x] docker compose failed. Make sure Docker Desktop is running.
  pause
  exit /b 1
)

echo.
echo [OK] daily-news is running. Open http://localhost:8765
echo      tail logs:  docker compose logs -f
echo      stop:       docker compose down
echo.
pause
endlocal
