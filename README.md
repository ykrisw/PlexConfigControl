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


Installer packaging may also be explicitly requested by a main-branch push whose
commit message includes `[test-installer]`. Normal pushes still run tests without
producing another installer. Packages include BUILD-INFO.txt with the exact source
commit and checksums for the image, guides and build information. Restricted test
mode and disabled host execution remain unchanged.
