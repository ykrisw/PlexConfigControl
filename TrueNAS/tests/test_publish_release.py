import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('publish_release', ROOT/'deploy/publish_release.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PublishTests(unittest.TestCase):
    def test_draft_assets_are_read_through_release_view_and_wait_for_both(self):
        calls = []
        def fake(*args, **kwargs):
            calls.append(args)
            if args == ('release','view','v1.6','--json','assets'):
                return json.dumps({'assets':[{'name':'PlexConfigControl_QuTShero_x86-64v1.6.qpkg'}]})
            if args[0] == 'api':
                raise AssertionError('A draft must not be read through the published tag endpoint')
            return ''
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'PlexConfigControl_QuTShero_x86-64v1.6.qpkg').write_bytes(b'verified-fixture')
            with patch.dict(module.os.environ,GH_REPO='owner/repo'),patch.object(module,'gh',fake):
                module.publish(folder)
        self.assertFalse(any(call[:2] == ('release','edit') for call in calls))

    def test_release_is_finalized_only_when_both_packages_are_present(self):
        calls = []
        def fake(*args, **kwargs):
            calls.append(args)
            if args == ('release','view','v1.6','--json','assets'):
                return json.dumps({'assets':[{'name':name} for name in module.NAMES]})
            if args[0] == 'api':
                raise subprocess.CalledProcessError(1,args)
            return ''
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'PlexConfigControl_TrueNAS_x86-64v1.6.zip').write_bytes(b'verified-fixture')
            with patch.dict(module.os.environ,GH_REPO='owner/repo'),patch.object(module,'gh',fake):
                module.publish(folder)
        self.assertTrue(any(call[:4] == ('release','edit','v1.6','--draft=false') for call in calls))
