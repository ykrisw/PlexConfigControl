"""Hidden password input using a capability-tested native shell builtin."""


class QnapTerminalError(RuntimeError):
    pass


def secure_terminal_password(prompt, *, tty_path='/dev/tty'):
    import os
    import subprocess
    from pathlib import Path

    # QNAP omits both Python termios and stty on some firmware builds. The
    # shell's read -s builtin controls its terminal directly, without either.
    # Probe the exact options against EOF before asking for any real secret.
    candidates = [('/bin/sh',), ('/bin/bash',), ('/bin/busybox', 'sh')]
    shell = None
    environment = {'PATH': '/bin:/usr/bin', 'LC_ALL': 'C'}
    for candidate in candidates:
        if not Path(candidate[0]).is_file() or not os.access(candidate[0], os.X_OK):
            continue
        try:
            probe = subprocess.run([*candidate, '-c',
                'IFS= read -r -s -p "" pcc_probe </dev/null'],
                stdin=subprocess.DEVNULL, capture_output=True,
                env=environment, timeout=5, check=False)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if probe.returncode == 1 and not probe.stdout and not probe.stderr:
            shell = candidate
            break
    if shell is None:
        raise QnapTerminalError('Powłoka nie obsługuje ukrytego wpisywania hasła — przerwano przed logowaniem.')
    try:
        terminal = open(tty_path, 'r+b', buffering=0)
    except OSError:
        raise QnapTerminalError('Brak terminala SSH — połącz się przez ssh -t i spróbuj ponownie.') from None
    with terminal:
        if not os.isatty(terminal.fileno()):
            raise QnapTerminalError('Brak terminala do bezpiecznego wpisania hasła.')
        # The secret is only a shell variable and an anonymous pipe to Python.
        # It never enters argv, environment, a disk file, logs or visible stdout.
        script = ('set +x; IFS= read -r -s -p "$1" pcc_secret; '
                  'pcc_status=$?; if [ "$pcc_status" -ne 0 ]; then exit "$pcc_status"; fi; '
                  'printf "%s" "$pcc_secret"; unset pcc_secret')
        try:
            result = subprocess.run([*shell, '-c', script, 'pcc-hidden-read', prompt],
                stdin=terminal, stdout=subprocess.PIPE, stderr=terminal,
                env=environment, check=False)
        finally:
            terminal.write(b'\n')
        if result.returncode != 0:
            raise QnapTerminalError('Przerwano wpisywanie hasła.')
        if not result.stdout:
            raise QnapTerminalError('Nie wpisano hasła. Uruchom test ponownie i wpisz hasło konta QNAP.')
        if len(result.stdout) > 4096:
            raise QnapTerminalError('Przekroczono długość hasła — przerwano.')
        return result.stdout.decode('utf-8')
