@echo off
REM Liga o robo no seu PC (responde na hora). Feche a janela para desligar.
cd /d "%~dp0"
python -m pip install -q -r requirements.txt
python main.py --continuo
pause
