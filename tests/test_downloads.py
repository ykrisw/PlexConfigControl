import io
import tempfile
import unittest
import zipfile
from plexconfigcontrol.history import History
from plexconfigcontrol.downloads import history_logs, MissingHistoryEvent

class DownloadTests(unittest.TestCase):
    def test_single_and_multiple_logs_no_disk_artifacts(self):
        with tempfile.TemporaryDirectory() as d:
            from pathlib import Path
            h=History(d); a=h.add('BACKUP','SUCCESS','Polski: zakończono'); b=h.add('RESTORE','FAILED','failed')
            before=set(Path(d).iterdir())
            name,mime,data=history_logs(h,[a])
            self.assertEqual(name,f'Event_{a}.log'); self.assertIn('zakończono',data.decode())
            name,mime,data=history_logs(h,[a,b])
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                self.assertEqual(z.namelist(),[f'Event_{a}.log',f'Event_{b}.log'])
            self.assertEqual(set(Path(d).iterdir()),before)
            h.clear([a])
            with self.assertRaises(MissingHistoryEvent): history_logs(h,[a,b])
    def test_selection_and_size_limits(self):
        with tempfile.TemporaryDirectory() as d:
            h=History(d); a=h.add('BACKUP','SUCCESS','12345')
            for ids in ([],[a,a],['../Logs'],[True]):
                with self.assertRaises(ValueError): history_logs(h,ids)
            with self.assertRaises(ValueError): history_logs(h,[a],max_bytes=4)
