# PlexConfigControl

PlexConfigControl is an application for manual Plex configuration backups and
restores, designed for installation as a **TrueNAS SCALE App**, with persistent
iXVolume storage for its own settings and state. Installers for other platforms
may be developed in future versions; they are not currently available.

**Restricted test installation available; not ready for production data.**

First test-installation packaging passed CI image/HTTPS/restart checks. `Dockerfile`
builds the unprivileged HTTPS image; **Build test installation** runs a disposable
container smoke test and Chromium/Firefox interface checks. Downloadable image
artifacts are produced only when the workflow is started manually; ordinary
code updates still run the checks without generating another installer. Follow
`deploy/TEST-INSTALL.md` only after that workflow succeeds. This is a restricted
test build, not permission to run Backup/Restore against live Plex data.

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
- Snapshot-backed Backup execution connected to the web API.
- Complete UI translations of errors.
- Web integration of the tested replacement coordinator and explicit publication recovery controls.
- TrueNAS installation test and final Apps password/secret form.
- Complete restore verification and rollback verification adapters.
- End-to-end tests on an isolated TrueNAS test dataset before live use.

Tests use temporary local files and simulated TrueNAS adapters. Test counts do
not establish that integration works on a real NAS. Some filesystem tests run
GNU tar; no tests modify the user's NAS.

## Development checks

Requires Python 3.11 or later and GNU tar on Linux.

```sh
python -m pip install '.[server]'
python -m unittest discover -s tests -v
python -m compileall -q plexconfigcontrol
node --test tests/browser/*.mjs
```

The test runtime requires a writable app ixVolume and non-root UID 568. It serves
HTTPS on container port 8443, with persistent self-signed TLS identity and local
verified-TLS health checking. Initial credentials use a salted verifier generated
by `python -m plexconfigcontrol.installation`; plaintext environment passwords
are rejected. Existing account credentials are never overwritten on restart.
The guided TrueNAS Custom App wizard maps ixVolume to `/var/lib/plexconfigcontrol`
and host port 8787 (configurable) to 8443. This temporary verifier step does not
complete the final requirement to choose the password directly in an app form.

Only `app.query` for Plex is exposed by the optional test API adapter. The test
route boundary blocks backup, actual restore, snapshot operations and archive
deletion. Optional archive storage must be read-only; no live Plex config,
Docker socket, ZFS devices or root privileges are mounted. It does not create or
adopt the final `Plex Config` output folder during this test phase.

The browser API module is served at `/assets/panel-client.mjs`. It supports
session login, CSRF-protected background validation, operation polling and
restore readiness, password changes and explicit logout.

The WSGI application now serves a development entry page at `/`, loading
`panel-app.mjs`. It restores the existing session or shows password-only sign-in,
then mounts the approved shell and all five views. No preview archives
or events are included. Backup shows real archives and planning; execution
remains unavailable. Mount behind HTTPS: session cookies
remain Secure. The installation must initialize the account beforehand.

Dashboard uses actual Plex status reads, returning to UNKNOWN after failed reads.
Change Password opens the current/new/confirmation dialog. A successful change
revokes all sessions and returns to sign-in; explicit logout also returns to
sign-in only after server confirmation. Leaving the application disposes polling.
There is no timer that signs users out for inactivity. Saved theme and language
preferences are loaded at sign-in; Dashboard labels support English and Polish,
while sign-in messages and uncommon server errors still need full translation.
Profile photo upload/replacement and confirmed removal are connected. Controls
appear at the lower edge of the avatar on hover or keyboard focus; touch devices
keep them accessible. JPEG/PNG uploads are authenticated and CSRF-protected, at
most 5 MiB and 20 megapixels, and normalize to a pixel-only 512px PNG without
EXIF/GPS metadata. Only `profile-photo.png` in application state is published.
Atomic replacement preserves the previous image on failure. Restart cleanup is
limited to the exact owned `profile-photo.pending` file. Confirmed deletion checks
the displayed image revision to avoid deleting a replacement from another session.
Private image reads require login; original filenames/paths are never stored or
used as filesystem paths. The first downloadable test image predates this feature.

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
layout hooks; Backup execution still needs integration.

