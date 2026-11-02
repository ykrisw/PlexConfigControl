import tempfile
import unittest
from pathlib import Path
from plexconfigcontrol.connection_check import read_secret,probe

class ProbeTests(unittest.TestCase):
    def test_secret_permission_and_symlink_checks(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'key'; p.write_text('secret-value\n'); p.chmod(0o600)
            self.assertEqual(read_secret(p),'secret-value')
            p.chmod(0o644)
            with self.assertRaises(ValueError): read_secret(p)
            p.chmod(0o600); link=Path(d)/'link'; link.symlink_to(p)
            with self.assertRaises(OSError): read_secret(link)
    def test_probe_only_reads_plex_and_does_not_return_credentials(self):
        calls=[]
        class Client:
            def call(self,method,*args):
                calls.append(method)
                return [{'name':'plex','state':'RUNNING','version':'1.3.24','secret':'never expose'}]
        result=probe(Client())
        self.assertEqual(calls,['app.query'])
        self.assertTrue(result['connected']); self.assertNotIn('secret',result)
