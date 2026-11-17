# PlexConfigControl 1.6

PlexConfigControl is an app for backing up and restoring your Plex Media Server configuration on TrueNAS SCALE and supported QNAP QuTS hero systems. Backups are stored in a folder you choose on the NAS. If you share that folder via SMB, you can move archives between the NAS, your computer, and other locations.

## TrueNAS SCALE — installer 1.6

[**Download for TrueNAS SCALE 1.6 — English / Polski**](https://github.com/ykrisw/PlexConfigControl/releases/latest/download/PlexConfigControlTrueNAS_1.6.zip)

One ZIP contains graphical installers for Windows x64, macOS Apple Silicon (M1 or later), and Linux x64. Extract it and open the installer for your computer. Choose **English** or **Polski** in the first window. Both installation guides are included. The app itself runs on TrueNAS. The same installer can update an existing installation.

## QNAP / QuTS hero — installer 1.6

[**Download for QNAP QuTS hero 1.6 — x86_64 (.qpkg)**](https://github.com/ykrisw/PlexConfigControl/releases/download/v1.6/PlexConfigControlQuTShero_1.6.qpkg)


The QNAP installer is a separate `PlexConfigControlQuTShero_1.6.qpkg` package for x86-64 QuTS hero. Install it manually in QNAP App Center. It includes its own Python and GNU tar, QNAP sign-in with TOTP, snapshot Backup, and journaled Restore with manual Plex stop and retained-configuration review. It is not the TrueNAS desktop installer. The QNAP package is distributed separately from the TrueNAS desktop ZIP. Check against `SHA256SUMS_QNAP` in the release. ARM and plain QTS are unsupported by this build. See [QNAP installation, compatibility and reproducible build notes](deploy/qnap/README.md).

## How it works

1. **Backup** — Start a backup from the web panel. Plex keeps running while the app creates a `.tar.gz` archive from a ZFS snapshot and verifies it. You can choose a name for each archive. The backup date is added to the filename automatically.
2. **Restore** — Select an archive and verify it. Then stop Plex manually and start the restore. When the restore finishes, start Plex again. Tags, descriptions, and artwork stored in the backed-up configuration return to their state at the time of the backup.
3. **History** — See detected archives and operation results, along with the date of each event. You can download logs from the web panel.

**License** · [MIT](LICENSE)

PlexConfigControl 1.6
