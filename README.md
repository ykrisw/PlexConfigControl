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
- Isolated TrueNAS verification of the file/metadata and rollback comparison adapters.
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

The optional test API adapter exposes only Plex `app.query` by default.
With explicit `PCC_PLEX_CONFIG_DATASET` and an already configured verified-TLS
read-only connection, it can also query the exact recorded application snapshot
in that dataset. It cannot list all snapshots, mutate them or control Plex.
Unavailable/unauthorized metadata remains UNKNOWN. Configuration grants no
TrueNAS account or role automatically. The test
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
Confirmed reconciliation of fully published archives is implemented at the
coordinator layer as described below; it is not enabled through the web execution
API or the restricted test installation.

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


## Read-only recovery status in Backup and Restore

Both panels now mount the same recovery notice, visible only when operation
state is RECOVERY_REQUIRED. The notice uses the active theme, notification border,
English/Polish text and the recorded snapshot identity; it distinguishes PRESENT,
ABSENT, UNKNOWN and no recorded snapshot. A retained Restore snapshot displays
an explicit warning about losing the rollback point. No-snapshot recovery still
warns that archive publication or temporary-file verification may be outstanding.

Authenticated `GET /api/recovery` defaults to UNKNOWN for a recorded snapshot
when no verified host inspector is configured. A deployment can inject only a
read-only `Recovery.inspect` adapter. The endpoint always advertises removal
unsupported and unavailable; there is no removal POST route or arbitrary host
command interface. The restricted runtime permits this read but does not acquire
snapshot permissions or infer snapshot absence from an unavailable connection.

The UI has a refresh-status button, periodic reads while recovery is visible,
request identity checks and disposal guards. Lost operation/status reads clear
previous confirmed data; late replies cannot redraw a different snapshot or a
logged-out panel. Normal panel layout is unchanged when recovery is not required.
Tests cover authentication, unexpected adapter replies, missing host integration,
controller races and simulated recovery intent inside disposable browser fixtures.
Actual confirmed snapshot removal remains to be connected after host integration
is authorized and verified; the informational view does not perform cleanup.

## Microsoft Edge and Android browser checks

The browser workflow also installs and launches the actual Microsoft Edge stable
channel on its Linux runner (`PCC_TEST_BROWSER=msedge`), verifies the Edge user
agent and runs the full desktop interface suite. This is separate from bundled
Chromium coverage and does not establish results on Windows or macOS.

`tests/mobile_e2e.py` exercises touch events, avatar controls/upload, checkbox/radio
selection, archive-list swiping, validation/cancellation, History confirmation,
five-tab navigation, English/Polish, Light/Dark, saved preferences and logout.
The default mode uses a Pixel 5 Chromium device profile, with Android user agent
and touch enabled. That mode alone is not an Android OS test.

A separate CI job starts an Android API 35 x86_64 Google APIs emulator and attaches
to its Chrome browser through adb/CDP. The test explicitly refuses physical
ADB devices and non-CI execution in Android mode. It prints the actual Android
and Chrome versions. The test app and all data are disposable; no user NAS is
contacted, no installer artifact is produced, and app host mutations remain
blocked. TLS is verified by a separate host health probe; only the ephemeral test
browser accepts the synthetic test certificate. Screenshots are stored separately
for Edge, Android device emulation and Android-system tests.

These checks exercise the web client. A physical Android phone, vendor-specific
browser/file pickers, native downloads and Android keyboard behavior still need
manual device verification; emulator success is not a blanket compatibility claim.


## Apple-platform verification

`tests/apple_e2e.py` uses Selenium with the installed Safari.app and Apple's
safaridriver on a disposable macOS runner, or the installed stock Firefox.app
and geckodriver. Safari is not substituted with Playwright WebKit. Separate
matrix entries create disposable iPhone/iPad simulators from installed Xcode
runtimes and use Safari's iOS WebDriver support with an explicit simulator UUID.
Physical devices and a non-CI host are not eligible for these tests.

The fixture serves the same restricted WSGI application over locally verified
HTTPS with real temporary account/history/archive state. Docker, ZFS, live Plex
and a user NAS are not involved. Safari trusts only the fixture certificate in
the isolated runner/simulator; the exact host certificate trust entry and only
the simulator created by this run are removed afterward. The CI log records the
actual OS, browser and simulator runtime/hardware; tests do not assume the
runner matches a user's macOS/iOS version.

Coverage includes sign-in, session restoration, five panels, archive import and
selection, validation/manual-stop gating, profile photo upload/removal, History
confirmation/clearing and log response bytes, permanent-log preservation,
English/Polish, Light/Dark preferences, scrolling/overflow, password change and
logout. File upload uses the web input handler; log-byte checks use the actual
authenticated API. Native photo pickers, Save/Files dialogs and physical touch/
keyboard behavior are not thereby certified.

Firefox for iOS/iPadOS is a separate App Store application, not this macOS
Firefox binary and not Safari. It is not installed or tested in these jobs.
Manual checks on a physical iPhone/iPad remain necessary for that application,
for native OS dialogs and for the user's specific OS/browser versions. A failed
or unavailable simulator/driver run must be reported as such, never relabeled
as a passed WebKit/device-emulation test.


Mobile Safari WebDriver on the hosted Apple simulators was observed to leave
secure password inputs empty. Mobile test controls therefore use DOM value/input/
change events and DOM click activation after checking visibility/enabled state.
They still run in real simulator Safari against the real HTTPS application and
backend, without mocking login or bypassing CSRF. This verifies application logic
and rendering, not native user activation, physical keyboard, gesture or picker
behavior. macOS Safari/Firefox continue using normal WebDriver keyboard/clicks.
The distinction must remain explicit when reporting mobile results.


## Confirmed recovery after interrupted publication

`PublicationRecovery.inspect()` fully rereads the published tar/gzip archive and
compares SHA-256 with the digest persisted before publication. Both new-copy and
replacement records carry that digest. An old two-line record is still readable
for diagnosis, but cannot be reconciled automatically without the missing digest.

`keep_archives(token, confirmed=True)` repeats validation under the operation
lock and requires the exact inspected record and archive identity. It clears only
the private publication marker; it never deletes, overwrites or renames any
archive, even an older copy that a replacement originally intended to retire.
The original operation stays FAILED with its original elapsed time. A separate
WARNING history event and a create-only `Recovery_YYYY.MM.DD_HH.MM.SS.log` in
`Plex Config/Logs` record the verification and confirmed retention decision.
Clearing History cannot remove that log. A same-second log collision fails closed;
retry later rather than overwrite a permanent log.

Outstanding snapshot intent, remaining temporary publication files (including
hardlinks), missing/unsafe/changed final archives, malformed or conflicting
records, audit-write failures and unexpected operation state prevent recovery.
No partial file is promoted. The coordinator accepts no host API and does not
start/stop Plex or create/delete snapshots. Other private workspaces are not
removed by this publication-only reconciliation.

