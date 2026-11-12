@echo off
chcp 65001 >nul
title Drop Certo - Login do ajudante
cd /d "%~dp0"
rem Pega a versao mais nova do ajudante (se a internet falhar, usa a que ja esta aqui)
curl -s -f -o ajudante_novo.py https://raw.githubusercontent.com/pedrosantanapsn-create/drop-certo-robo/main/ajudante/ajudante.py
if not errorlevel 1 (
  for %%A in (ajudante_novo.py) do if %%~zA GTR 2000 move /y ajudante_novo.py ajudante.py >nul
)
if exist ajudante_novo.py del ajudante_novo.py
python ajudante.py login
echo.
pause
