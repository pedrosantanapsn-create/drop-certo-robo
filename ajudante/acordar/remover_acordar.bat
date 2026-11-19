@echo off
chcp 65001 >nul
title Drop Certo - desfazer o "acordar sozinho"
net session >nul 2>&1
if errorlevel 1 (
  echo  [!] Abra este arquivo com o botao direito ^> "Executar como administrador".
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-ScheduledTask -TaskName 'DropCerto Acordar*' -ErrorAction SilentlyContinue | Unregister-ScheduledTask -Confirm:$false;" ^
  "Write-Host '  OK  tarefas removidas'"
echo.
echo  As tarefas foram removidas: o PC nao acorda mais sozinho por causa do Drop Certo.
echo  A opcao "Permitir temporizadores de ativacao" continua ligada (outros programas
echo  podem usar). Para desligar: Painel de Controle ^> Opcoes de Energia ^> Alterar
echo  configuracoes do plano ^> Configuracoes avancadas ^> Suspender.
echo.
pause