State is checkpointed as FAILED before removing the marker: the pending marker
still blocks new work and archive deletion if interrupted. An unlink/directory
fsync failure reblocks the operation, even when the marker is already absent;
that ambiguous state needs manual investigation. External SMB writers cannot be
serialized by the app lock; do not modify the files during inspection/confirmation.
The restricted web test installation has no route enabling this coordinator.
Tests use synthetic local archives and injected disk failures, not live TrueNAS.


## Publication diagnostics in Backup and Restore

The authenticated read-only `/api/recovery` response now includes the sanitized
publication record alongside snapshot status. It reports only recognized archive
and temporary filenames; unreadable records expose no raw contents or paths.
Names are operation intent, not a claim that any named file exists or is valid.
Polling does not hash, extract, delete or promote an archive. If operation identity
or the publication record changes during snapshot inspection, the reply is
rejected and the client must refresh rather than display a stale confirmation.

Backup and Restore display these details inside the existing themed notification
with the yellow border, in English or Polish. Failed reads clear previous details.
A pending publication also blocks Restore selection/validation at a FAILED
checkpoint; a browser reload or runtime restart cannot dismiss the pending work.
The core confirmed reconciliation coordinator is still not exposed through a web
mutation route: `publication_resolution_supported` remains false. The view offers
only Refresh status. This does not enable live Backup/Restore execution.


## Independent rollback verification

`RollbackVerifier(store, snapshot_reader, config_writer)` is a read-only Restore
adapter for checking a failed Restore after the snapshot rollback request returns.
It requires the exact still-recorded Restore snapshot and operation state, opens
it through the scoped `SnapshotReader`, and compares its configuration against
the configured live dataset with GNU rsync dry-run, checksums, numeric ownership,
permissions, hardlink/ACL/xattr checks and unexpected-file detection. Plex must
remain confirmed STOPPED. Target and source directory identities are rechecked
after the potentially lengthy comparison, as is the outstanding operation record.
A changed identity or state prevents a verified-rollback result.

Only `ConfigWriter.verify_snapshot` accepts the exact read-only emergency-snapshot
path beneath the configured dataset. It excludes the root virtual `.zfs/`
control directory from this comparison. The source/target overlap restriction
remains intact for configuration writes: this exception cannot authorize copying
snapshot contents into the live dataset. The adapter does not create a second
snapshot, remove the retained emergency snapshot, reset ACLs or start Plex.
A verified rollback still leaves the failed Restore FAILED/RECOVERY_REQUIRED.

Tests execute actual GNU rsync comparisons on temporary files, including
same-size corruption with preserved mtime, extra files, permissions and hardlinks.
Coordinator tests inject a simulated snapshot/rollback API and read-only mount
flag, and verify that corrupted rollback data is never logged as verified.
These are not real ZFS rollback or TrueNAS ACL tests. The adapter is not yet
connected to live Restore execution in the restricted web test installation.


## Restore failure and reporting boundaries

Restore now completes private staging cleanup before requesting removal of the
emergency snapshot, and checks STOPPED again after cleanup. A staging-cleanup
failure therefore still has the recorded recovery point available. Remaining
private `restore-*` workspaces, or an unreadable workspace inventory, also keep
recovery blocked even if configuration writes had not started; they are never
silently deleted by this failure handler. Failure to
write progress cannot skip the rollback attempt; host state and exact snapshot
existence are independently checked before any rollback request.

A lost deletion reply is ambiguous: the snapshot may already be absent. The
operation retains its exact snapshot intent and remains RECOVERY_REQUIRED until
inspection/reconciliation confirms what happened. It does not claim snapshot
presence, create another emergency point or start/stop Plex to investigate.

Errors during final progress/log/history reporting are also failures of the full
operation. Fail-closed progress can replace a premature COMPLETED with
CLEANUP_REQUIRED while preserving the recorded finish time. Interrupted startup
reconciliation uses the same rule. If configuration verification and snapshot
removal already completed, the app reports that distinction rather than attempt
a rollback using a nonexistent snapshot. New operations remain blocked.

A finalized permanent Restore log is never reopened or edited. If subsequent
History/finalization fails, the coordinator attempts a separate create-only
`Recovery_YYYY.MM.DD_HH.MM.SS.log` under `Plex Config/Logs`. If disk or History
writes also fail, it preserves the original exception and durable recovery state
where storage remains available; it does not invent a saved log or History entry.
These stores are not one atomic transaction; investigating a reporting failure
must include operation state and any permanent logs already written.

Fault tests cover staging cleanup, unavailable progress/History/log writes,
snapshot deletion refusal, lost deletion replies, manual Plex restart during
cleanup, and process interruption/startup. They use real local tar/gzip staging
with simulated host responses, not real ZFS operations on a NAS.


## Backup reporting failures and preservation

Backup applies fail-closed progress reporting to errors after archive publication,
including failures of permanent logging or web History. A published archive is
never deleted by this failure handler. If the publication marker had already
been cleared, it attempts to recreate the same marker from the previously
verified digest and recorded filenames, without republishing or trusting a fresh
hash of possibly changed data. Recreating a marker cannot overwrite an existing
one. If storage cannot retain that intent, durable operation state still remains
RECOVERY_REQUIRED and manual investigation is needed.

A finalized Backup log is not reopened or edited: subsequent reporting failures
attempt a separate create-only Recovery log in `Plex Config/Logs`. History/log
errors cannot mask the original exception or leave a premature COMPLETED status
as the final progress result when progress storage is available. RUNNING is kept
until final reporting returns, so process interruption during reporting is
reconciled at startup. These independent stores are not one atomic transaction;
manual investigation must consult operation state and existing permanent logs.

For replacement, private workspace cleanup now precedes retirement of the old
archive. If cleanup fails, both published new and selected old files remain.
Remaining `backup-*` workspaces block both full success and publication-recovery
confirmation. This code never recursively deletes an unidentified workspace.
Snapshot cleanup remains an independent attempt for exactly the recorded temporary
snapshot, even when logging fails. Plex is neither stopped nor started.

The injected-fault suite uses actual local archive creation/publication with a
simulated host API. It covers History and log failures, lost publication replies,
failed/ambiguous snapshot cleanup, lost snapshot creation replies, interrupted
final reporting, private workspace leftovers and unavailable recovery-intent
storage. It also confirms that a retained valid archive can be fully reverified
and acknowledged without new host calls. This does not enable Backup execution
in the restricted web runtime or establish real TrueNAS/ZFS permissions.


## Backup outcome notices

The current operation state now stores a small allowlisted historical outcome
(code and archive filename). It distinguishes completion, failure before confirmed
publication, a published archive requiring review, uncertain publication, process
interruption and confirmed re-verification. It is not an archive allowlist or proof
that a file still exists or is currently valid. Moving a completed archive does
not rewrite the historical result; returned archives still need validation.

Backup displays success only for consistent SUCCESS/COMPLETED state with no
recorded snapshot or pending publication. Failure and publication warnings use
the existing themed yellow-border notifications in English/Polish. Re-verification
is explicitly separate from the original failed Backup. Recovery replies are
bound to the observed outcome as well as snapshot/publication identity; outdated
replies or failed reads cannot retain an earlier confirmation.

