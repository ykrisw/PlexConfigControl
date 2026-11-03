# PlexConfigControl

Development project for one TrueNAS App managing manual Plex configuration
backups and restores. **Not ready for installation or production data.**

The approved appearance is frozen in `design/approved-panels.html` with its
specification in `design/README.md`. Shared production styles import
`static/approved-appearance.css`; subsequent UI work must use that baseline.

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
- Backup and Settings views connected to the server.
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
restore readiness, password changes and explicit logout.

The WSGI application now serves a development entry page at `/`, loading
`panel-app.mjs`. It restores the existing session or shows password-only sign-in,
then mounts the approved shell, Dashboard, Restore and History views. No preview archives
or events are included. Backup and Settings show explicit integration
placeholders; they are not usable panels yet. Mount behind HTTPS: session cookies
remain Secure. The installation must initialize the account beforehand.

Dashboard uses actual Plex status reads, returning to UNKNOWN after failed reads.
Change Password opens the current/new/confirmation dialog. A successful change
revokes all sessions and returns to sign-in; explicit logout also returns to
sign-in only after server confirmation. Leaving the application disposes polling.
There is no timer that signs users out for inactivity. Saved theme and language
preferences are loaded at sign-in; Dashboard labels support English and Polish,
while Restore, sign-in messages and server errors still need full translation.
Profile photo upload/removal is not implemented yet.

`/assets/restore-panel.mjs` exports `bindRestoreControls(root, client, render)`.
The Restore markup can bind radios named `restore-archive` and buttons with
`data-restore-action="validate"`, `"cancel"` or `"refresh"`. The render callback
receives the current selection, busy flag, server snapshot and error; write
server strings using `textContent`. Calling the returned disposer stops browser
polling and listeners without cancelling the server operation. No archive is
selected automatically. The final restore action and complete five-panel
application still need integration.

### Shared panel geometry and Restore view

`panel-shell.mjs` exports `mountPanelShell(root, {onNavigate, theme})`. It creates
the five top tabs and persistent panel sections with a shared content height
(820px minimum), 18px side/bottom insets and 14px spacing. The height is shared
through `--pcc-content-height`; individual tabs must not override it.

Use `pcc-card pcc-account` in Dashboard, `pcc-card pcc-archives` in Backup,
`pcc-card pcc-events` in History and `pcc-card pcc-about` in Settings for the
cards whose lower edges should expand to the bottom. Backup's Important card
keeps its natural height below the expanded archive list. These are shared
layout hooks; Backup and Settings content still needs integration.

`restore-view.mjs` exports `mountRestoreView(section, client)` and binds the
actual archive list, selection, validation, progress, readiness, cancellation
and Plex status to the API. It can mount into `shell.sections.get('restore')`.
No archive is automatically selected. Dynamic text uses `textContent`.
The final destructive Restore action remains unavailable in this development
view until the host adapters are fully integrated and verified. A disposer
removes listeners and browser polling without cancelling server work.

The inline conversation preview remains illustrative; it is not an installed
application. Browser rendering of the packaged views still requires visual QA.

### Connected History view

`history-view.mjs` mounts real history records with counters, All/Backup/Restore
filters, multiple selection, timestamps in the saved timezone, and a scrolling
list. A confirmation dialog identifies the selected record count before clearing
only those web-history records. Changing filters clears the selection. Refreshes
preserve surviving selections and remove missing ones; stale confirmations and
unconfirmed deletion responses cannot trigger automatic retries.

Download Logs exports the log text stored with the selected web-history events:
one `Event_ID.log` or an in-memory ZIP for multiple events. This does not read or
modify original permanent operational log files; exporting their complete content
will need a separately verified association between events and those files.
No temporary downloads are written on the NAS. Downloads and history clearing
require the authenticated session and CSRF token. The browser revokes temporary
download URLs after use or disposal. Selected downloads are limited to 1000 events.

History IDs now use SQLite AUTOINCREMENT, so deleted IDs are not assigned to new
events. Existing history databases migrate transactionally, preserving live IDs
and contents. This prevents stale browser selections from targeting later events.

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
