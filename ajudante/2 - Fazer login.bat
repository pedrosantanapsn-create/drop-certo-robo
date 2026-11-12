@echo off
chcp 65001 >nul
title Drop Certo - Login do ajudante
cd /d "%~dp0"
python ajudante.py login
echo.
pause