Older operation-state payloads without this optional field remain readable. A new
operation clears the previous outcome. Web History remains separate: clearing
History neither recreates events from this field nor clears operational recovery
locks. API output strips malformed or unrecognized outcome contents. No execution
or cleanup capability is enabled by these diagnostic notices.


## Restore outcome notices and interrupted execution

Restore stores an allowlisted historical outcome alongside the current operation:
completion, failure before configuration writes, verified rollback, unconfirmed
recovery, verified data/snapshot cleanup with failed final reporting, or process
interruption. API output also binds each code to its operation kind. The panel
never equates a verified rollback with successful Restore, or a recorded snapshot
identity with confirmed current presence. English/Polish messages preserve these
distinctions and do not claim that Plex is currently stopped based on old history.

Success requires consistent SUCCESS/COMPLETED state and confirmed operation
snapshot cleanup. Completion state is saved only after final reporting returns.
Live stage/elapsed labels use recorded progress; no file-byte count or percentage
is fabricated for rsync stages without such measurements. The execution API
remains disabled in the restricted test installation.

An execution-start record is now persisted before private staging/database work.
Startup recognizes interrupted execution even if the phase had still been the
manual-stop preparation phase. It remains blocked until recovery is checked;
retrying execution, cancelling it as ordinary preparation, or reporting readiness
cannot erase that record. A normal validated archive simply waiting for the user
to stop Plex has no execution record and survives restart without this warning.

Tests cover both paths and real coordinator checkpoint selection with injected
host adapters. Browser CI adds synthetic read-only rollback/recovery fixtures
and reload checks; these fixtures perform no real snapshot or Restore operation.


## Read-only connection diagnostics

Settings → About → Details contains an explicit Run checks action. Opening
Settings/Details or changing language does not trigger probes. The authenticated
GET `/api/integration` checks only configured read capabilities: Plex status,
archive directory listing, and (when configured and recorded for recovery) one
exact application snapshot. It never creates a test snapshot, starts/stops Plex,
changes ACLs, hashes/extracts archives or runs import/history logging.

A readable archive list is reported separately from archive content validation.
With no recorded snapshot the result says that snapshot access was not tested;
configured scope alone does not prove permissions. Busy/changing operations clear
snapshot confirmations. Missing configuration, unavailable reads and unknown
states remain explicit. Transport errors, API keys, connection URLs and private
paths are not returned. Checks have a UTC timestamp and are historical observations,
not a continuously monitored connection status.

Backup/Restore availability remains false even when every read succeeds: host
execution integration is still not connected in this restricted test runtime.
The panel runs no automatic retries or polling. Failed checks remove previous
confirmations, and disposal/logout cancels pending browser reads. The diagnostics
POST route is unavailable; configuration continues to belong in deployment setup.
The added controls stay inside the existing collapsed Details, preserving the
approved default Settings layout in Light/Dark/System and English/Polish.


## Confined destination-setup baseline

The installation-side `storage` module now opens every component of the selected
absolute parent with NOFOLLOW, rejects traversal/ancestor symlinks and supports
explicit protected ixVolume/Plex-source paths supplied by trusted deployment code.
Read-only `inspect_destination` reports name availability separately from untested
write/SMB permissions. Actual creation rechecks with exclusive mkdir; a folder,
file or symlink already named `Plex Config` always requires manual renaming.

Fresh `Plex Config`/`Logs` entries are fsynced and checked for observed name/identity
replacement before success. Existing permissions/ownership are never changed;
new-directory permissions honor process umask and inherited ACLs. Partial setup
is retained for explicit inspection, never recursively removed when SMB may have
already written files. Structured English/Polish error messages omit raw OS error
text and private paths. Only archives and Logs belong in this user directory.

`verify_destination` checks the returned root/Logs anchors without recreating or
adopting missing/replaced folders. These are mount-session device/inode anchors,
not persistent ZFS provenance; real deployment still needs trusted storage binding
and reboot checks before using them across remounts. External SMB renames/mount
changes cannot be serialized by an application-only lock; pause them during setup.
The restricted test runtime does not call destination creation or adopt an existing
archive mount as newly owned storage. These are installer integration primitives,
not a completed installation form or permission to alter a live NAS dataset.


## Password changes and session generations

Web sessions now bind to a private fingerprint of the current stored credential.
Changing the password invalidates older sessions immediately, even if deleting
obsolete session rows or writing the History event fails. A login verified against
an older credential cannot create an authorized new session after a concurrent
password change. Password updates also compare the credential verified earlier
before committing, so a stale concurrent change cannot overwrite a newer password.
No fingerprint, password, salt or hash is returned by the public session API.

Existing unbound sessions from older builds require one sign-in during migration;
new bound sessions survive ordinary restarts while credentials remain unchanged.
There is still no idle-expiry timer. Password-change responses explicitly flag
unconfirmed History or row-cleanup work; logical invalidation does not depend on
row deletion. An unavailable History record is mentioned on return to sign-in.

The browser fences responses by session generation. Old unauthorized replies
cannot sign out a new login, old JSON/download bodies cannot populate a newer
session, and concurrent account transitions are not automatically retried.
Background unauthorized polling waits for the result of an in-flight password
change/logout before deciding whether to return to sign-in, avoiding accidental
cancellation of the confirmation. A lost connection without an unauthorized
response does not itself become an idle logout or claimed successful password change.

Tests inject credential-change/session-insert races and database cleanup failures.
Browser CI also checks revocation in a second isolated browser context. These
checks use disposable local account state and never modify a NAS account/password.


Installer packaging runs only through manual workflow dispatch. Normal code pushes
run tests without producing another installer. Packages include BUILD-INFO.txt with the exact source
commit and checksums for the image, guides and build information. Restricted test
mode and disabled host execution remain unchanged.


TrueNAS RPC calls share one request time budget across waiting for the client lock,
connection setup, authentication and response notifications. The production
WebSocket transport receives the remaining timeout before each send/receive;
notifications cannot restart the budget. A caller that times out waiting for the
lock does not close another caller's connection. Late mutation replies remain
uncertain and are never retried automatically. This is covered by local protocol
tests; real TrueNAS timeout/recovery behaviour still requires host acceptance tests.

### Opt-in TrueNAS host snapshot smoke test

`python -m tests.host_snapshot_smoke --run-sandbox-test` (as root on the host)
exercises the application's `Snapshots`, `SnapshotReader` and `StateStore` against
real middleware/ZFS on one fresh `TrueNAS/pcc-test-<uuid>` dataset. It requires
Plex already RUNNING, checks durable snapshot intent, read-only snapshot access,
foreign dataset rejection and verified deletion. Success removes the disposable
dataset; failure prints its exact identity and retains it for inspection. Private
state is temporary in `/dev/shm`; no permanent operation logs are created by this
diagnostic. The fixed, test-only midclt adapter rejects production datasets,
recursive/forced deletion, app start/stop and rollback. Do not use this adapter in
the application runtime. This test does not exercise WSS authentication, archive
creation, Restore, user confirmation or container privileges.

