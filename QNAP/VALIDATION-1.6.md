# PlexConfigControl 1.6 — confirmed working baseline

Platform: **QNAP QuTS hero x86-64**. Confirmation date: **17 November 2026**.

## Owner verification

The project owner reported successful backup creation and configuration restore on this platform. The owner also reported no current objections to the interface appearance. This records the result on the owner's installation.

| Check | Result | Evidence |
| --- | --- | --- |
| Create a Plex configuration backup | Passed | Owner report, 17 November 2026 |
| Restore a configuration backup | Passed | Owner report, 17 November 2026 |
| Current interface appearance | Accepted for this baseline | Owner reported no current objections |

## Automated verification

The linked build completed successfully, including browser checks in Chromium, Firefox and WebKit. Archive-label regressions cover the previous-archive/new-backup case and full archive names before validation and restore progress, in Polish/English and both themes.

The actual packaged runtime also passed fresh setup, panel login, restart, profile/account checks, guarded uninstall, released-port verification and clean reinstall in a disposable CI environment. These lifecycle checks are CI results, not additional owner-reported NAS tests.

## Exact downloadable package

- File: `PlexConfigControl_QuTShero_x86-64v1.6.qpkg`
- SHA-256: `772687998b1a5520260dba43551a5715aabaca8280b0f2d30f7f9960060f8568`
- Size: 30440010 bytes
- Application source commit: [`3971b155a30a042c7f99e39bf31279765b606a1a`](https://github.com/ykrisw/PlexConfigControl/commit/3971b155a30a042c7f99e39bf31279765b606a1a)
- [Successful build and checks](https://github.com/ykrisw/PlexConfigControl/actions/runs/44165465671)
- [Download the confirmed package](https://github.com/ykrisw/PlexConfigControl/releases/download/v1.6/PlexConfigControl_QuTShero_x86-64v1.6.qpkg)
- [Machine-readable release record](RELEASE-1.6.json)

## Maintenance

Keep this package and its checksum as the 1.6 reference. Documentation-only updates must not rebuild or replace these binaries. Later application changes require their own verification before replacing a downloadable package. The release source tag and the `main`/`master` documentation identify this baseline; the manifest records the exact application commit used to build the binary.

Installation instructions and licensing remain linked from [README](README.md). Plex configuration and user-selected archives/logs are user data; uninstalling the application does not mean deleting those backups.
