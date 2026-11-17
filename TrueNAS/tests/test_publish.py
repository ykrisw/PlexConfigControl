import hashlib
import tempfile
import unittest
from pathlib import Path
from plexconfigcontrol.publish import publish_new, PublishError

NAME='TrueNASPlexConfig_2026.11.03_04.15.35.tar.gz'
class PublishTests(unittest.TestCase):
    def test_new_publish_and_collision_preserve_existing(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); source=root/'source'; source.write_bytes(b'verified')
            dest=root/'dest'; dest.mkdir(); intents=[]
            digest=hashlib.sha256(b'verified').hexdigest()
            publish_new(source,dest,NAME,digest,intents.append)
            self.assertEqual((dest/NAME).read_bytes(),b'verified')
            self.assertEqual(len(intents),1)
            with self.assertRaises(FileExistsError): publish_new(source,dest,NAME,digest,intents.append)
            self.assertEqual([p.name for p in dest.iterdir()],[NAME])
    def test_digest_failure_and_failed_intent_leave_no_files(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); source=root/'source'; source.write_bytes(b'changed'); dest=root/'dest'; dest.mkdir()
            with self.assertRaises(PublishError): publish_new(source,dest,NAME,'0'*64,lambda name:None)
            self.assertEqual(list(dest.iterdir()),[])
            def fail(name): raise RuntimeError('state save failed')
            with self.assertRaises(RuntimeError): publish_new(source,dest,NAME,'0'*64,fail)
            self.assertEqual(list(dest.iterdir()),[])