Manual TrueNAS checks reported on 2026-11-03 verified the existing legacy archive's
gzip and regular-file readability and both archived Plex databases' integrity
using Plex SQLite on disposable copies. A separate synthetic dataset verified
snapshot isolation and rollback of file contents, mode and an extra file. The
initial diagnostic mishandled an empty successful snapshot-deletion response;
independent queries confirmed deletion and subsequent dataset cleanup. These are
environment checks, not full application Backup/Restore acceptance. The host smoke
test reached application snapshot creation, persisted intent, read-only access and
foreign-dataset rejection on the user's NAS. Deletion then exposed a second
diagnostic adapter parsing issue: midclt returned nonempty, non-JSON text. The
adapter now ignores mutation stdout and confirms state via strict JSON queries;
the second sandbox was subsequently removed after the user stopped Filebrowser,
whose mount namespace retained it. A rerun at commit
`54df4e8f64e8eec0f939d57f44cb2b84b8fc20d8` passed every snapshot-module check,
confirmed snapshot/dataset cleanup and observed Plex RUNNING. Filebrowser remains
stopped by user choice.


The opt-in host smoke flag `--archive-test` adds synthetic Plex-shaped files and
small SQLite fixture databases to the fresh sandbox. It uses the application
archive builder against the verified read-only snapshot, compares every file to
that snapshot, checks a byte-only export/return copy using full validation and
SHA256, and rejects a deliberately truncated copy. Diagnostic archive copies are
temporary in RAM; no production archive or permanent operation log is modified.
The user ran this host archive test at commit
`b8ca8e0d5c758a28abfa1e3d971ddf8e486840d4`: all checks passed, including confirmed
snapshot/dataset removal and Plex RUNNING. It does not exercise the Backup
coordinator, SMB access, Restore or database compatibility with Plex itself.


The optional `--backup-test` flag additionally runs the actual Backup coordinator
on the sandbox. Its isolated diagnostic `Plex Config/Logs`, archives, History and
private state live temporarily in RAM and are removed after the diagnostic. It
checks snapshot-only contents while the sandbox live file changes, publication,
terminal progress/state, the one-existing-copy decision and History clearing
without changing diagnostic log/archive bytes. It never uses production archives
or permanent user operation logs. The user ran this coordinator host test at
`9ad81c4f05ec32bace5e4438a1eea221d7cc4bf5`: every check passed, including
confirmed cleanup and Plex RUNNING. Application HTTP/WSS/container/SMB acceptance
remains separate.


### Opt-in sandbox Restore success with manual Plex stop

`python -m tests.host_restore_smoke --run-sandbox-restore-test` requires Plex
RUNNING initially and no Filebrowser-held mounts of disposable datasets. It uses
one fresh sandbox, real ZFS snapshots, the actual Restore coordinator, staging,
ConfigWriter/rsync, metadata comparison and SQLite integrity checks on synthetic
fixture databases. The code confirms the real RUNNING gate before writes, then
waits up to ten minutes for the user to stop Plex in Apps. It never calls app.stop
or app.start and leaves Plex STOPPED. Success confirms History/log/checkpoints,
staging/snapshot absence and dataset deletion. Diagnostic archive/log/state files
are temporary in RAM. Failure retains the sandbox and prints exact identities;
do not rerun until it has been investigated. This is not a Restore of production
Plex data, a Plex-specific SQLite compatibility test or deployment acceptance.
The user ran the success test at commit
`f06ce3d20e90aae5cb520dceb9f906e9e1ec63cf`: all checks passed, including
manual-stop gating, real rsync, fixture database integrity, History/log/state,
snapshot/staging cleanup and sandbox removal. Plex remained STOPPED.


The Restore diagnostic flag `--failure-test` requires Plex already STOPPED. It
injects a known failure after sandbox synchronization and an additional sandbox
file write, exercises the actual coordinator's scoped ZFS rollback, and verifies
recovered bytes, permissions/metadata and fixture database integrity. It requires
FAILED History/log reporting, RECOVERY_REQUIRED state, one retained emergency
snapshot and rejection of another snapshot. A passing failure diagnostic
intentionally retains that snapshot and sandbox for separately confirmed manual
cleanup; private diagnostic state/log/archive copies in RAM are removed. It never
removes that recovery point automatically. Unexpected failures or unverified
recovery cannot produce PASS. The user ran this diagnostic at commit
`d6de9a0e5b006008e9012a6a76d69ae3ccbd89a3`: rollback, metadata checks, FAILED
reporting, single-snapshot retention and blocking a second snapshot all passed.
The user subsequently confirmed manual deletion of that exact snapshot and
sandbox; independent queries confirmed both absent. Production WSS
authentication, least-privilege container
integration, reboot persistence and full app acceptance remain untested.


Backup execution independently requires confirmed RUNNING status for the exact
`plex` app, both before creating operation/log state and again immediately before
snapshot creation. STOPPED, transitional, unavailable, malformed or wrong-app
responses block execution without starting Plex. A loss of RUNNING confirmation
after preparation records a failed operation with its diagnostic log and creates
no snapshot/archive. The rule applies to new copies and confirmed overwrite;
stale archive choices and the single-copy decision still resolve before host
reads. These added checks have local regression coverage; the previous host
coordinator pass predates this additional guard. The restricted web runtime still
does not enable host writes or operational Backup/Restore routes.

### Explicit operation-submission boundary (not enabled in the restricted runtime)

`ExecutionGateway` accepts only fixed Backup/Restore request types. An explicitly
configured Web instance can expose `/api/backup/start` and `/api/restore/execute`
behind the existing credential-bound session and CSRF checks. Backup modes are
NEW, ANOTHER and OVERWRITE with explicit confirmation and exact displayed archive
identity for the latter two. Restore requires the validated name/digest and typed
RESTORE. Every request has a 32-character lowercase hexadecimal request_id; extra
fields, command strings, paths and dataset names are rejected. Current Plex state,
archive identities, operation/recovery blocks and readiness are checked before
submission. Admission does not mark progress/history successful.

No execution backend is supplied by the default runtime. A separately authorised backend
must durably deduplicate request_id together with the complete request payload,
reserve exclusive execution before returning `AcceptedOperation`, and repeat
identity/readiness checks under the coordinator lock. A restore request's queued
digest must still match the validation checkpoint before execution; Backup must
recount and check the confirmed identity. It must execute only the fixed Backup
or Restore coordinators and write progress to the same private state store.
The gateway cannot itself guarantee those backend responsibilities. Network loss
or a mismatched acceptance receipt returns an unconfirmed submission, with no
automatic retry. Browser methods validate the receipt against the request identity
and fixed status URL; they never interpret acceptance as completion.

`Web` defaults to no execution service; `prepare()` supplies none. The restricted
`TestApplication` additionally rejects any Web instance configured with one and
continues blocking host-write routes. No privilege, API credential, general root
shell, default worker architecture or live host action is added. The approved UI
layout is preserved; execution controls require an explicitly configured backend
and its host acceptance tests. HTTP and browser-client tests here use an inert
submission stub; they do not exercise real asynchronous host execution.

