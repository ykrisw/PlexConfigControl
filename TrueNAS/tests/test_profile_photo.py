import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from plexconfigcontrol.profile_photo import ProfilePhoto,InvalidPhoto,PhotoChanged,MAX_UPLOAD


def picture(color='red',format='PNG'):
    image=Image.new('RGB',(32,24),color);output=io.BytesIO()
    if format=='JPEG':
        exif=image.getexif();exif[270]='private photo metadata';exif[274]=6
        image.save(output,format=format,exif=exif)
    else:image.save(output,format=format)
    return output.getvalue()


class PhotoTests(unittest.TestCase):
    def test_normalized_photo_strips_metadata_persists_and_removes_only_its_file(self):
        with tempfile.TemporaryDirectory() as d:
            state=Path(d)/'ixVolume';permanent=Path(d)/'Plex Config'/'Logs'/'Backup.log'
            permanent.parent.mkdir(parents=True);permanent.write_text('keep')
            photo=ProfilePhoto(state);saved=photo.upload(picture(format='JPEG'))
            self.assertTrue(saved['present']);self.assertEqual(len(saved['revision']),64)
            with Image.open(io.BytesIO(photo.read())) as image:
                self.assertEqual(image.size,(512,512));self.assertEqual(image.format,'PNG')
                self.assertFalse(image.getexif());self.assertNotIn('exif',image.info)
            self.assertEqual(photo.path.stat().st_mode & 0o077,0)
            reopened=ProfilePhoto(state);self.assertEqual(reopened.status(),saved)
            reopened.remove(confirmed=True,expected_revision=saved['revision'])
            self.assertIsNone(reopened.read());self.assertEqual(permanent.read_text(),'keep')
            self.assertFalse(photo.pending.exists())

    def test_invalid_oversized_and_excessive_pixel_uploads_preserve_previous_photo(self):
        with tempfile.TemporaryDirectory() as d:
            photo=ProfilePhoto(d);photo.upload(picture());before=photo.read()
            for data in (b'',b'<svg><script>bad</script></svg>',b'x'*(MAX_UPLOAD+1)):
                with self.assertRaises(InvalidPhoto):photo.upload(data)
            with patch('plexconfigcontrol.profile_photo.MAX_PIXELS',10):
                with self.assertRaises(InvalidPhoto):photo.upload(picture())
            self.assertEqual(photo.read(),before);self.assertFalse(photo.pending.exists())

    def test_failed_publication_cleans_pending_file_and_keeps_old_photo(self):
        with tempfile.TemporaryDirectory() as d:
            photo=ProfilePhoto(d);photo.upload(picture());before=photo.read()
            with patch('plexconfigcontrol.profile_photo.os.replace',side_effect=OSError('disk problem')):
                with self.assertRaises(OSError):photo.upload(picture('blue'))
            self.assertEqual(photo.read(),before);self.assertFalse(photo.pending.exists())

    def test_restart_removes_only_the_exact_owned_pending_file(self):
        with tempfile.TemporaryDirectory() as d:
            photo=ProfilePhoto(d);saved=photo.upload(picture())
            photo.pending.write_bytes(b'interrupted write')
            unrelated=Path(d)/'unrelated.pending';unrelated.write_bytes(b'keep')
            reopened=ProfilePhoto(d)
            self.assertFalse(photo.pending.exists());self.assertEqual(reopened.status(),saved)
            self.assertEqual(unrelated.read_bytes(),b'keep')

    def test_symlink_storage_never_follows_or_overwrites_external_file(self):
        with tempfile.TemporaryDirectory() as d:
            outside=Path(d)/'outside';outside.write_bytes(b'precious')
            photo=ProfilePhoto(Path(d)/'state');photo.path.symlink_to(outside)
            with self.assertRaises(OSError):photo.read()
            with self.assertRaises(OSError):photo.upload(picture())
            with self.assertRaises(OSError):photo.remove(confirmed=True)
            self.assertEqual(outside.read_bytes(),b'precious');self.assertFalse(photo.pending.exists())

    def test_old_removal_confirmation_cannot_delete_a_replaced_photo(self):
        with tempfile.TemporaryDirectory() as d:
            photo=ProfilePhoto(d);first=photo.upload(picture());second=photo.upload(picture('blue'))
            with self.assertRaises(PhotoChanged):photo.remove(confirmed=True,expected_revision=first['revision'])
            self.assertEqual(photo.status(),second)
            with self.assertRaises(ValueError):photo.remove()
