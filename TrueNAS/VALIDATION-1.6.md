# PlexConfigControl 1.6 — confirmed working baseline

Platform: **TrueNAS SCALE x86-64**. Confirmation date: **17 November 2026**.

## Owner verification

The project owner reported successful backup creation and configuration restore on this platform. The owner also reported no current objections to the interface appearance. This records the result on the owner's installation.

| Check | Result | Evidence |
| --- | --- | --- |
| Create a Plex configuration backup | Passed | Owner report, 17 November 2026 |
| Restore a configuration backup | Passed | Owner report, 17 November 2026 |
| Current interface appearance | Accepted for this baseline | Owner reported no current objections |

## Automated verification

The linked build completed successfully, including browser checks in Chromium, Firefox and WebKit. Archive-label regressions cover the previous-archive/new-backup case and full archive names before validation and restore progress, in Polish/English and both themes.

## Exact downloadable package

- File: `PlexConfigControl_TrueNAS_x86-64v1.6.zip`
- SHA-256: `c224e879853b8b30b2c7693c179e53a73a4aa5d63597ddd4776cc83b78185d03`
- Size: 69056130 bytes
- Application source commit: [`3971b155a30a042c7f99e39bf31279765b606a1a`](https://github.com/ykrisw/PlexConfigControl/commit/3971b155a30a042c7f99e39bf31279765b606a1a)
- [Successful build and checks](https://github.com/ykrisw/PlexConfigControl/actions/runs/44165465724)
- [Download the confirmed package](https://github.com/ykrisw/PlexConfigControl/releases/download/v1.6/PlexConfigControl_TrueNAS_x86-64v1.6.zip)
- [Machine-readable release record](RELEASE-1.6.json)

## Maintenance

Keep this package and its checksum as the 1.6 reference. Documentation-only updates must not rebuild or replace these binaries. Later application changes require their own verification before replacing a downloadable package. The release source tag and the `main`/`master` documentation identify this baseline; the manifest records the exact application commit used to build the binary.

Installation instructions and licensing remain linked from [README](README.md). Plex configuration and user-selected archives/logs are user data; uninstalling the application does not mean deleting those backups.
