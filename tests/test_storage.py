import os
import tempfile
import unittest
from pathlib import Path
from plexconfigcontrol.storage import RenameRequired, create_destination


class StorageTests(unittest.TestCase):
    def test_existing_folder_and_permissions_untouched_then_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'Plex Config'
            root.mkdir(mode=0o750)
            file=root/'precious.tar.gz'; file.write_bytes(b'keep')
            before=root.stat()
            with self.assertRaises(RenameRequired): create_destination(directory)
            self.assertEqual(root.stat().st_mode,before.st_mode)
            self.assertEqual(root.stat().st_ino,before.st_ino)
            self.assertEqual(file.read_bytes(),b'keep')
            self.assertFalse((root/'Logs').exists())
            root.rename(Path(directory)/'Old Plex Config')
            result=create_destination(directory)
            self.assertTrue(result.logs.is_dir())
            self.assertEqual(result.inode,result.root.stat().st_ino)
            self.assertEqual((Path(directory)/'Old Plex Config'/file.name).read_bytes(),b'keep')

    def test_existing_symlink_rejected_without_writing_target(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'other'; target.mkdir()
            (Path(directory)/'Plex Config').symlink_to(target, target_is_directory=True)
            with self.assertRaises(RenameRequired): create_destination(directory)
            self.assertEqual(list(target.iterdir()),[])

    def test_missing_parent_not_created(self):
        with tempfile.TemporaryDirectory() as directory:
            parent=Path(directory)/'missing'
            with self.assertRaises(FileNotFoundError): create_destination(parent)
            self.assertFalse(parent.exists())

    def test_preflight_is_read_only_and_does_not_claim_write_permission(self):
        from plexconfigcontrol.storage import inspect_destination
        with tempfile.TemporaryDirectory() as directory:
            parent=Path(directory);before=parent.stat()
            self.assertEqual(inspect_destination(parent),{'status':'NAME_AVAILABLE','permission_check':'NOT_TESTED'})
            self.assertEqual(list(parent.iterdir()),[])
            self.assertEqual((parent.stat().st_mode,parent.stat().st_uid,parent.stat().st_gid),
                             (before.st_mode,before.st_uid,before.st_gid))
            file=parent/'Plex Config';file.write_bytes(b'existing user file')
            self.assertEqual(inspect_destination(parent)['status'],'RENAME_REQUIRED')
            with self.assertRaises(RenameRequired):create_destination(parent)
            self.assertEqual(file.read_bytes(),b'existing user file')

    def test_ancestor_symlink_is_rejected_without_touching_target(self):
        from plexconfigcontrol.storage import inspect_destination
        with tempfile.TemporaryDirectory() as directory:
            parent=Path(directory);real=parent/'real';real.mkdir();(real/'selected').mkdir()
            link=parent/'alias';link.symlink_to(real,target_is_directory=True)
            for action in (inspect_destination,create_destination):
                with self.assertRaises(OSError):action(link/'selected')
            self.assertEqual(list((real/'selected').iterdir()),[])

    def test_unsafe_and_protected_paths_create_nothing(self):
        from plexconfigcontrol.storage import inspect_destination, UnsafeDestination
        for invalid in ('relative', '/', '//tmp/path', '/tmp/../wrong', '/tmp/invalid\0',None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(UnsafeDestination):inspect_destination(invalid)
        with tempfile.TemporaryDirectory() as directory:
            parent=Path(directory);source=parent/'live-config';source.mkdir()
            for forbidden in (source,source/'Plex Config',parent):
                with self.subTest(forbidden=forbidden):
                    with self.assertRaises(UnsafeDestination):create_destination(source,forbidden_paths=(forbidden,))
            self.assertEqual(list(source.iterdir()),[])
            sibling=parent/'other-private-state';sibling.mkdir()
            result=create_destination(parent,forbidden_paths=(sibling,))
            self.assertTrue(result.logs.is_dir())

    def test_creation_honors_umask_without_chmod_chown_or_global_umask_changes(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            saved=os.umask(0o027)
            try:
                with patch('plexconfigcontrol.storage.os.chmod',side_effect=AssertionError('No chmod')),\
                     patch('plexconfigcontrol.storage.os.chown',side_effect=AssertionError('No chown')),\
                     patch('plexconfigcontrol.storage.os.umask',side_effect=AssertionError('No process umask changes')):
                    result=create_destination(directory)
                self.assertEqual(result.root.stat().st_mode & 0o777,0o750)
                self.assertEqual(result.logs.stat().st_mode & 0o777,0o750)
            finally:os.umask(saved)

    def test_creation_fsync_failure_keeps_user_data_and_reports_incomplete_setup(self):
        from unittest.mock import patch
        from plexconfigcontrol.storage import SetupIncomplete
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'Plex Config'
            def failed_sync(_):
                (root/'copied-by-user.txt').write_bytes(b'keep')
                raise OSError('directory fsync failed')
            with patch('plexconfigcontrol.storage.os.fsync',side_effect=failed_sync):
                with self.assertRaises(SetupIncomplete):create_destination(directory)
            self.assertEqual((root/'copied-by-user.txt').read_bytes(),b'keep')
            with self.assertRaises(RenameRequired):create_destination(directory)

    def test_logs_collision_during_setup_never_edits_or_removes_existing_contents(self):
        from unittest.mock import patch
        from plexconfigcontrol.storage import SetupIncomplete
        with tempfile.TemporaryDirectory() as directory:
            mkdir=os.mkdir;root=Path(directory)/'Plex Config'
            def collision(name,*args,**kwargs):
                if name=='Logs':
                    mkdir(name,*args,**kwargs)
                    (root/'Logs'/'user.log').write_bytes(b'permanent')
                    raise FileExistsError('concurrent directory creation')
                return mkdir(name,*args,**kwargs)
            with patch('plexconfigcontrol.storage.os.mkdir',side_effect=collision):
                with self.assertRaises(SetupIncomplete):create_destination(directory)
            self.assertEqual((root/'Logs'/'user.log').read_bytes(),b'permanent')

    def test_observed_root_replacement_during_setup_fails_without_touching_replacement(self):
        from unittest.mock import patch
        from plexconfigcontrol.storage import SetupIncomplete
        with tempfile.TemporaryDirectory() as directory:
            parent=Path(directory);mkdir=os.mkdir
            def replace(name,*args,**kwargs):
                result=mkdir(name,*args,**kwargs)
                if name=='Logs':
                    (parent/'Plex Config').rename(parent/'Saved Plex Config')
                    (parent/'Plex Config').mkdir()
                    (parent/'Plex Config'/'external.txt').write_text('keep')
                return result
            with patch('plexconfigcontrol.storage.os.mkdir',side_effect=replace):
                with self.assertRaises(SetupIncomplete):create_destination(parent)
            self.assertTrue((parent/'Saved Plex Config'/'Logs').is_dir())
            self.assertEqual((parent/'Plex Config'/'external.txt').read_text(),'keep')
            self.assertFalse((parent/'Plex Config'/'Logs').exists())

    def test_observed_parent_replacement_cannot_return_an_unrelated_path(self):
        from unittest.mock import patch
        from plexconfigcontrol.storage import SetupIncomplete
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);parent=root/'selected';parent.mkdir();mkdir=os.mkdir
            def replace(name,*args,**kwargs):
                result=mkdir(name,*args,**kwargs)
                if name=='Logs':
                    parent.rename(root/'moved');parent.mkdir()
                return result
            with patch('plexconfigcontrol.storage.os.mkdir',side_effect=replace):
                with self.assertRaises(SetupIncomplete):create_destination(parent)
            self.assertTrue((root/'moved'/'Plex Config'/'Logs').is_dir())
            self.assertEqual(list(parent.iterdir()),[])

    def test_runtime_verification_detects_replaced_root_or_logs_without_recreating_them(self):
        from plexconfigcontrol.storage import verify_destination,DestinationChanged
        for logs_only in (False,True):
            with self.subTest(logs_only=logs_only),tempfile.TemporaryDirectory() as directory:
                result=create_destination(directory);self.assertTrue(verify_destination(result))
                path=result.logs if logs_only else result.root
                path.rename(path.with_name(path.name+'-moved'));path.mkdir()
                with self.assertRaises(DestinationChanged):verify_destination(result)
                self.assertEqual(list(path.iterdir()),[])

    def test_runtime_verification_rejects_missing_or_symbolic_logs(self):
        from plexconfigcontrol.storage import verify_destination
        with tempfile.TemporaryDirectory() as directory:
            result=create_destination(directory);result.logs.rmdir()
            with self.assertRaises(FileNotFoundError):verify_destination(result)
            self.assertFalse(result.logs.exists())
            outside=Path(directory)/'outside';outside.mkdir();result.logs.symlink_to(outside,target_is_directory=True)
            with self.assertRaises(OSError):verify_destination(result)
            self.assertEqual(list(outside.iterdir()),[])


    def test_setup_errors_are_localized_without_exposing_raw_paths_or_errors(self):
        from plexconfigcontrol.storage import (describe_setup_error,UnsafeDestination,
            SetupIncomplete,DestinationChanged)
        cases=[(RenameRequired('secret'),'RENAME_REQUIRED'),(UnsafeDestination('secret'),'UNSAFE_DESTINATION'),
               (SetupIncomplete(5,'secret'),'SETUP_INCOMPLETE'),(DestinationChanged('secret'),'DESTINATION_CHANGED'),
               (PermissionError('secret'),'ACCESS_REQUIRED'),(FileNotFoundError('/private/secret'),'PARENT_UNAVAILABLE'),
               (OSError('private secret'),'SETUP_FAILED')]
        for error,code in cases:
            with self.subTest(code=code):
                en=describe_setup_error(error,'en');pl=describe_setup_error(error,'pl')
                self.assertEqual(en['code'],code);self.assertEqual(pl['code'],code)
                self.assertNotEqual(en['message'],pl['message'])
                self.assertNotIn('secret',en['message']+pl['message'])
