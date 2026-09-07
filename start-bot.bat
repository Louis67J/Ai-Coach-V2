@echo off
REM Lance le bot Discord (necessaire pour recevoir le brief du matin).
REM Un seul bot a la fois : deux instances repondent en double.
cd /d "%~dp0"
call .venv\Scripts\activate.bat
echo Bot Discord demarre  (Ctrl+C pour arreter)
python -m ai_coach.main bot
pause