`restore-view.mjs` exports `mountRestoreView(section, client)` and binds the
actual archive list, selection, validation, progress, readiness, cancellation
and Plex status to the API. It can mount into `shell.sections.get('restore')`.
No archive is automatically selected. Dynamic text uses `textContent`.
Restore labels, manual-stop guidance, common archive rejection reasons and real
validation stages support English and Polish. Unknown diagnostic reasons remain
visible instead of being replaced by a vague translated error. Validation reads
all file content, checks the gzip stream and streams SHA-256 calculation with
actual byte counters for each stage. Compressed hashing bytes and expanded file
bytes are separate stages; no percentage is invented without a known total.
An older polling response cannot replace a newer snapshot or clear its result.
Waiting/active operations reject selection changes and duplicate validation.
Archive-list read failures disable validation; removed selections are cleared.
The final destructive Restore action remains unavailable in this development
view until the host adapters are fully integrated and verified. A disposer
removes listeners and browser polling without cancelling server work.

The inline conversation preview remains illustrative; it is not an installed
application. The build workflow now checks the real packaged interface in
Chromium: authentication, five tabs, theme/language changes, profile upload and
removal, archive prevalidation, history downloads and account password/logout.
It captures Light/Dark screenshots plus narrow 320/360px screens and checks
shared panel heights, horizontal overflow and navigation alignment. Only
disposable Docker state and synthetic CI archives/history are used, never a NAS.
Screenshots are uploaded separately as `PlexConfigControl-browser-screenshots`.
The browser uses a temporary self-signed-certificate exception only for its local
CI context; the HTTPS health probe still verifies the generated certificate.

Real-browser checks found and fixed an Illegal invocation at sign-in: native
Window fetch must retain its receiver. Earlier image artifacts predate this fix;
use a build that passes the real-browser check rather than an earlier package.

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

## Verified replacement coordinator

`Backup.run_overwrite(selected_archive)` implements the single-copy overwrite
choice at the coordinator layer. It requires the exact current selection and
recounts under the operation lock; stale selections or a changed archive count
are rejected before any snapshot. The replacement gets a new dated filename.
A same-name collision requires another timestamp; it is never silently replaced.

The old file remains intact while the snapshot is read and the new archive is
validated. Only after exact snapshot removal is confirmed does the coordinator
publish the new file, re-read its SHA-256, check both identities and retire the
selected old file. It changes no folder permissions or ownership. A private,
fsynced replacement intent records both names, the old identity and new digest
before publication; it is removed only after completion. Ambiguous publication,
retirement or marker cleanup enters RECOVERY_REQUIRED and blocks more work,
including after restart. Recovery does not automatically delete either archive.
Manual reconciliation of this record is still pending; this is not yet enabled
through the web execution API or the restricted test installation.

External SMB changes detected during replacement retain the original and mark
recovery required. As with archive deletion, ordinary stat/unlink cannot provide
filesystem compare-and-swap against concurrent external writers. Do not edit,
rename or delete either file through SMB during replacement. Isolated TrueNAS
integration and fault-injection tests remain required before live use.

## Portable single-file archives

Each completed `TrueNASPlexConfig_YYYY.MM.DD_HH.MM.SS.tar.gz` is a standalone
backup. Copy the complete file unchanged to another disk, NAS or storage service,
then copy it back into the configured `Plex Config` folder with its original
filename. Do not extract or repack it. Refresh the archive list and validate it
again before Restore. No original snapshot, history record, app database,
sidecar checksum, operation log or source machine path is required to recognize
and validate the returned archive. After reinstalling, import it into the new
`Plex Config` folder created by setup; existing-folder setup protections still apply.

File bytes must survive the round trip. The archive container's own owner,
permissions, mtime, xattrs and inode may change during an SMB/NTFS/exFAT copy;
configuration file bytes and recorded numeric ownership, modes, ACLs/xattrs and
paths stay inside the tar stream. The returned file must be readable by the
app under the selected folder's existing access policy; import does not reset
ACLs or take ownership. Complete the copy before clicking Refresh/Validate.

Listing scans the directory directly rather than consulting History. Validation
reads every member and the full gzip stream and computes a fresh SHA-256.
Changing/replacing a file after validation invalidates readiness and execution,
even for an identical-byte returned copy: cancel preparation and validate it
again. Private staging independently checks the content digest before extraction;
a changed or incomplete copy cannot trigger a configuration write or emergency
snapshot. Manual Plex stop and typed RESTORE confirmation remain mandatory.

`tests/test_archive_portability.py` exercises actual backup creation, byte-only
export, deletion of the original archive/snapshot fixture and original app state,
reimport with changed outer metadata, fresh web listing/prevalidation and a full
restore coordinator run into an isolated temporary directory. It compares all
fixture bytes, names, modes, owners, mtimes and supported user xattrs, and runs
SQLite integrity checks on real fixture databases. It also checks incomplete,
damaged and replaced copies. ZFS and Plex adapters are simulated; this is not
proof of live SMB/TrueNAS ACL preservation or Plex-specific database compatibility.

