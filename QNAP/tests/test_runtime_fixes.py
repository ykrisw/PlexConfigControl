"""Run with PCC_QNAP_SOURCE pointing at the prepared native source tree."""
import contextlib
import ctypes
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, os.environ['PCC_QNAP_SOURCE'])
from plexconfigcontrol.qnap_eventlog import LoggedPanelHistory, panel_event, flush_events
from plexconfigcontrol import qnap_restore as restore
from plexconfigcontrol.qnap_discovery import QnapPlexInstallation

class Service:
    def __init__(self,root):
        self.owner=root/'owner';self.owner.mkdir()
        self.location=self.owner/'location.json';self.mutex=threading.RLock();self.busy=False;self.api=object()
        self.folder=root/'archives';self.folder.mkdir();(self.folder/'Logs').mkdir()
        i=(self.folder/'Logs').stat();self.binding={'logs_identity':[i.st_dev,i.st_ino],'uid':os.getuid(),'gid':os.getgid()}
    def _binding(self):return self.binding,self.folder

class Events(unittest.TestCase):
    def test_photo_event_queues_before_folder_and_survives_history_clear(self):
        with tempfile.TemporaryDirectory() as folder:
            service=Service(Path(folder))
            data={'id':'a'*32,'kind':'PROFILE_PHOTO','status':'SUCCESS','action':'updated'}
            self.assertTrue(panel_event(service,data)['pending'])
            self.assertFalse(list((service.folder/'Logs').iterdir()))
            service.location.write_text('{}');flush_events(service)
            files=list((service.folder/'Logs').iterdir());self.assertEqual(len(files),1)
            self.assertEqual(json.loads(files[0].read_text())['kind'],'PROFILE_PHOTO')
            flush_events(service);self.assertEqual(list((service.folder/'Logs').iterdir()),files)
    def test_arbitrary_event_payload_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):panel_event(Service(Path(folder)),{'password':'secret'})

class Restore(unittest.TestCase):
    def run_restore(self,fail_mount=False):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);s=Service(root)
            live=root/'Plex';live.mkdir();(live/'data').write_text('original')
            work=root/'.pcc-restore-test';work.mkdir(mode=0o700)
            prepared=work/'prepared';prepared.mkdir();(prepared/'data').write_text('restored')
            s.current={'archive':'PlexConfig_new.tar.gz','kind':'RESTORE','restore':{'original':restore.identity(live),'prepared':restore.identity(prepared),'parent':restore.identity(root),'workspace_identity':restore.identity(work),'phase':'READY','prepared_digest':restore.tree_digest(prepared)}}
            s._save=lambda:None;s._progress=lambda *a:None;s._snapshot_record=lambda *a,**k:None
            log=root/'operation.log';s._open_log=lambda:log.open('w');s.clock=lambda:0
            instance=restore.QnapRestore(s)
            installation=QnapPlexInstallation('1',False,str(root/'pkg'),str(live),'pool/data',str(root),'Plex',4)
            instance.paths=lambda:(installation,live,work)
            result=[];instance.finish=lambda success,error:result.append((success,error))
            @contextlib.contextmanager
            def mounted(*args,**kwargs):
                if fail_mount:raise restore.SnapshotProbeError('PROBE_SNAPSHOT_MOUNT_FAILED')
                yield type('Source',(),{'storage_identity':'pool/data@owned'})()
            def probe_run(probe):
                outcome={'created':True,'readable':False,'cleanup_confirmed':False,'error':None,'cleanup_error':None,'id':'123'}
                try:
                    probe.inspect_data('123',set());outcome.update(readable=True,cleanup_confirmed=True)
                except Exception as error:outcome['error']=str(error)
                return outcome
            with patch.object(restore,'stopped'),patch.object(restore,'open_snapshot_data',mounted),patch.object(restore.OwnedSnapshotProbe,'run',probe_run):instance._apply()
            if fail_mount:
                self.assertFalse(result[0][0]);self.assertIn('PROBE_SNAPSHOT_MOUNT_FAILED',result[0][1])
                self.assertEqual((live/'data').read_text(),'original')
                self.assertIn('APPLY_FAILURE',log.read_text());self.assertIn('SNAPSHOT_RESULT',log.read_text())
            else:
                self.assertTrue(result[0][0],result)
                self.assertEqual((live/'data').read_text(),'restored')
                self.assertEqual((work/'previous/data').read_text(),'original')
    def test_older_glibc_uses_kernel_no_replace_without_overwriting(self):
        real=ctypes.CDLL(None,use_errno=True)
        class OldLibc:
            syscall=real.syscall
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'source').mkdir();(root/'existing').mkdir()
            fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY)
            try:
                with patch.object(restore.ctypes,'CDLL',return_value=OldLibc()):
                    with self.assertRaises(FileExistsError):restore.rename_held(fd,'source',fd,'existing')
                    self.assertTrue((root/'source').exists())
                    restore.rename_held(fd,'source',fd,'target')
                    self.assertTrue((root/'target').is_dir());self.assertFalse((root/'source').exists())
            finally:os.close(fd)
    def test_native_directory_swap_and_verification(self):self.run_restore()
    def test_mount_failure_is_explicit_and_preserves_live(self):self.run_restore(True)


