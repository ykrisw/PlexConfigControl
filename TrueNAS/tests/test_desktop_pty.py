"""Exercise the real terminal line discipline used by SSH's allocated PTY."""
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import unittest

@unittest.skipUnless(os.name == 'posix', 'Allocated POSIX SSH terminal')
class DesktopPtyTests(unittest.TestCase):
    def test_large_certificate_reply_survives_real_terminal(self):
        import pty
        import threading
        source = (Path(__file__).resolve().parents[1] / 'deploy/desktop/setup_app.py').read_text()
        self.assertIn('stty -echo -icanon min 1 time 0 && sudo -S', source)
        master, slave = pty.openpty()
        code = "import json,sys;print('READY',flush=True);data=json.loads(sys.stdin.readline());print(len(data['answer']),flush=True)"
        import shlex
        process = subprocess.Popen(['sh','-c', 'stty -echo -icanon min 1 time 0 && exec ' + shlex.quote(sys.executable) + ' -c ' + shlex.quote(code)], stdin=slave, stdout=slave, stderr=slave)
        os.close(slave)
        try:
            self.assertTrue(select.select([master], [], [], 10)[0])
            self.assertIn(b'READY', os.read(master,4096))
            payload = (json.dumps({'answer':'A' * 600000})+'\n').encode()
            def write():
                view=memoryview(payload)
                while view:
                    written=os.write(master,view[:16384]);view=view[written:]
            writer=threading.Thread(target=write,daemon=True);writer.start()
            self.assertTrue(select.select([master],[],[],20)[0])
            response=os.read(master,4096)
            self.assertIn(b'600000',response)
            writer.join(5);self.assertFalse(writer.is_alive())
            self.assertEqual(process.wait(timeout=5),0)
        finally:
            if process.poll() is None:process.kill();process.wait()
            os.close(master)
