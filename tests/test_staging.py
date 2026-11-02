import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from plexconfigcontrol.archives import REQUIRED,validate_archive
from plexconfigcontrol.staging import stage_archive,StagingError

class StagingTests(unittest.TestCase):
    def make(self,path):
        with tarfile.open(path,'w:gz') as archive:
            for name in REQUIRED:
                member=tarfile.TarInfo(name); member.size=4
                archive.addfile(member,io.BytesIO(b'test'))
    def test_real_extraction_and_cleanup_after_exception(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); state=root/'state'; state.mkdir(); archive=root/'a.tar.gz'; self.make(archive)
            digest=validate_archive(archive).sha256
            with self.assertRaises(RuntimeError):
                with stage_archive(archive,state,digest) as config:
                    self.assertTrue((config/'Library/Application Support/Plex Media Server/Preferences.xml').is_file())
                    raise RuntimeError('later validation failed')
            self.assertEqual(list(state.iterdir()),[])
            self.assertEqual(validate_archive(archive).sha256,digest)
    def test_changed_archive_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); state=root/'state'; state.mkdir(); archive=root/'a.tar.gz'; self.make(archive)
            def forbidden(*args,**kwargs): raise AssertionError('Extraction must not run')
            with self.assertRaises(StagingError):
                with stage_archive(archive,state,'0'*64,runner=forbidden): pass
            self.assertEqual(list(state.iterdir()),[])
