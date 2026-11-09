import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from plexconfigcontrol.plex_runtime import PlexRuntimeError, detect_plex_runtime


class PlexRuntimeTests(unittest.TestCase):
    container = 'c' * 64
    image = 'sha256:' + 'e' * 64

    def runner(self, reference, version, *, verified=None):
        return Mock(side_effect=[SimpleNamespace(stdout=output) for output in (
            self.container + '\n', self.image, 'unrelated/image@sha256:' + 'd' * 64 + '\n' + reference,
            verified if verified is not None else self.image + ' linux/amd64', version,
        )])

    def test_detects_two_official_images_and_their_own_sqlite_versions(self):
        for version, prefix, digit in (('3.53.3', '', 'a'), ('3.54.1', 'docker.io/', 'b')):
            reference = prefix + 'plexinc/pms-docker@sha256:' + digit * 64
            with self.subTest(reference=reference):
                runner = self.runner(reference, version + ' 2026-06-26 20:14:12 (64-bit)\n')
                self.assertEqual(detect_plex_runtime(runner=runner), (reference, version, self.container, self.image))
                self.assertEqual(runner.call_args.args[0],
                                 ['docker', 'exec', self.container, '/usr/lib/plexmediaserver/Plex SQLite', '-version'])

    def test_rejects_an_unpinned_image_and_mismatched_image_or_architecture(self):
        reference = 'plexinc/pms-docker@sha256:' + 'a' * 64
        for selected, verified in (('plexinc/pms-docker:latest', None),
                                   (reference, 'sha256:' + 'b' * 64 + ' linux/amd64'),
                                   (reference, self.image + ' linux/arm64')):
            with self.subTest(selected=selected, verified=verified):
                runner = self.runner(selected, '3.53.3', verified=verified)
                with self.assertRaises(PlexRuntimeError):
                    detect_plex_runtime(runner=runner)
                self.assertNotIn('exec', runner.call_args.args[0])

    def test_rejects_ambiguous_container_and_failed_or_invalid_sqlite(self):
        runner = Mock(return_value=SimpleNamespace(stdout=self.container + '\n' + 'd' * 64))
        with self.assertRaises(PlexRuntimeError):
            detect_plex_runtime(runner=runner)
        runner.assert_called_once()
        reference = 'plexinc/pms-docker@sha256:' + 'a' * 64
        with self.assertRaises(PlexRuntimeError):
            detect_plex_runtime(runner=self.runner(reference, 'SQLite version unavailable'))
        with self.assertRaises(PlexRuntimeError):
            detect_plex_runtime(runner=Mock(side_effect=subprocess.TimeoutExpired('docker', 20)))