## Storage contract

Backup now lists real archives with selection, scrolling, Plex state and current
archive-count planning. Zero or at least two copies plan a new dated archive;
exactly one requires the overwrite/new-copy choice, including after deletion
back to one. Creating/overwriting remains disabled until the execution API and
host integration are connected. Deletion uses server-advertised capabilities,
operation gating, a filename confirmation list and exact archive identities.
The restricted test runtime advertises deletion disabled and also blocks its
route. Failed/partial deletion responses are never retried automatically; lists
refresh and retain an uncertainty warning. External SMB writers remain outside
the operation lock; archive deletion is not a filesystem compare-and-swap.

Archive identity fields in `/api/archives` and `/api/backup/plan` are decimal
strings, including nanosecond modification times and inode numbers. This avoids
JavaScript Number rounding. The deletion route accepts those exact strings and
retains integer compatibility for non-browser clients. Presentation may convert
size/date values, but confirmation always sends the original exact strings.

Settings theme buttons persist Light/Dark/System through the authenticated API;
appearance changes only after server confirmation. First installation stays
System until manually changed. English/Polish selection updates Settings and tab
labels immediately. Dashboard and History remount in the new language when next
opened. Disposing a Restore view never cancels server validation. Uncommon error
translations remain pending. The first downloadable test image predates
the Settings view; subsequent successful build artifacts include it.

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


## Archive arrival history and permanent logs

Authenticated archive-list and History refreshes scan the configured directory.
A newly observed filename/inode creates an `ARCHIVE_DETECTED` / `INFO` event with
the filename, observed size, detection time and an explicit NOT VALIDATED note.
History displays “Archive detected” / “Wykryto archiwum”; its text can be downloaded
through Download Logs. Detection does not count as a successful Backup or Restore.
No source computer or actual copy time is guessed, and no extraction occurs.

An observation ledger in the app ixVolume prevents repeated events across scans,
worker restarts and History clearing. App-created backups register their identity
after publication and are not mislabeled as imports. A removal observed on a scan
followed by a returned file produces another event. Initial unknown files are
reported as detected, with no claim that they were copied during app uptime.
This is directory observation, not a continuous OS audit: changes occurring
entirely between scans, or an in-place overwrite of the same inode, may not be
recognized as another arrival. Growing copies do not produce an event per chunk.

Each detection also queues a create-only permanent log named
`ArchiveImport_YYYY.MM.DD_HH.MM.SS_<unique-id>.log`, exclusively under
`Plex Config/Logs`. The private durable outbox retries unavailable destinations;
`/api/operation.archive_discovery.pending_logs` reports records awaiting writing.
A conflicting or partial existing log is never overwritten or removed. Completed
logs are not recreated if manually deleted. Clearing web history touches neither
permanent logs nor the observation ledger and never resurrects the cleared event.

The restricted test runtime still mounts archives read-only: it records and
exports the History event, queues its permanent log in the app ixVolume and
explicitly reports permanent_logs_enabled=false. It does not bypass that mount or
write logs elsewhere on the NAS. A writable configured deployment is required
to flush those records into Plex Config/Logs. Actual SMB/TrueNAS tests are pending.

## Snapshot recovery preflight

The recovery coordinator inspects only the exact recorded, dataset-scoped
snapshot. It reports PRESENT, ABSENT or UNKNOWN from a fresh read-only query,
never from a guessed interpretation of a missing/malformed response. Active
operations keep inspection/removal unavailable under the shared operation lock.
Transport exception payloads are not exposed in the inspection result.

A lost deletion reply can leave recorded intent for an already absent snapshot.
A fresh ABSENT result allows a new explicit confirmation to reconcile that exact
intent without sending another deletion. The original failed operation remains
RECOVERY_REQUIRED until other cleanup is verified. For a retained Restore
snapshot the inspection explicitly identifies loss of the rollback recovery point.

Snapshot existence/absence checks reject wrong identities, multiple results and
malformed result types. Unknown state cannot clear intent or permit a success
report. Rollback independently verifies the Plex application identity as well as
STOPPED state. Snapshot readers also reject malformed query entries before opening
any source. Tests cover these cases with simulated APIs; recovery controls remain
unconnected to the restricted web runtime pending verified host integration.
