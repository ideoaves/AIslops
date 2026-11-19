@echo off
rem Open the WebM converter. The console stays so errors are readable.
chcp 65001 >nul
python "%~dp0webm_convert.py" %*
echo.
pause
