# PlexConfigControl 1.0.5

PlexConfigControl is an app for backing up and restoring your Plex Media Server configuration on TrueNAS SCALE. Backups are stored in a folder you choose on the NAS. If you share that folder via SMB, you can move archives between the NAS, your computer, and other locations.

## TrueNAS SCALE — installer 1.0.5

[**Download for TrueNAS SCALE 1.0.5 — English / Polski**](https://github.com/ykrisw/PlexConfigControl/releases/latest/download/PlexConfigControl_Installer_Windows_macOS_Linux_PL_EN.zip)

One ZIP contains graphical installers for Windows x64, macOS Apple Silicon (M1 or later), and Linux x64. Extract it and open the installer for your computer. Choose **English** or **Polski** in the first window. Both installation guides are included. The app itself runs on TrueNAS. The same installer can update an existing installation.

## QNAP / QuTS hero — installer 1.0.5

The QNAP installer is a separate `PCC_1.0.5_x86_64.qpkg` package for x86-64 QuTS hero. Install it manually in QNAP App Center. It includes its own Python and GNU tar, QNAP sign-in with TOTP, snapshot Backup, and journaled Restore with manual Plex stop and retained-configuration review. It is not the TrueNAS desktop installer. The QNAP package is distributed separately from the TrueNAS desktop ZIP.

## How it works

1. **Backup** — Start a backup from the web panel. Plex keeps running while the app creates a `.tar.gz` archive from a ZFS snapshot and verifies it. You can choose a name for each archive. The backup date is added to the filename automatically.
2. **Restore** — Select an archive and verify it. Then stop Plex manually and start the restore. When the restore finishes, start Plex again. Tags, descriptions, and artwork stored in the backed-up configuration return to their state at the time of the backup.
3. **History** — See detected archives and operation results, along with the date of each event. You can download logs from the web panel.

**License** · [MIT](LICENSE)

PlexConfigControl 1.0.5