### Durable admission and replay protection

`ExecutionJournal` adds a private `execution.sqlite3` ledger for a future
execution backend. Admission commits under SQLite BEGIN IMMEDIATE/FULL sync,
allows one queued/running/recovery request, and returns the original receipt for
an identical request_id/fingerprint even after completion or process recreation.
Changed mode, archive identity, Restore digest or kind cannot reuse that ID.
Concurrent claims have one execution owner; only its private token can finalize
the claim. Only the token hash is stored. The ledger contains request fingerprints,
IDs, kind, state and timestamps, not archive names, request bodies, passwords,
commands or operation logs. Web History clearing neither removes deduplication
records nor regenerates deleted History entries from them.

The execution owner's explicit startup reconciliation, guarded by the operation
lock, turns queued/running claims into RECOVERY_REQUIRED and invalidates old
ownership. Nothing is automatically replayed. Confirmed closure of an interrupted
admission additionally requires the coordinator to be idle/terminal with no
recorded snapshot, publication intent or private backup/restore workspace. This
method never deletes those resources or declares the operation successful.
Journal outcome finalization still requires the backend to independently verify
the actual coordinator result; ledger state alone proves no data integrity.

`ExecutionGateway` can receive an explicit receipt lookup (for example
`journal.lookup`). After session/CSRF and strict payload checks, matching replays
return the existing receipt before re-evaluating live readiness. Thus a lost reply
cannot cause a resubmission when the first operation has already changed archive
counts, Plex status or operation state. Conflicting payloads are rejected. A new
request still passes every current readiness check. No lookup/journal is supplied
by the default restricted runtime, and no execution service is enabled. This
ledger itself does not execute work, grant host privileges or serialize work
for automatic restart. See the optional runner below; iXVolume persistence on the
NAS remains untested.


### Optional asynchronous execution runner (not installed or enabled)

`ExecutionWorker` connects fixed typed requests to actual Backup/Restore
coordinators on a non-daemon thread. Trusted deployment must supply fixed API,
dataset, archive/state directories and coordinator factories. No host credential,
mount, root privilege, arbitrary command interface or default runtime wiring is
provided. The runner checks coordinator type, API/dataset/path scope and private
state/history/progress storage before using it. Admission repeats Plex status,
archive-count/identity and Restore digest/checkpoint checks under the operation
lock. It durably reserves/claims the request before returning its receipt.

One lock is held from admission through coordinator reporting and journal
finalization. A single-use, thread/path-bound guard lends that reservation to the
coordinator without releasing/reacquiring it. An explicit handoff prevents failed
thread startup from executing after the parent releases its lock. Matching
replays return the existing receipt without starting another thread. Shutdown
rejects new work and waits for owned threads. There is no automatic restart of
queued/interrupted jobs; the execution owner explicitly calls
`worker.reconcile_startup()` before accepting traffic, and this refuses live work.

Operation JSON now optionally records `execution_request_id` (legacy rows load
with None). The coordinator binds it when execution begins; runner success also
requires matching request/kind/archive, verified SUCCESS, no snapshot/publication
intent/private workspace and completed progress. Unexpected interruptions remain
RECOVERY_REQUIRED. Journal/reporting uncertainty cannot become a claimed success.
`/api/operation` can expose whitelisted execution status with nanosecond timestamps
as decimal strings and an explicit binding flag, never private ownership tokens
or request fingerprints. An admitted job awaiting recovery also blocks ordinary
Restore validation/cancellation and archive deletion. Historical UI success is
suppressed for a different or unconfirmed admitted job without changing layout.

Local tests exercise the runner with real coordinators, tar/staging and private
SQLite stores using a fake scoped host API. They cover HTTP admission/status,
background lock ownership, replay, scoped factories, Restore failure retention,
startup/shutdown and stale success suppression. This runner has not been tested
on the NAS, in an unprivileged installed container, or across an actual reboot.
Host integration and its permission design and final app installation remain to
be completed. The restricted runtime still
rejects any execution backend and grants no new capabilities.


### Confirmed browser Backup/Restore submissions

The approved panel views now wire their existing buttons to fixed submission
requests, gated by server capabilities and current state. Backup creates a dated
copy directly for zero or multiple archives; exactly one opens a themed yellow
notification dialog offering another copy or confirmed replacement. The dialog
retains the displayed full archive identity (including exact decimal inode and
nanosecond values) and rejects stale choices. Restore exposes execution only for
the validated selected archive/digest, confirmed STOPPED Plex and an enabled
backend. Its themed dialog requires literal RESTORE and rechecks the displayed
selection before submission. Read-only installations keep creation disabled and
execution hidden; no privileged runtime is activated by these UI changes.

The shared submission controller retains an immutable payload and cryptographic
request identity for an uncertain response. It never retries a POST automatically.
Explicit Check Status reads the authenticated exact-request ledger lookup;
explicit Retry Same Request resends the original payload/identity so durable
backend deduplication applies. A missing admission at one instant remains
unconfirmed because an earlier POST may still complete. Late responses cannot
replace a newer request or downgrade confirmed completion. Leaving a view cancels
browser reads, not server-owned work. No token or ownership hash is displayed.

`GET /api/execution/status?request_id=<32 lowercase hex characters>` is available
only with an explicitly configured execution service/status lookup. It returns a
whitelisted matching execution record or found=false; malformed, duplicate or
extra query fields are rejected. A matching record can be inspected even after a
different job becomes the latest. The default restricted runtime blocks this
route. English and Polish notices distinguish sending, accepted, running,
uncertain, failed and recovery states without invented progress. New notification
actions wrap on narrow screens. Layout, themes and status-dot styling are retained.

Local Python/JavaScript tests cover these control flows and request boundaries.
The new enabled dialogs and retry actions have not yet been exercised in native
browsers or on the user's NAS; full browser/host/container acceptance is still
required before enabling the deployed execution backend.


### Native execution-dialog browser suite

`python tests/execution_ui_e2e.py` exercises the actual mounted Backup/Restore
views with Playwright and a fully intercepted, in-memory API. The workflow runs
it in Chromium, Firefox and Microsoft Edge after installing disposable browser
tools. It covers English/Polish, Light/Dark/System and desktop/narrow viewports;
these narrow viewports are not physical mobile-device tests. Every browser HTTP
request is intercepted and off-origin requests are aborted. No NAS dataset,
Docker fixture, privileged runtime or real execution backend is used by this
suite. The injected CSRF value and submissions are UI fixtures, not an auth test.

Checks include themed three-pixel yellow dialog borders, light-theme black
headings, popup overflow, exact large archive identities, explicit overwrite,
lost-reply status checking and same-ID retries with one simulated execution.
The uncertainty scenario temporarily hides the latest-operation read until an
explicit exact-request check or retry, so normal successful polling cannot resolve
the simulated uncertainty before the user-action assertion.
Restore is blocked in the UI while Plex is simulated RUNNING; confirmation must
be RESTORE, a changed validation digest invalidates an open dialog, and the
selected current digest is sent once after re-confirmation. The UI then presents
the corresponding simulated completion. Screenshots (including failures) are
collected by the existing browser artifact step. The suite does not claim real
backup integrity or recovery, TLS/auth checks, Safari or physical-device coverage.

