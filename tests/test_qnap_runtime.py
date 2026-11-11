import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from plexconfigcontrol.qnap_discovery import QnapDiscoveryError
from plexconfigcontrol.qnap_runtime import inspect_plex_runtime, plex_process_state


ROOT = '/share/ZFS530_DATA/.qpkg/PlexMediaServer'
INSTALLATION = SimpleNamespace(install_directory=ROOT, package_enabled=True)


class QnapRuntimeTests(unittest.TestCase):
    def probe(self, *, output='3.53.3\nok\n', service=ROOT+'/plex.sh', resolve=None):
        self.commands = []
        def runner(argv, **kwargs):
            self.commands.append((argv, kwargs))
            return SimpleNamespace(returncode=0,
                stdout=service if argv[0] == '/sbin/getcfg' else output)
        return inspect_plex_runtime(INSTALLATION, runner=runner,
            resolve=resolve or (lambda path: path), executable=lambda *args: True)

    def test_native_probe_uses_only_memory_and_never_runs_service_script(self):
        runtime = self.probe()
        self.assertEqual(runtime.sqlite_version, '3.53.3')
        self.assertEqual(runtime.service_script, ROOT+'/plex.sh')
        self.assertEqual(len(self.commands), 2)
        argv, options = self.commands[1]
        self.assertEqual(argv[1:5], ['-batch', '-init', '/dev/null', ':memory:'])
        self.assertEqual(options['env']['SQLITE_HISTORY'], '/dev/null')

    def test_invalid_or_failed_database_probe_is_rejected(self):
        for output in ('3.53.3\ncorrupt', '3.53.3', 'junk\nok', '3.53.3\nok\nextra'):
            with self.subTest(output=output), self.assertRaises(QnapDiscoveryError):
                self.probe(output=output)

    def test_external_service_and_tool_symlink_are_rejected(self):
        with self.assertRaisesRegex(QnapDiscoveryError, 'SERVICE_LOCATION_CHANGED'):
            self.probe(service='/etc/init.d/unrelated.sh')
        with self.assertRaisesRegex(QnapDiscoveryError, 'OUTSIDE_PACKAGE'):
            self.probe(resolve=lambda path: '/usr/bin/sqlite3')

    def test_timeout_is_sanitized(self):
        def runner(argv, **kwargs):
            raise subprocess.TimeoutExpired('private details', 15)
        with self.assertRaisesRegex(QnapDiscoveryError, '^QNAP_PLEX_RUNTIME_UNAVAILABLE$'):
            inspect_plex_runtime(INSTALLATION, runner=runner,
                resolve=lambda path: path, executable=lambda *args: True)

    def test_enabled_package_alone_does_not_mean_running(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(plex_process_state(INSTALLATION, proc=Path(directory)), 'STOPPED')

    def test_exact_main_executable_is_required(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            (proc/'12').mkdir()
            (proc/'self').mkdir()
            for suffix, expected in (('/Plex Transcoder', 'STOPPED'),
                    ('/Plex Media Server', 'RUNNING'),
                    ('/Plex Media Server (deleted)', 'RUNNING'),
                    ('/Plex Media Server-other', 'STOPPED')):
                self.assertEqual(plex_process_state(INSTALLATION, proc=proc,
                    readlink=lambda path: ROOT+suffix), expected)

    def test_unreadable_process_is_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            (proc/'12').mkdir()
            def denied(path):
                raise PermissionError()
            self.assertEqual(plex_process_state(INSTALLATION, proc=proc, readlink=denied), 'UNKNOWN')
