@echo off
chcp 65001 >nul
title Drop Certo - PC acorda sozinho para o ajudante
echo.
echo  Este instalador faz o Windows ACORDAR o PC sozinho em horarios marcados
echo  e abrir o Edge, para o ajudante (extensao) gerar os links pendentes.
echo  Depois o PC volta a dormir sozinho, pelo tempo de suspensao do Windows.
echo.
echo  O que ele muda no Windows:
echo    1) cria 4 tarefas agendadas chamadas "DropCerto Acordar ..."
echo    2) liga a opcao de energia "Permitir temporizadores de ativacao" (na tomada)
echo  Para desfazer tudo: remover_acordar.bat
echo.
net session >nul 2>&1
if errorlevel 1 (
  echo  [!] Abra este arquivo com o botao direito ^> "Executar como administrador".
  echo.
  pause
  exit /b 1
)
set /p HORAS="Horarios para acordar (ENTER = 09:00,13:00,18:00,21:00): "
if "%HORAS%"=="" set HORAS=09:00,13:00,18:00,21:00
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$edge = @(\"$env:ProgramFiles(x86)\Microsoft\Edge\Application\msedge.exe\", \"$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe\") | Where-Object { Test-Path $_ } | Select-Object -First 1;" ^
  "if (-not $edge) { Write-Host ' [!] Nao achei o Edge neste PC.'; exit 1 };" ^
  "Get-ScheduledTask -TaskName 'DropCerto Acordar*' -ErrorAction SilentlyContinue | Unregister-ScheduledTask -Confirm:$false;" ^
  "$cfg = New-ScheduledTaskSettingsSet -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 5);" ^
  "$acao = New-ScheduledTaskAction -Execute $edge -Argument '--no-startup-window';" ^
  "$quem = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive;" ^
  "foreach ($h in '%HORAS%'.Split(',')) { $h = $h.Trim(); if ($h -notmatch '^\d{1,2}:\d{2}$') { Write-Host \" [!] Horario invalido: $h\"; continue };" ^
  "  $nome = 'DropCerto Acordar ' + $h.Replace(':','h');" ^
  "  Register-ScheduledTask -TaskName $nome -Action $acao -Trigger (New-ScheduledTaskTrigger -Daily -At $h) -Settings $cfg -Principal $quem -Description 'Acorda o PC e abre o Edge para o ajudante do Drop Certo' | Out-Null;" ^
  "  Write-Host \"  OK  acorda todo dia as $h\" };" ^
  "powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1 | Out-Null; powercfg /setactive SCHEME_CURRENT | Out-Null;" ^
  "Write-Host '  OK  temporizadores de ativacao ligados (na tomada)'"
if errorlevel 1 (
  echo.
  echo  [!] Algo deu errado. Tire um print desta janela e mande para o Claude.
  pause
  exit /b 1
)
echo.
echo  PRONTO. Para funcionar:
echo    - deixe o PC em SUSPENSAO (Iniciar ^> Ligar/Desligar ^> Suspender), nao desligado;
echo    - deixe na tomada;
echo    - o Edge precisa estar logado no Mercado Livre e com a extensao ativa.
echo  Teste: suspenda o PC uns minutos antes de um dos horarios e veja se ele acorda.
echo.
pause