The new suite passed in actual Chromium, Firefox and Microsoft Edge on the
Linux CI runner in run `41729090939` for commit
`d55d54bf7e812f5b3583f478fdde86139d30f019`. These are intercepted-API UI
tests, not live NAS execution or native Apple/mobile execution-dialog tests.
Installer packaging remains manual-only; these workflow changes add tests only.


### Browser CI follow-up: bootstrap and loaded-list timing

Inspection of run `41727527763` for commit
`2445550da5c8935de52e9060e321f7a281063c31` found that the unit workflow passed;
the existing Chromium, Linux Firefox, macOS Firefox and Android jobs/checks also
passed. Edge failed before sign-in because initial JavaScript-module GETs had
ERR_NETWORK_CHANGED; Safari macOS failed an immediate archive-list overflow
assertion after language remount. Its failure HTML/screenshot subsequently
contained 14 rows and a visible working scrollbar, identifying the unloaded-list
race rather than evidence of a missing scrollbar. These are partial results,
not an all-browser pass; the new execution-dialog suite was not reached by the
failed Linux job.

The local-fixture navigation helper now optionally waits for the login input and
allows at most three root GET attempts only after a matching transient initial
navigation/local asset failure. It refuses retries after any observed non-GET/HEAD
request, for unrelated origin/API failures, or for product failures without that
transient evidence. Both login-context bootstraps use this check; application
POSTs are never retried. Apple tests now await the full archive/history fixture
rows and actual overflow before testing scrollTop; they retain the overflow and
scroll assertions. The intercepted execution-UI fixture now uses the real
pcc-main geometry class. Run `41729090939` confirmed the corrected Linux browser
checks, all three execution-dialog browser suites, macOS Firefox/Safari and
Safari in iOS/iPadOS simulators. The separate application unit workflow also
passed. This is not physical-device or full-deployment acceptance.

The Android-system job failed before sign-in with ERR_INTERNET_DISCONNECTED
when Chrome navigated to the emulator gateway. Its fixture now uses an ADB
reverse tunnel to the same host-loopback HTTPS port, retaining the explicit
CI-only/emulator-only checks. The mapping uses --no-rebind and is removed on
normal exit or test failure; no application request is retried. Host-side health
checks still validate the synthetic certificate normally. The revised Android
transport has local regression checks but still requires a new emulator CI pass.


### Windows and Linux Mint retail-browser UI checks

`.github/workflows/desktop-browsers.yml` adds three independent native Windows
jobs for installed Microsoft Edge, Mozilla Firefox and Google Chrome, plus two
Mint-userspace container jobs for Firefox and Google Chrome. Installed browser
binaries are required explicitly: the suite does not substitute Chromium for
Chrome or Playwright Firefox for retail Firefox. Selenium manages matching
drivers. `environment.json` records actual OS/browser capabilities alongside
screenshots, with failure HTML when available.

`tests/desktop_e2e.py` loads actual product HTML/CSS/modules against a disposable
loopback HTTPS fixture (`desktop_fixture.py`) with synthetic API data. It checks
all five panels, EN/PL, Light/Dark/System, wide/narrow browser windows, 13 archives,
20 history entries, actual list overflow/scrolling, selected rows, light-theme
black headings, Plex status transitions, password-dialog opening/cancellation,
History-clear cancellation, sign-out, one-copy Backup choice and typed Restore
confirmation/completion. The latter operations are fixture receipts only: no
snapshot, archive, production authentication or NAS operation is exercised here.
A separate verified-TLS health probe trusts only the generated fixture cert;
WebDriver accepts that disposable identity without changing product TLS policy.

Windows CI uses Windows Server 2025, not a Windows 11 desktop. Mint CI uses the
pinned `linuxmintd/mint22.3-amd64` userspace with Firefox, Chrome and Mint metadata,
sharing the runner kernel; it is not a complete Mint Xfce desktop session or VM.
Chrome's sandbox flag is limited to this disposable Mint CI container. The
suite remains runnable on actual Windows 11 and Linux Mint desktops, as a
regular user, to close those environment-specific gaps. Native file pickers,
physical desktop/GPU integration and real NAS acceptance remain separate checks.

Developer commands from the source checkout (these install test tools in a
virtualenv, not PlexConfigControl on the client OS):

Windows PowerShell, with the requested retail browser already installed:

```powershell
py -3 -m venv .venv-pcc-ui
.\.venv-pcc-ui\Scripts\python.exe -m pip install 'selenium>=4.27,<5' 'cryptography>=44'
$env:PCC_DESKTOP_TARGET = 'windows'
$env:PCC_DESKTOP_BROWSER = 'firefox' # Repeat with chrome and msedge.
.\.venv-pcc-ui\Scripts\python.exe tests/desktop_e2e.py
```

Linux Mint, with Firefox/Google Chrome already installed:

```sh
python3 -m venv .venv-pcc-ui
.venv-pcc-ui/bin/pip install 'selenium>=4.27,<5' 'cryptography>=44'
PCC_DESKTOP_TARGET=mint PCC_DESKTOP_BROWSER=firefox .venv-pcc-ui/bin/python tests/desktop_e2e.py
PCC_DESKTOP_TARGET=mint PCC_DESKTOP_BROWSER=chrome .venv-pcc-ui/bin/python tests/desktop_e2e.py
```

No new browser/OS pass is claimed until CI completes. The preceding revision
`f6a104b60576d970fcdaee498d9bfb9f789ce4a6` completed both application-tests run
`41731369439` and browser run `41731369736` successfully, including the corrected
Android-system transport. Installer packaging remains manual-only and is not
part of this desktop workflow.


### Opera on Windows, macOS and Mint

The desktop workflow additionally installs and launches retail Opera on native
Windows/macOS runners and in Mint userspace. `tests/opera_e2e.py` uses the
installed Opera executable through Playwright's Chromium-compatible automation;
it never falls back to downloaded Chromium. The live user agent must identify
Opera (`OPR/`) or the check fails. Tests use a fresh temporary browser profile,
never a user's existing profile. OS, executable, browser version and user agent
are recorded with screenshots.

Opera checks all five actual panel views over the disposable HTTPS fixture,
EN/PL, Light/Dark/System, wide/narrow viewports, archive/history scrolling and
selection, black headings in Light, Plex status transitions, password dialog and
sign-out. It also runs the existing intercepted-API execution-dialog scenarios:
one-copy Backup choice, lost submission reply, explicit same-request retry,
read-only receipt lookup, typed Restore confirmation, stale-validation rejection
and synthetic completion. These are UI compatibility checks, not actual backups
or restores on a NAS. Chromium-compatible automation of a custom browser can
itself fail; only a completed job establishes coverage for its recorded version.
The same Windows Server/Mint-userspace limitations described above apply.

