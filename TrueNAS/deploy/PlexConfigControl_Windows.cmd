@echo off
setlocal DisableDelayedExpansion
set "PCC_DIRECTORY=%~dp0"
powershell.exe -NoProfile -Command ^
  "$ErrorActionPreference = 'Stop';" ^
  "Write-Host ('=' * 52) -ForegroundColor Cyan; Write-Host '  PlexConfigControl | Setup' -ForegroundColor Cyan; Write-Host ('=' * 52) -ForegroundColor Cyan; Write-Host ''; Write-Host '  1. English'; Write-Host '  2. Polski';" ^
  "do { $choice = Read-Host 'Choose language [1]'; if ($choice -notin '', '1', '2') { Write-Host 'Enter 1 for English or 2 for Polish.' } } until ($choice -in '', '1', '2');" ^
  "function Message($english, $polish) { if ($choice -eq '2') { $polish } else { $english } };" ^
  "$name = Message 'PlexConfigControl_Installer.py' 'PlexConfigControl_Instalator.py';" ^
  "$installer = Join-Path $env:PCC_DIRECTORY $name;" ^
  "if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) { throw (Message 'Extract the entire ZIP. Keep the .py file next to this launcher.' 'Rozpakuj caly ZIP. Plik .py musi lezec obok skrotu.') };" ^
  "if (-not (Get-Command ssh.exe -ErrorAction SilentlyContinue) -or -not (Get-Command scp.exe -ErrorAction SilentlyContinue)) { throw (Message 'Windows OpenSSH Client is required.' 'Potrzebny jest klient OpenSSH dla Windows.') };" ^
  "do {" ^
  "  $destination = Read-Host (Message 'TrueNAS SSH address (user@host or SSH alias)' 'Adres SSH TrueNAS (uzytkownik@host lub alias SSH)');" ^
  "  $valid = $destination -match '^([a-zA-Z_][a-zA-Z0-9_.-]*@)?[a-zA-Z0-9][a-zA-Z0-9.-]*$';" ^
  "  if (-not $valid) { Write-Host (Message 'Enter user@host or a valid SSH alias.' 'Wpisz uzytkownik@host albo poprawny alias SSH.') };" ^
  "} until ($valid);" ^
  "$remoteFile = '/var/tmp/pcc-win-{0}.py' -f [guid]::NewGuid().ToString('N');" ^
  "$uploadTarget = '{0}:{1}' -f $destination, $remoteFile;" ^
  "& scp.exe -o StrictHostKeyChecking=ask $installer $uploadTarget;" ^
  "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE };" ^
  "$remoteCommand = 'sudo -- python3 {0} --desktop --ssh-connection $SSH_CONNECTION; result=$?; rm -f -- {0}; exit $result' -f $remoteFile;" ^
  "& ssh.exe -o StrictHostKeyChecking=ask -tt $destination $remoteCommand;" ^
  "$result = $LASTEXITCODE;" ^
  "exit $result"
set "PCC_RESULT=%ERRORLEVEL%"
pause
exit /b %PCC_RESULT%