class Session(unittest.TestCase):
    def test_temporary_network_failure_keeps_existing_authentication(self):
        from plexconfigcontrol import qnap_session
        from plexconfigcontrol.qnap_api import QnapApiError
        from types import SimpleNamespace
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            service=Service(Path(folder));service.auth_busy=False
            service.user=SimpleNamespace(pw_name='test-user')
            service.api=Mock(_session='test-session-123')
            service.api.snapshot_count.side_effect=QnapApiError('QNAP_LOCAL_API_UNAVAILABLE')
            api=service.api;service.discover=lambda:SimpleNamespace(volume_id=4)
            qnap_session.remember(service)
            self.assertEqual((service.owner/'qnap-session.json').stat().st_mode&0o777,0o600)
            qnap_session.tick(service)
            self.assertIs(service.api,api);self.assertIsNotNone(service.user)
            service.api.forget_session.assert_not_called()
    def test_long_local_operation_does_not_disable_session_keepalive(self):
        from plexconfigcontrol import qnap_session
        from types import SimpleNamespace
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            service=Service(Path(folder));service.auth_busy=False;service.busy=True
            service.user=SimpleNamespace(pw_name='test-user');service.api=Mock(_session='test-session-123')
            service.discover=lambda:SimpleNamespace(volume_id=4)
            qnap_session.tick(service)
            service.api.snapshot_count.assert_called_once_with(4)
            self.assertIsNotNone(service.user)
    def test_only_nas_confirmed_expiry_discards_authentication(self):
        from plexconfigcontrol import qnap_session
        from plexconfigcontrol.qnap_api import QnapApiError
        from types import SimpleNamespace
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            service=Service(Path(folder));service.auth_busy=False
            service.user=SimpleNamespace(pw_name='test-user');service.api=Mock(_session='test-session-123')
            service.discover=lambda:SimpleNamespace(volume_id=4)
            qnap_session.remember(service)
            service.api.snapshot_count.side_effect=QnapApiError('QNAP_SESSION_EXPIRED')
            qnap_session.tick(service)
            self.assertIsNone(service.api);self.assertIsNone(service.user)
            self.assertFalse((service.owner/'qnap-session.json').exists())

class Registration(unittest.TestCase):
    def test_restart_does_not_rewrite_identical_package_fields(self):
        import ast
        from unittest.mock import Mock
        source=Path(os.environ['PCC_QNAP_SOURCE'])/'deploy/qnap/qpkg/launcher.py'
        tree=ast.parse(source.read_text())
        function=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='qpkg_setting')
        runner=Mock(return_value=type('Result',(),{'stdout':'8443\n'})())
        scope={'subprocess':type('Subprocess',(),{'run':runner,'DEVNULL':-3,'PIPE':-1}),'NAME':'PCC'}
        exec(compile(ast.Module(body=[function],type_ignores=[]),str(source),'exec'),scope)
        scope['qpkg_setting']('Web_Port',8443)
        self.assertEqual(runner.call_count,1)
        self.assertEqual(runner.call_args.args[0][0],'/sbin/getcfg')

if __name__=='__main__':unittest.main()
