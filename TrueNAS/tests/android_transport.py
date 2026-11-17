"""Local HTTPS transport for an already-validated disposable CI emulator."""
from contextlib import contextmanager


@contextmanager
def fixture_tunnel(adb, port):
    """Forward only the fixture port; never replace an existing ADB mapping.

    The caller supplies the serial-bound ADB function after the CI/emulator
    identity checks. This changes test transport, not application TLS or retries.
    """
    if not isinstance(port, str) or not port.isascii() or not port.isdecimal():
        raise ValueError('Fixture port must be decimal')
    if not 1024 <= int(port) <= 65535:
        raise ValueError('Fixture port must be an unprivileged TCP port')
    socket = 'tcp:' + port
    adb('reverse', '--no-rebind', socket, socket)
    try:
        yield 'https://127.0.0.1:' + port
    finally:
        adb('reverse', '--remove', socket)