To run against an already-installed Opera as a regular desktop user, install
`playwright>=1.56,<2` and `cryptography>=44` in the test virtualenv, set
`PCC_DESKTOP_TARGET` to `windows`, `macos` or `mint`, and run
`python tests/opera_e2e.py`. No Playwright browser download is needed.

The first Windows desktop run (`41752659398`, revision `6f2dab92`) reached the
actual browsers but exposed an incorrect test selector for Restore's archive
list: it uses `data-archive-list`, while Backup uses `data-archives`. Both the
Selenium and Opera test paths now use the actual view-specific selectors; checks
still require 13 rows and real overflow. New Opera/desktop results remain pending
until the updated jobs complete. No installer is built by this workflow.


### Installation-time Plex Configuration Storage discovery

The installer-side `plex_storage.discover_plex_storage` reads the installed Plex
app's `storage.config` setting and the actual `/config` mount reported by
`app.query`, then resolves its filesystem through `filesystem.statfs`. Both
ixVolume and Host Path are recognized; no pool, dataset or ix-apps mountpoint is
hardcoded as the Plex source. `/data`, logs and transcode mounts are not mistaken
for configuration. ACL-enabled Host Path settings use their configured ACL path.
The result retains only storage type, config source, dataset, dataset mount and
relative path, never the complete app config (which may contain a claim token).

This belongs to installation configuration, not a new Settings panel/control.
The installer form model always offers `manual_plex_config_path` when automatic
detection fails, with EN/PL labels and an explicit Check path action. Supplying
`manual_source` bypasses the app.config read, but still verifies the actual Plex
/config mount and its ZFS identity. A manually entered path is never permission
to use a different directory or to proceed without verification. The installer
can accept corrected input and repeat checks without automatically changing ACLs.

`installation_storage.plan_storage` performs discovery before output-directory
setup. `create_storage` rechecks its immutable plan immediately before exclusive
Plex Config/Logs creation using the existing no-adoption/no-permission-repair
storage routines. Repeated reads detect observed storage changes; they do not
lock external TrueNAS app edits. The worker must recheck storage binding before
every operation; discovery alone never enables execution. Ambiguous/missing
mounts, unsupported settings, non-ZFS storage and changed identities fail closed.
A stopped Plex can be inspected if TrueNAS still reports its container mounts;
otherwise manual entry still requires those mounts to be verifiable, without
automatically starting Plex.

A Host Path subdirectory in a shared dataset is identified, but the current
whole-dataset emergency rollback cannot safely accept it for installation.
The gate returns DEDICATED_PLEX_DATASET_REQUIRED before directory creation rather
than risking unrelated files. Dedicated dataset roots work for either storage
type. No storage is moved, renamed, snapshotted or assigned different permissions
by discovery. Protected PBS storage is rejected. These are tested installation
components and a form model; the final TrueNAS installation form/deployment
integration and host acceptance remain unfinished. The restricted WWW runtime
has not gained arbitrary app.config/filesystem API access.

### Installer storage flow and observed desktop results

`InstallationStorageFlow` now joins read-only detection/manual retry, output-name
inspection, exact-plan confirmation and one folder-creation attempt. A fresh
check invalidates the previous revision. Unconfirmed or stale confirmations do
not write. The actual create rechecks Plex storage and the exclusive destination
creation still refuses an existing folder. An existing Plex Config is reported
as RENAME_REQUIRED already during planning, before READY; the old contents and
permissions remain unchanged. After the user renames it manually, a fresh check
may proceed. Unexpected errors after a possible mkdir enter REVIEW_REQUIRED,
retain any partial folder and do not permit automatic retry/adoption. COMPLETE
also cannot create a second folder on a repeated confirmation. The controller
returns only a copied form model with EN/PL messages; trusted plans/API clients
remain internal. This remains installer-side integration code, not a mounted
public WWW setup endpoint or a completed TrueNAS installation form.

Browser run `41753807162` (revision `2c3b9cb8`) passed installed retail Chrome,
Firefox and Edge on Windows Server 2025, Chrome/Firefox in Mint userspace, and
Opera on macOS and Mint userspace. The Windows Opera job launched actual Opera
but timed out awaiting the login input, with no reported JavaScript error. The
Opera fixture now uses the existing bounded read-only localhost-bootstrap helper
and captures failed requests/console errors plus failure HTML. It does not retry
API mutations or disable product checks; a subsequent Windows Opera pass is
still required. These UI results do not establish live NAS execution acceptance.

### User-selected archive location and names at installation

This supersedes earlier fixed Plex Config / TrueNASPlexConfig naming requirements.
Installation configuration now has three independent editable inputs:

- Backup folder location: a manually entered existing absolute host directory on
  any accessible pool/dataset; there is no default pool or guessed path.
- Backup folder name: defaults to `Plex Backup` when omitted/empty; custom portable
  folder names (including spaces and Unicode letters) are supported.
- Archive prefix: defaults to `PlexConfig` when omitted/empty, or e.g. `Dupa`.

Logs always go in the fixed `Logs` child of the chosen backup folder. Every new
archive always ends with `_YYYY.MM.DD_HH.MM.SS.tar.gz`, using Europe/London time.
For example `/mnt/ArchivePool/Backups` plus folder `Moje kopie` and prefix `Dupa`
produces `/mnt/ArchivePool/Backups/Moje kopie/Dupa_2026.11.04_10.20.30.tar.gz`
and `/mnt/ArchivePool/Backups/Moje kopie/Logs/`.

The selected folder is created exclusively under the existing parent; setup never
creates a pool/dataset, renames/adopts an existing output folder or resets ACLs.
Selecting a different location/name or prefix requires a fresh checked plan and
invalidates its previous confirmation. Invalid/traversing names are rejected
before host probes. Prefixes use 1–64 ASCII letters/digits/underscore/hyphen,
starting with a letter/digit; the timestamp and extension cannot be overridden.
Folder validation rejects separators, traversal and Windows-reserved names.

Naming choices are saved as a private mode-0600 `output-naming.json` in application
state (iXVolume), never in the output/Logs folder. The trusted installation flow
must receive that state directory to complete nondefault naming. Save failures
leave setup in REVIEW_REQUIRED; existing choices cannot be silently overwritten.
Backup loads the persisted prefix at construction unless trusted deployment code
explicitly supplies one. Invalid saved settings fail closed rather than reverting
to defaults. The output mount/path still has to be bound by deployment; a naming
record alone never grants access or relocates a directory.

Backend listing, publication, validation selection/outcomes and frontend Backup/
Restore/recovery name checks recognize custom dated names, the new PlexConfig
default and existing TrueNASPlexConfig dated archives. They are not renamed when
preferences change. Full content/database validation and restore confirmations
remain required; recognizing a filename does not establish archive integrity.
Checks include real synthetic archive creation from both default/custom saved
prefixes, private naming persistence, folder identity checks, two manually chosen
pool/dataset locations, unchanged Logs layout, and frontend selection/outcomes.
The final TrueNAS installation form/deployment integration remains unfinished;
these inputs are now in its tested installer model and storage/Backup code.

