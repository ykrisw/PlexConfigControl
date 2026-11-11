"""Real tar round trips from a native Plex data tree; no NAS calls."""
import tarfile
import tempfile
import unittest
from pathlib import Path

from plexconfigcontrol.archives import BASE, validate_archive
from plexconfigcontrol.backup_archive import BackupArchiveError, compare_contents, create_archive
from plexconfigcontrol.staging import stage_archive


class QnapArchiveTests(unittest.TestCase):
    def source(self, parent):
        source = parent/'native-plex-data'
        databases = source/'Plug-in Support'/'Databases'
        databases.mkdir(parents=True)
        (source/'Preferences.xml').write_text('<Preferences/>')
        (databases/'com.plexapp.plugins.library.db').write_bytes(b'test library contents')
        (databases/'com.plexapp.plugins.library.blobs.db').write_bytes(b'test blobs contents')
        (source/'Metadata').mkdir()
        (source/'Metadata'/'example').write_bytes(b'artwork contents')
        return source

    def test_native_data_round_trips_through_common_archive_and_staging_format(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source = self.source(parent)
            output = parent/'portable.tar.gz'
            result = create_archive(source, output, source_layout='plex-data')
            self.assertEqual(validate_archive(output).sha256, result.sha256)
            state = parent/'state'
            state.mkdir()
            with stage_archive(output, state, result.sha256) as staged:
                canonical = staged/'Library'/'Application Support'/'Plex Media Server'
                self.assertEqual((canonical/'Metadata'/'example').read_bytes(), b'artwork contents')
                self.assertEqual((canonical/'Preferences.xml').read_bytes(), (source/'Preferences.xml').read_bytes())
            self.assertEqual(list(state.iterdir()), [])
            with tarfile.open(output, 'r:gz') as archive:
                self.assertTrue(all(member.name == BASE.rstrip('/') or member.name.startswith(BASE)
                                    for member in archive))

    def test_changed_source_fails_byte_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source = self.source(parent)
            output = parent/'portable.tar.gz'
            create_archive(source, output, source_layout='plex-data')
            (source/'Metadata'/'example').write_bytes(b'changed contents')
            with self.assertRaises(BackupArchiveError):
                compare_contents(source, output, source_layout='plex-data')

    def test_unsafe_source_link_is_rejected_and_temporary_archive_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source = self.source(parent)
            external = parent/'external'
            external.write_bytes(b'not Plex data')
            (source/'linked').symlink_to(external)
            output = parent/'portable.tar.gz'
            with self.assertRaises(ValueError):
                create_archive(source, output, source_layout='plex-data')
            self.assertFalse(output.exists())

    def test_arbitrary_archive_prefix_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            output = parent/'portable.tar.gz'
            with self.assertRaises(BackupArchiveError):
                create_archive(parent, output, source_layout='../elsewhere')
            self.assertFalse(output.exists())
