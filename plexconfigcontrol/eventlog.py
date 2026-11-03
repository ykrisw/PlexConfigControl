"""Create-only operation logs. No rename, deletion or historical-log editing API."""
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


class EventLog:
    def __init__(self, logs_directory, kind, started, timezone_name='Europe/London'):
        if kind not in ('Backup', 'Restore', 'Recovery'):
            raise ValueError('Unsupported operation kind')
        if started.tzinfo is None:
            raise ValueError('Timezone-aware timestamp required')
        self.name = kind + started.astimezone(ZoneInfo(timezone_name)).strftime('_%Y.%m.%d_%H.%M.%S.log')
        self.closed = False
        self.lines = []
        directory_fd = os.open(logs_directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fd = None
        try:
            # Honor directory ACL inheritance and process umask; never chmod/chown.
            fd = os.open(self.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o666, dir_fd=directory_fd)
            os.fsync(directory_fd)
        except BaseException:
            if fd is not None:
                os.close(fd)
            raise
        finally:
            os.close(directory_fd)
        self.stream = os.fdopen(fd, 'w', encoding='utf-8')

    def write(self, message, at=None):
        if self.closed:
            raise ValueError('Operation log is finalized')
        # Callers supply operational messages only, never credentials/API payloads.
        at = at or datetime.now(timezone.utc)
        if at.tzinfo is None:
            raise ValueError('Timezone-aware timestamp required')
        line = '[' + at.astimezone(timezone.utc).isoformat() + '] ' + str(message).replace('\r', '\\r').replace('\n', '\\n') + '\n'
        self.stream.write(line)
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.lines.append(line)

    def finish(self):
        if not self.closed:
            try:
                self.stream.flush()
                os.fsync(self.stream.fileno())
            finally:
                self.stream.close()
                self.closed = True
        return ''.join(self.lines)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.finish()
