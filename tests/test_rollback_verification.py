"""Synthetic snapshots; comparisons never invoke TrueNAS or mutate the source."""
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from plexconfigcontrol.config_writer import ConfigWriter, ConfigWriteError
from plexconfigcontrol.operations import OperationDenied, Phase
from plexconfigcontrol.rollback_verification import RollbackVerifier
from plexconfigcontrol.state import StateStore

IDENTIFIER='test/config@pcc-restore-'+'a'*32


class RollbackVerificationTests(unittest.TestCase):
    @contextmanager
    def fixture(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);target=root/'config';target.mkdir()
            snapshot=target/'.zfs'/'snapshot'/IDENTIFIER.split('@')[1];snapshot.mkdir(parents=True)
            store=StateStore(root/'state')
            with store.transaction() as operation:
                operation.kind='RESTORE';operation.phase=Phase.RUNNING;operation.snapshot_id=IDENTIFIER
            status=Mock();status.read.return_value={'state':'STOPPED'}
            info=target.stat()
            writer=ConfigWriter(target,info.st_dev,info.st_ino,status,
                                runner=Mock(return_value=SimpleNamespace(returncode=0,stdout=b'')))
            calls=[]
            @contextmanager
            def reader(identifier):
                calls.append(identifier)
                yield snapshot
            verifier=RollbackVerifier(store,reader,writer)
            # This fixture is an ordinary directory. Only the read-only filesystem
            # flag is simulated; production SnapshotReader independently checks it.
            with patch('plexconfigcontrol.config_writer.os.statvfs',return_value=SimpleNamespace(f_flag=os.ST_RDONLY)):
                yield verifier,snapshot,status,calls

    def test_exact_comparison_is_read_only_and_retains_emergency_snapshot(self):
        with self.fixture() as (verifier,snapshot,status,calls):
            self.assertTrue(verifier(IDENTIFIER))
            self.assertEqual(calls,[IDENTIFIER])
            args=verifier.writer.runner.call_args.args[0]
            for flag in ('--dry-run','--checksum','--itemize-changes','--numeric-ids','-aHAXS'):
                self.assertIn(flag,args)
            self.assertEqual(args[-2:], [str(snapshot)+'/',str(verifier.writer.target)+'/'])
            self.assertTrue(snapshot.exists())
            with verifier.store.transaction() as operation:
                self.assertEqual(operation.snapshot_id,IDENTIFIER)
                self.assertEqual(operation.phase,Phase.RUNNING)

    def test_foreign_snapshot_or_wrong_operation_never_reads_or_runs_rsync(self):
        for field,value in (('kind','BACKUP'),('phase',Phase.SUCCESS),('snapshot_id',None)):
            with self.subTest(field=field),self.fixture() as (verifier,_,_,calls):
                with verifier.store.transaction() as operation:setattr(operation,field,value)
                with self.assertRaises(OperationDenied):verifier(IDENTIFIER)
                self.assertEqual(calls,[]);verifier.writer.runner.assert_not_called()
        with self.fixture() as (verifier,_,_,calls):
            with self.assertRaises(OperationDenied):verifier('another/config@pcc-restore-'+'b'*32)
            self.assertEqual(calls,[])

    def test_reader_mismatch_and_writable_source_are_rejected(self):
        with self.fixture() as (verifier,snapshot,_,_):
            @contextmanager
            def wrong(_):yield snapshot.parent
            verifier.reader=wrong
            with self.assertRaises(OperationDenied):verifier(IDENTIFIER)
            verifier.writer.runner.assert_not_called()
        with self.fixture() as (verifier,_,_,_):
            with patch('plexconfigcontrol.config_writer.os.statvfs',return_value=SimpleNamespace(f_flag=0)):
                with self.assertRaises(ConfigWriteError):verifier(IDENTIFIER)
            verifier.writer.runner.assert_not_called()

    def test_plex_start_target_swap_source_swap_and_record_change_cannot_pass(self):
        for change in ('plex','target','source','record'):
            with self.subTest(change=change),self.fixture() as (verifier,snapshot,status,_):
                def runner(*args,**kwargs):
                    if change=='plex':status.read.return_value={'state':'RUNNING'}
                    elif change=='target':
                        verifier.writer.target.rename(verifier.writer.target.parent/'old-config')
                        verifier.writer.target.mkdir()
                    elif change=='source':
                        snapshot.rename(snapshot.parent/'old-snapshot');snapshot.mkdir()
                    else:
                        with verifier.store.transaction() as operation:operation.snapshot_id=None
                    return SimpleNamespace(returncode=0,stdout=b'')
                verifier.writer.runner=runner
                with self.assertRaises((ConfigWriteError,OperationDenied)):verifier(IDENTIFIER)

    def test_difference_or_failed_comparison_is_not_a_verified_rollback(self):
        for code,output in ((0,b'>f checksum differs'),(23,b'')):
            with self.subTest(code=code),self.fixture() as (verifier,snapshot,_,_):
                verifier.writer.runner.return_value=SimpleNamespace(returncode=code,stdout=output)
                with self.assertRaises(ConfigWriteError):verifier(IDENTIFIER)
                self.assertTrue(snapshot.exists())
                with verifier.store.transaction() as operation:self.assertEqual(operation.snapshot_id,IDENTIFIER)

    def test_snapshot_path_exception_never_allows_write(self):
        with self.fixture() as (verifier,snapshot,_,_):
            with self.assertRaises(ConfigWriteError):verifier.writer.write(snapshot)
            verifier.writer.runner.assert_not_called()

    @unittest.skipUnless(shutil.which('rsync'),'GNU rsync required')
    def test_real_checksum_and_metadata_comparison_detects_same_size_corruption(self):
        # A separate source avoids pretending an ordinary directory is a ZFS
        # snapshot. These are actual GNU rsync writes and dry-run comparisons.
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'staged';target=root/'config'
            source.mkdir();target.mkdir()
            file=source/'library.db';file.write_bytes(b'known database bytes')
            file.chmod(0o640);os.link(file,source/'library-hardlink.db')
            nested=source/'nested';nested.mkdir();(nested/'Preferences.xml').write_bytes(b'<Preferences/>')
            status=Mock();status.read.return_value={'state':'STOPPED'}
            info=target.stat();writer=ConfigWriter(target,info.st_dev,info.st_ino,status)
            writer.write(source);self.assertTrue(writer.verify(source))
            self.assertEqual((target/'library.db').stat().st_ino,(target/'library-hardlink.db').stat().st_ino)
            original=(target/'library.db').stat()
            (target/'library.db').write_bytes(b'X'*original.st_size)
            os.utime(target/'library.db',ns=(original.st_atime_ns,original.st_mtime_ns))
            with self.assertRaises(ConfigWriteError):writer.verify(source)
            writer.write(source);(target/'Preferences-unexpected.xml').write_text('extra')
            with self.assertRaises(ConfigWriteError):writer.verify(source)
            (target/'Preferences-unexpected.xml').unlink();(target/'library.db').chmod(0o600)
            with self.assertRaises(ConfigWriteError):writer.verify(source)

    @unittest.skipUnless(shutil.which('rsync'),'GNU rsync required')
    def test_real_rollback_comparison_ignores_only_virtual_zfs_control_directory(self):
        with self.fixture() as (verifier,snapshot,_,_):
            original=snapshot/'Preferences.xml';original.write_bytes(b'original config')
            shutil.copy2(original,verifier.writer.target/'Preferences.xml')
            # A real snapshot preserves root metadata. Simulate that explicitly.
            shutil.copystat(verifier.writer.target,snapshot)
            verifier.writer.runner=subprocess.run
            self.assertTrue(verifier(IDENTIFIER))
            live=verifier.writer.target/'Preferences.xml';info=live.stat()
            live.write_bytes(b'X'*info.st_size)
            os.utime(live,ns=(info.st_atime_ns,info.st_mtime_ns))
            with self.assertRaises(ConfigWriteError):verifier(IDENTIFIER)
            self.assertTrue(snapshot.exists())

    @unittest.skipUnless(shutil.which('rsync'),'GNU rsync required')
    def test_restore_failure_only_reports_verified_rollback_after_real_comparison(self):
        import io
        import tarfile
        from test_restore import StoppedAPI, NAME
        from plexconfigcontrol.archives import REQUIRED
        from plexconfigcontrol.history import History
        from plexconfigcontrol.progress import Progress
        from plexconfigcontrol.restore import Restore
        from plexconfigcontrol.restore_validation import RestoreValidation
        for corrupt in (False,True):
            with self.subTest(corrupt=corrupt),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);target=root/'config';target.mkdir()
                original=target/'original.db';original.write_bytes(b'known original bytes')
                destination=root/'Plex Config';(destination/'Logs').mkdir(parents=True)
                with tarfile.open(destination/NAME,'w:gz') as archive:
                    for name in REQUIRED:
                        entry=tarfile.TarInfo(name);entry.size=4
                        entry.uid=os.getuid();entry.gid=os.getgid()
                        archive.addfile(entry,io.BytesIO(b'test'))
                store=StateStore(root/'state');history=History(root/'state');progress=Progress(root/'state')
                RestoreValidation(destination,root/'state',store,history).validate(NAME)
                class Host(StoppedAPI):
                    def call(self,method,*args):
                        result=super().call(method,*args)
                        if method=='pool.snapshot.create':
                            source=target/'.zfs'/'snapshot'/args[0]['name'];source.mkdir(parents=True)
                            shutil.copy2(original,source/original.name);shutil.copystat(target,source)
                        elif method=='pool.snapshot.rollback':
                            source=target/'.zfs'/'snapshot'/args[0].split('@')[1]
                            shutil.copy2(source/original.name,original);shutil.copystat(source,target)
                            if corrupt:original.write_bytes(b'bad rollback result')
                        return result
                api=Host()
                status=Mock();status.read.return_value={'state':'STOPPED'}
                info=target.stat();writer=ConfigWriter(target,info.st_dev,info.st_ino,status)
                @contextmanager
                def reader(identifier):
                    self.assertIn(identifier,api.present)
                    yield target/'.zfs'/'snapshot'/identifier.split('@')[1]
                verifier=RollbackVerifier(store,reader,writer)
                def failed_write(_):
                    original.write_bytes(b'partially restored')
                    raise RuntimeError('injected Restore failure')
                restore=Restore(api,store,history,progress,root/'state',destination,'test/config',
                                lambda _:None,failed_write,lambda _:True,verifier)
                with patch('plexconfigcontrol.config_writer.os.statvfs',return_value=SimpleNamespace(f_flag=os.ST_RDONLY)):
                    with self.assertRaises(RuntimeError):restore.run(NAME,'RESTORE')
                log=next((destination/'Logs').glob('Restore_*.log')).read_text()
                self.assertIn('Rollback could not be verified.' if corrupt else 'Rollback verified.',log)
                with store.transaction() as operation:
                    self.assertEqual(operation.phase,Phase.RECOVERY_REQUIRED)
                    self.assertIn(operation.snapshot_id,api.present)
                self.assertEqual(history.list()[0]['status'],'FAILED')
                self.assertFalse(any(method in ('app.start','app.stop','pool.snapshot.delete') for method,_ in api.calls))
