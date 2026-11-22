import json
import unittest
from unittest.mock import patch
from plexconfigcontrol import image_cleanup as cleanup

class ImageCleanupTests(unittest.TestCase):
    def test_only_unused_pcc_images_removed_and_latest_and_other_apps_kept(self):
        current='sha256:'+'a'*64;old='sha256:'+'b'*64;used='sha256:'+'c'*64
        rows=[{'Repository':repo,'Tag':tag,'ID':identity} for repo,tag,identity in
              [('plexconfigcontrol','latest',current),('plexconfigcontrol-worker','old',old),
               ('plexconfigcontrol','used',used),('plexinc/pms-docker','old',old),('other','old',old)]]
        def run(*args):
            if args[:2]==('image','inspect'):return [current]
            if args[:2]==('ps','-aq'):return ['d'*64]
            if args[0]=='inspect':return [used]
            if args[:2]==('image','ls'):return list(map(json.dumps,rows))
            return []
        with patch.object(cleanup,'_run',side_effect=run) as calls:
            self.assertTrue(cleanup.prune_unused({'plexconfigcontrol:latest'}))
        removed=[c.args for c in calls.call_args_list if c.args[:2]==('image','rm')]
        self.assertEqual(removed,[('image','rm','plexconfigcontrol-worker:old')])
    def test_unknown_inventory_never_removes_images(self):
        with patch.object(cleanup,'_run',return_value=['invalid']) as calls:
            self.assertFalse(cleanup.prune_unused({'plexconfigcontrol:latest'}))
            self.assertFalse(any(c.args[:2]==('image','rm') for c in calls.call_args_list))
