@echo off
rem One-click start: backend (uvicorn via .venv) + frontend (vite)
rem 先杀掉占用 8000 的旧进程（防 --reload 残留的僵尸进程占端口，省得手动清）
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8000 " ^| findstr LISTENING') do (
  echo Killing stale process %%P on port 8000
  taskkill /F /PID %%P >nul 2>&1
)
start "ACP Backend" cmd /k "cd /d %~dp0backend && .venv\Scripts\activate && uvicorn app.main:app --reload"
start "ACP Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"
echo Backend: http://127.0.0.1:8000/docs
echo Frontend: http://localhost:5173
