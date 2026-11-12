@echo off
chcp 65001 >nul
title Drop Certo - Instalar ajudante
cd /d "%~dp0"
echo ============================================
echo   Drop Certo - instalando o ajudante
echo ============================================
echo.
rem O Windows tem um "python" falso que so abre a loja: por isso testamos a versao de verdade
python --version >nul 2>nul
if errorlevel 1 (
  echo O Python nao esta instalado neste computador.
  echo.
  echo 1. Abra a Microsoft Store, procure "Python 3.12" e clique em Instalar.
  echo    ^(ou baixe em https://www.python.org/downloads/ e marque "Add python.exe to PATH"^)
  echo 2. Depois abra este arquivo de novo.
  echo.
  pause
  exit /b 1
)
echo Instalando os programas do ajudante ^(pode levar alguns minutos^)...
python -m pip install --upgrade pip >nul
python -m pip install playwright requests
if errorlevel 1 (
  echo.
  echo Deu erro na instalacao. Tire um print desta janela e mande para o Claude.
  pause
  exit /b 1
)
if not exist senha.txt (
  echo.> senha.txt
  echo.
  echo Criei o arquivo senha.txt nesta pasta. Abra ele no Bloco de Notas,
  echo cole a SENHA DO AJUDANTE ^(a que o Supabase mostrou^) e salve.
)
echo.
echo Pronto! Agora:  1^) cole a senha no senha.txt   2^) abra "2 - Fazer login.bat"
echo.
pause
