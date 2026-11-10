# PlexConfigControl 1.0.10 — installation

Extract the ZIP and open the installer for your computer.

| Computer | Open |
|---|---|
| macOS, Intel or Apple Silicon | `PlexConfigControl Setup.app` |
| Windows 10/11, 64-bit | `Windows/PlexConfigControl Setup.exe` |
| Ubuntu 22.04+, Mint 21+, Debian 12+, 64-bit desktop | `Linux/PlexConfigControl Setup` |

1. Choose **English** in the installer window.
2. Enter your TrueNAS address and administrator username.
3. Click **Connect**. An SSH key is optional. If your TrueNAS account password
   is needed, the installer requests it in a masked field. On the first
   connection, compare the SSH fingerprint with your NAS before approving it.
4. For a fresh installation, choose the backup location and folder name.
   Enter and confirm your own PlexConfigControl panel password.
5. Confirm the settings. The window shows the current stage and an animated
   activity bar. The first installation can take several minutes.
6. When setup finishes, click **Open panel**.

The wizard detects an existing running installation and offers an update.
Updating retains settings, history, archives and the existing panel password.
After an error, correct the reported problem and click **Try again**. Entries
remain in memory while this window is open. Passwords are not saved on disk.

If setup was interrupted after TrueNAS created the app, check its status in
**Apps → Installed** before trying again. The installer does not automatically
delete an existing app.

## Requirements

TrueNAS 25.10.8 or later on x86-64 with an Apps pool, SSH enabled and an account
with sudo access. The official Plex app must be named `plex` and use a separate
`config` iXVolume. Plex must be running during installation. Choose an existing
data dataset for backup archives. A fresh installation stores its private files
in the `pcc` iXVolume and application state in `state`. Archives and logs go to
the selected backup folder.

These installers are not publisher-signed. Your computer may require approval
before launching a downloaded installer. On Linux, the executable must retain
its executable permission after extracting the ZIP.

Setup requires a valid TrueNAS API HTTPS certificate and access from the NAS to
image registries and package repositories. Updating requires the Plex image
that matches the installed PlexConfigControl runtime. TrueNAS 25.10.8 has been
tested. Newer TrueNAS releases require separate compatibility verification.

Restore requires validating the archive and manually stopping Plex. Start Plex
manually after restore completes.

MIT license. https://github.com/ykrisw/PlexConfigControl
