@echo off
REM Abre o dashboard solar da Wanda.
cd /d "%~dp0"
if not exist .venv ( echo Rode setup.bat primeiro. & pause & exit /b 1 )
call .venv\Scripts\activate.bat
streamlit run app.py
