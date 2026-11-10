@echo off
setlocal DisableDelayedExpansion
set "PCC_INSTALLER=%~dp0PlexConfigControl_Instalator.py"
powershell.exe -NoProfile -Command ^
  "$ErrorActionPreference = 'Stop';" ^
  "if (-not (Test-Path -LiteralPath $env:PCC_INSTALLER -PathType Leaf)) { throw 'Extract the ZIP. Keep the .py file next to this launcher.' };" ^
  "if (-not (Get-Command ssh.exe -ErrorAction SilentlyContinue) -or -not (Get-Command scp.exe -ErrorAction SilentlyContinue)) { throw 'Windows OpenSSH Client is required.' };" ^
  "$server = Read-Host 'Adres IPv4 lub nazwa TrueNAS';" ^
  "$user = Read-Host 'Uzytkownik SSH TrueNAS z dostepem do sudo';" ^
  "if ($server -notmatch '^[a-zA-Z0-9][a-zA-Z0-9.-]*$' -or $user -notmatch '^[a-zA-Z_][a-zA-Z0-9_.-]*$') { throw 'Podaj poprawny adres i nazwe uzytkownika.' };" ^
  "$destination = '{0}@{1}' -f $user, $server;" ^
  "$remoteFile = '/var/tmp/pcc-win-{0}.py' -f [guid]::NewGuid().ToString('N');" ^
  "$uploadTarget = '{0}:{1}' -f $destination, $remoteFile;" ^
  "& scp.exe -o StrictHostKeyChecking=ask $env:PCC_INSTALLER $uploadTarget;" ^
  "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE };" ^
  "$remoteCommand = 'sudo python3 {0}; result=$?; case $result in 0) rm -f -- {0};; esac; exit $result' -f $remoteFile;" ^
  "& ssh.exe -o StrictHostKeyChecking=ask -tt $destination $remoteCommand;" ^
  "$result = $LASTEXITCODE;" ^
  "if ($result -ne 0) { Write-Host ('Plik do ewentualnego wznowienia na TrueNAS: ' + $remoteFile) };" ^
  "exit $result"
set "PCC_RESULT=%ERRORLEVEL%"
pause
exit /b %PCC_RESULT%
