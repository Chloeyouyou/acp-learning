@echo off
rem One-click start: backend (uvicorn via .venv) + frontend (vite)
start "ACP Backend" cmd /k "cd /d %~dp0backend && .venv\Scripts\activate && uvicorn app.main:app --reload"
start "ACP Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"
echo Backend: http://127.0.0.1:8000/docs
echo Frontend: http://localhost:5173
