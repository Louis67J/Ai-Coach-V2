@echo off
REM Lance le dashboard web. Double-clic depuis l'explorateur, ou .\start-web.bat
cd /d "%~dp0"
call .venv\Scripts\activate.bat
echo Dashboard sur http://localhost:8501  (Ctrl+C pour arreter)
streamlit run src\ai_coach\web\app.py
pause
