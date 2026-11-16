"""Hidden terminal password input without Python's optional termios module."""


class QnapTerminalError(RuntimeError):
    pass


def secure_terminal_password(prompt, *, tty_path='/dev/tty'):
    import os
    import re
    import subprocess
    from pathlib import Path

    # QNAP Python can lack working termios support. Never use getpass's echoed
    # stdin fallback, an environment variable, argv, or a temporary password file.
    stty = next((str(path) for path in (Path('/bin/stty'), Path('/usr/bin/stty'))
                 if path.is_file() and os.access(path, os.X_OK)), None)
    if stty is None:
        raise QnapTerminalError('Brak narzędzia do ukrycia hasła — przerwano przed logowaniem.')
    try:
        terminal = open(tty_path, 'r+b', buffering=0)
    except OSError:
        raise QnapTerminalError('Brak terminala SSH — połącz się przez ssh -t i spróbuj ponownie.') from None
    with terminal:
        if not os.isatty(terminal.fileno()):
            raise QnapTerminalError('Brak terminala do bezpiecznego wpisania hasła.')

        def control(*arguments):
            return subprocess.run([stty, *arguments], stdin=terminal,
                                  capture_output=True, timeout=5, check=False)

        saved = control('-g')
        state = saved.stdout.strip()
        if (saved.returncode != 0 or not state or len(state) > 4096
                or not re.fullmatch(rb'[A-Za-z0-9:;= -]+', state)):
            raise QnapTerminalError('Nie można odczytać ustawień terminala — przerwano.')
        value = bytearray()
        try:
            if control('-echo', 'icanon').returncode != 0:
                raise QnapTerminalError('Nie można ukryć hasła — przerwano przed jego wpisaniem.')
            terminal.write(prompt.encode('utf-8'))
            while True:
                character = terminal.read(1)
                if not character:
                    raise QnapTerminalError('Przerwano wpisywanie hasła.')
                if character in (b'\n', b'\r'):
                    break
                value.extend(character)
                if len(value) > 4096:
                    raise QnapTerminalError('Przekroczono długość hasła — przerwano.')
            if not value:
                raise QnapTerminalError('Nie wpisano hasła. Uruchom test ponownie i wpisz hasło konta QNAP.')
            return value.decode('utf-8')
        finally:
            try:
                restored = control(state.decode('ascii'))
                if restored.returncode != 0:
                    raise QnapTerminalError('Nie przywrócono terminala. Wpisz w Shell: stty echo')
            finally:
                terminal.write(b'\n')
                for index in range(len(value)):
                    value[index] = 0
