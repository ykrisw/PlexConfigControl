import tempfile
import unittest
from pathlib import Path
from plexconfigcontrol.archive_store import ArchiveStore, ArchiveChanged
from plexconfigcontrol.locking import operation_lock, OperationBusy

A='TrueNASPlexConfig_2026.11.03_04.15.35.tar.gz'
B='TrueNASPlexConfig_2026.11.04_04.15.35.tar.gz'
class ArchiveStoreTests(unittest.TestCase):
    def test_delete_only_selected_preserves_log_and_foreign_files(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); backup=root/'backup'; backup.mkdir()
            (backup/A).write_bytes(b'archive'); (backup/B).write_bytes(b'other')
            (backup/'Logs').mkdir(); log=backup/'Logs'/'Backup.log'; log.write_text('keep')
            (backup/'notes.txt').write_text('keep')
            store=ArchiveStore(backup,root/'state'); selected=[x for x in store.list() if x.name==A]
            with self.assertRaises(ValueError): store.delete(selected)
            store.delete(selected,True)
            self.assertFalse((backup/A).exists()); self.assertTrue((backup/B).exists())
            self.assertEqual(log.read_text(),'keep'); self.assertTrue((backup/'notes.txt').exists())

    def test_changed_archive_and_active_operation_block_deletion(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); backup=root/'backup'; backup.mkdir(); (backup/A).write_bytes(b'old')
            store=ArchiveStore(backup,root/'state'); selected=store.list()
            with operation_lock(root/'state'):
                with self.assertRaises(OperationBusy): store.delete(selected,True)
            (backup/A).write_bytes(b'changed contents')
            with self.assertRaises(ArchiveChanged): store.delete(selected,True)
            self.assertTrue((backup/A).exists())

    def test_symlink_not_listed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); target=root/'outside'; target.write_text('keep')
            backup=root/'backup'; backup.mkdir(); (backup/A).symlink_to(target)
            self.assertEqual(ArchiveStore(backup,root/'state').list(),[])

    def test_lists_by_archive_timestamp_across_prefixes_and_copies(self):
        import os

        names = [
            'Zulu_2026.11.03_04.15.35.tar.gz',
            'Alpha_2026.11.04_12.00.00.tar.gz',
            'Middle_2026.11.04_09.00.00.tar.gz',
        ]
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            backup = root / 'backup'
            backup.mkdir()
            for index, name in enumerate(names):
                path = backup / name
                path.touch()
                # The oldest backup was copied last.
                os.utime(path, (100 - index, 100 - index))
            store = ArchiveStore(backup, root / 'state')
            self.assertEqual([entry.name for entry in store.list()], [names[1], names[2], names[0]])

    def test_lists_gzipped_import_with_a_renamed_unicode_filename(self):
        import gzip

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backup = root / 'backup'
            backup.mkdir()
            name = 'Kopia Plex przed zmianą.tar.gz'
            (backup / name).write_bytes(gzip.compress(b'archive'))
            (backup / 'losowy plik.tar.gz').write_bytes(b'not gzip')
            self.assertEqual([item.name for item in ArchiveStore(backup, root / 'state').list()], [name])
