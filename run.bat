@echo off
echo.
echo   Arkham Horror TTS App
echo   Installing dependencies...
echo.
pip install -r requirements.txt >nul 2>&1
echo   Starting app...
echo   Open http://localhost:5000 in your browser
echo.
python app.py
pause
