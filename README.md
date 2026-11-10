# PlexConfigControl 1.0.10

PlexConfigControl is an app for backing up and restoring your Plex Media Server configuration on TrueNAS SCALE. Backups are stored in a folder you choose on the NAS. If you share that folder via SMB, you can move archives between the NAS, your computer, and other locations.

## Download the installer

- [Polish installer ZIP and guide](https://raw.githubusercontent.com/ykrisw/PlexConfigControl/main/release/PlexConfigControl_Instalator_Windows_macOS_Linux.zip)
- [English installer ZIP and guide](https://raw.githubusercontent.com/ykrisw/PlexConfigControl/main/release/PlexConfigControl_Installer_Windows_macOS_Linux_EN.zip)

Both ZIPs contain the same app and installer launchers for Windows, macOS, and Linux. The package you choose determines the language of the installation wizard and guide. The app itself runs on TrueNAS.

## How it works

1. **Backup** — Start a backup from the web panel. Plex keeps running while the app creates a `.tar.gz` archive from a ZFS snapshot and verifies it. You can choose a name for each archive. The backup date is added to the filename automatically.
2. **Restore** — Select an archive and verify it. Then stop Plex manually and start the restore. When the restore finishes, start Plex again. Tags, descriptions, and artwork stored in the backed-up configuration return to their state at the time of the backup.
3. **History** — See detected archives and operation results, along with the date of each event. You can download logs from the web panel.

**License** · [MIT](LICENSE)

PlexConfigControl 1.0.10
