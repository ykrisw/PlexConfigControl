import os
from pathlib import Path
import pty
import select
import subprocess
import sys
import termios
import time
import unittest


HELPER = Path(__file__).resolve().parents[1]/'deploy/qnap/terminal_password.py'


class TerminalPasswordTests(unittest.TestCase):
    def exercise(self, password):
        master, slave = pty.openpty()
        before = termios.tcgetattr(slave)
        code = (
            'import runpy,sys; ns=runpy.run_path(sys.argv[1]); '
            'value=ns["secure_terminal_password"]("Hidden password: ",tty_path=sys.argv[2]); '
            'print("READ_OK" if value == "test-zażółć" else "WRONG_VALUE")'
        )
        process = subprocess.Popen([sys.executable, '-I', '-S', '-c', code,
            str(HELPER), os.ttyname(slave)], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        transcript = bytearray()
        try:
            deadline = time.monotonic()+5
            while b'Hidden password: ' not in transcript:
                if time.monotonic() >= deadline:
                    self.fail('Password prompt did not appear')
                if select.select([master], [], [], .1)[0]:
                    transcript.extend(os.read(master, 4096))
            self.assertFalse(termios.tcgetattr(slave)[3] & termios.ECHO)
            os.write(master, password+b'\n')
            stdout, stderr = process.communicate(timeout=5)
            while select.select([master], [], [], .05)[0]:
                transcript.extend(os.read(master, 4096))
            self.assertEqual(termios.tcgetattr(slave), before)
            if password:
                self.assertNotIn(password, bytes(transcript)+stdout+stderr)
            return process.returncode, stdout, stderr
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
            os.close(master)
            os.close(slave)

    def test_hidden_utf8_password_without_stdin_or_termios_import(self):
        code, stdout, stderr = self.exercise('test-zażółć'.encode())
        self.assertEqual(code, 0)
        self.assertEqual(stdout.strip(), b'READ_OK')
        self.assertEqual(stderr, b'')

    def test_empty_password_fails_and_restores_terminal(self):
        code, stdout, stderr = self.exercise(b'')
        self.assertNotEqual(code, 0)
        self.assertIn('Nie wpisano hasła'.encode(), stderr)

    def test_regular_file_is_rejected_without_reading_password(self):
        import runpy
        namespace = runpy.run_path(str(HELPER))
        with self.assertRaisesRegex(namespace['QnapTerminalError'], 'Brak terminala'):
            namespace['secure_terminal_password']('Password: ', tty_path='/dev/null')


if __name__ == '__main__':
    unittest.main()