### Accepted installer wording and non-writing path preview

Installer fields now use the approved Polish wording: “Miejsce przechowywania
kopii zapasowych Plex”, with help explaining a dataset root or an existing child
folder; “Nazwa nowego folderu na kopie i logi”; and “Początek nazwy plików kopii
zapasowych”. Equivalent English copy is included. Defaults remain Plex Backup /
PlexConfig, with fixed Logs and timestamp/extension. The Polish format legend uses
GG for the hour while actual files retain the same two-digit 24-hour timestamp.

`installation_preview` and the flow's `edit` action produce full output-folder,
Logs and example-archive paths without API calls or filesystem probes. These are
explicitly marked as examples, unchecked and uncreated. Editing an input clears
the prior plan/revision and disables creation immediately; an old confirmation
cannot create at the previous location. Check results retain current field values.
Only successful checks mark a preview checked, and only confirmed folder creation
marks it created; the archive remains an example, never a claimed backup. Errors
clear stale previews or checked state. These are the installer controller/form
model; the final TrueNAS install-form/deployment binding remains unfinished.

The latest Windows Opera logs showed ERR_CONNECTION_REFUSED for parallel static
asset GETs, rather than JavaScript errors. The disposable HTTPS desktop fixture
now uses a bounded listen backlog of 64 instead of the server default of five.
A local regression test opens 16 queued TCP connections before TLS handshakes to
exercise that burst condition. This is a test-server change, not a product TLS,
permission or retry-policy change. A subsequent Windows Opera pass is required
before treating it as a verified correction.

### Installer form component and explicit adapter boundary

`static/installation-view.mjs` now renders the actual installer storage form using
the trusted initial field model: accepted descriptions, editable parent/folder/
prefix, full local path preview, fixed Logs, manual Plex-source fallback, checked
source/dataset, and a native folder-creation confirmation dialog. English/Polish
copy and scoped Light/Dark/System styling are included. It is a separate component;
the approved five-tab application has not been changed or given setup privileges.

`installation-controller.mjs` accepts an injected adapter with `check(inputs,
signal)` and `create({revision,confirmed:true})`. It does not select an endpoint or
host command. The future trusted installer host must bind those calls to its own
`InstallationStorageFlow`, supply a fresh UNVERIFIED initial model, hold the
private API/state configuration, and enforce authentication/origin/CSRF/session
ownership before exposing any transport. No new public setup route has been
registered in Web/TestApplication, and no privileged backend has been enabled.
The final TrueNAS install-form/deployment integration remains unfinished.

Typing updates only a local example preview, never probes the host. Editing
invalidates prior readiness; creation needs a checked response whose output path,
folder name, prefix and revision match current inputs. Confirmation displays the
exact folder/Logs/prefix and can be cancelled without a write. Fields are locked
while checking/creating. Repeated clicks cannot submit creation twice. Unknown
write outcomes block further writes/checks until review; leaving the view does
not cancel or retry an already submitted write. Paths/error text are inserted as
text, not HTML. Completion reports configured storage, never a completed backup.

Unit tests cover custom/default names, London timestamps, Unicode folders,
manual fallback, stale/mismatched plans, malformed/lost receipts and disposal
races. `tests/installation_ui_e2e.py` adds actual-component tests in Chromium,
Firefox and Edge with a fully intercepted adapter, EN/PL and desktop/narrow
Light/Dark/System cases. It checks previews, manual entry, cancellation, changed
pool path, single creation, text-only source rendering and explicit uncertain
outcomes. These browser results must be read from CI; local syntax/unit checks
are not a native-browser pass and synthetic receipts never create host folders.
Installer packaging remains manual-only.

### Authenticated installation service and durable creation receipt

`installation_service.InstallationService` now binds the installer flow to real
private-state Sessions. Its `check(token, csrf, payload)` accepts only parent,
manual_source, folder_name and archive_prefix; `create(token, csrf, payload)`
accepts only an exact checked revision and literal confirmed=true. Callers cannot
supply API methods, commands, URLs or datasets. The trusted deployment supplies
the API client and initialized account/session state. Another session cannot
consume an in-memory checked revision or read its nonce. Logout/credential changes
invalidate authorization through Sessions. Public methods return fixed safe error
codes instead of arbitrary private exception text.

The service holds the existing operation file lock and refuses recorded core
operations/recovery/publication before setup. A private mode-0600
`installation.sqlite3` commits STARTED before folder creation. Only a confirmed
flow result and persisted receipt become COMPLETE. Restart with STARTED, unknown
or corrupt receipt remains REVIEW_REQUIRED: no automatic replay, deletion or
folder adoption. A repeated exact confirmation by the same authenticated owner
of a completed request returns its durable receipt without creating again. A
known pre-write rejection (existing folder or failed source recheck) is NO_WRITE,
so an explicit new check can proceed after correction. Two service instances with
different checked plans cannot both create destinations in the same private state.

Tests use actual sessions/CSRF and temporary directories: custom names/Logs,
private naming persistence, receipt lookup after service restart, wrong/expired
sessions, stale payloads, competing instances, existing-folder rejection, core
recovery/busy locks, simulated interruption before mkdir and receipt-persistence
failure after real folder creation. No test connects to the user's NAS.

This adapter is deliberately not mounted in Web/TestApplication and enables no
privileged runtime or public setup endpoint. Its transport still needs explicit
HTTPS, origin/body limits, session-cookie handling and deployment ownership; the
final TrueNAS installation binding remains unfinished. In-memory checked plans
are not restored after a restart. State requiring review must not be bypassed by
silently replacing the service/record or choosing another folder.

Run `41758555734` for revision `4719f9e1` confirmed the installer-component suite
in actual Linux Chromium, Firefox and Microsoft Edge (intercepted adapter only).
The Windows Opera job in run `41758555715` instead failed because Chocolatey's
feed returned HTTP 504 and installed no browser. The disposable Windows setup now
allows at most three package-install attempts and verifies an actual installed
Opera executable after each. These retries are limited to ephemeral CI browser
installation; application POSTs and host operations are not automatically retried.
A new Opera run is still required to verify the browser itself.


### User-requested restricted test package — 4 November 2026

Kris explicitly requested an installer from the current code. This supersedes the
earlier cancellation for this one package only. The existing tested-image job
may now package on workflow_dispatch or the exact one-off commit message
`Package requested restricted installer 2026-11-04 5cc12c8a`. Ordinary pushes still
run tests without producing installer packages. Packaging follows the unit,
HTTPS/restart and Linux browser/component checks in the test-image job.

The package remains the restricted test runtime: no host Backup/Restore,
snapshot writes or archive deletion, and no mounted storage-setup form. Updated
EN/PL instructions give a first installation with only a private new iXVolume,
no live Plex config, API credentials or Docker socket. BUILD-INFO includes the
source commit and image ID/architecture. This is an explicitly requested test
artifact, not a claim of production readiness or full installer integration.
