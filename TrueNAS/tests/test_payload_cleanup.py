import os
from pathlib import Path
import tempfile
import unittest
from deploy.build_self_extracting import LAUNCHER

class PayloadCleanupTests(unittest.TestCase):
    def test_stale_payload_only_and_preserve_live_unknown_and_symlink(self):
        scope={};exec(LAUNCHER,scope)
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);proc=base/'proc';proc.mkdir()
            def payload(name):
                p=base/name;p.mkdir(mode=0o700)
                root=p/'PlexConfigControl_RC_Install';root.mkdir();(root/'INSTALUJ.sh').write_text('test')
                return p
            stale=payload('pcc-rc.stale');live=payload('pcc-rc.live')
            unknown=payload('pcc-rc.unknown');(unknown/'settings.json').write_text('preserve')
            target=base/'archives';target.mkdir();(target/'backup.tar.gz').write_text('archive')
            linked=payload('pcc-rc.linked');(linked/'data').symlink_to(target,target_is_directory=True)
            process=proc/'123';process.mkdir();(process/'cmdline').write_bytes(str(live/'PlexConfigControl_RC_Install/INSTALUJ.sh').encode());(process/'cwd').symlink_to(base,target_is_directory=True)
            self.assertEqual(scope['cleanup_previous_payloads'](base,proc),1)
            self.assertFalse(stale.exists())
            for p in (live,unknown,linked,target/'backup.tar.gz'):self.assertTrue(p.exists())
    def test_live_payload_lock_is_preserved(self):
        import fcntl
        scope={};exec(LAUNCHER,scope)
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);proc=base/'proc';proc.mkdir()
            work=base/'pcc-rc.active';work.mkdir(mode=0o700)
            package=work/'PlexConfigControl_RC_Install';package.mkdir();(package/'INSTALUJ.sh').touch()
            with (work/'.pcc-active').open('w') as f:
                fcntl.flock(f,fcntl.LOCK_EX)
                self.assertEqual(scope['cleanup_previous_payloads'](base,proc),0)
                self.assertTrue(work.exists())
