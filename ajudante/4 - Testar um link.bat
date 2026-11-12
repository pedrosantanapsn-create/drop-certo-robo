@echo off
chcp 65001 >nul
title Drop Certo - Teste do ajudante
cd /d "%~dp0"
python ajudante.py teste
echo.
pause
