# PlexConfigControl

Development project for one TrueNAS App managing manual Plex configuration
backups and restores. **Not ready for installation or production data.**

## Implemented foundations

- Password hashing, escalating persistent lockout and explicit session logout.
- English/Polish catalogs and persistent preferences; System theme by default.
- Separate panel history, history deletion and in-memory log downloads.
- Create-only permanent operation logs, archive listing and confirmed deletion.
- Archive validation, private restore staging, content comparison and progress.
- Snapshot lifecycle, read-only snapshot access and backup/restore coordinators.
- Interrupted-operation detection and exclusive operation locking.
- Authenticated WSGI JSON endpoints for the connected account/history features.

## Remaining before deployment

- Real TrueNAS WebSocket authentication and verified TLS transport.
- Container access to snapshots and tested file ownership/ACL/xattr preservation.
- Approved Light/Dark interface connected to the server.
- Profile photo support and complete UI translations of errors.
- Single-existing-archive overwrite workflow and crash-safe publication recovery.
- Production HTTP/HTTPS server, certificate setup and TrueNAS installation form.
- Complete restore verification and rollback verification adapters.
- End-to-end tests on an isolated TrueNAS test dataset before live use.

Tests use temporary local files and simulated TrueNAS adapters. Test counts do
not establish that integration works on a real NAS. Some filesystem tests run
GNU tar; no tests modify the user's NAS.

## Development checks

Requires Python 3.11 or later and GNU tar on Linux.

```sh
python -m unittest discover -s tests -v
python -m compileall -q plexconfigcontrol
node --test tests/browser/*.mjs
```

The browser API module is served at `/assets/panel-client.mjs`. It supports
session login, CSRF-protected background validation, operation polling and
restore readiness. It does not yet render or bind the approved interface.

`/assets/restore-panel.mjs` exports `bindRestoreControls(root, client, render)`.
The Restore markup can bind radios named `restore-archive` and buttons with
`data-restore-action="validate"`, `"cancel"` or `"refresh"`. The render callback
receives the current selection, busy flag, server snapshot and error; write
server strings using `textContent`. Calling the returned disposer stops browser
polling and listeners without cancelling the server operation. No archive is
selected automatically. Full HTML, styling and the final restore action remain
to be connected.

## Storage contract

All application settings, credentials, sessions, profile data, panel history and
working state belong in the application ixVolume. The user-selected destination
contains `Plex Config/`, dated `.tar.gz` archives and `Plex Config/Logs/` only.
An existing `Plex Config` at first installation must be renamed manually before
setup creates a fresh folder. Never reset its ACLs or ownership automatically.

Backup never stops Plex. Restore waits for the user to stop Plex and confirm
`RESTORE`; it never starts Plex afterward. Only the recorded operation snapshot
may be removed. A failed Restore retains its emergency snapshot. Unresolved
cleanup blocks new operations. Manual snapshot removal requires confirmation.

When creating a backup, use the current archive count: zero creates a new copy,
one asks overwrite or create another, two or more create another dated copy.
History deletion never deletes permanent `.log` files. No inactivity logout.
