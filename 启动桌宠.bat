@echo off
rem Whale Girl Desktop Pet launcher (standalone)
cd /d %~dp0plugins\whale-pet\pet
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw whale_pet.py
) else (
    start "" python whale_pet.py
)
