# PlexConfigControl 1.0.5 — installation

Extract the ZIP and open the installer for your computer.

| Computer | Open |
|---|---|
| macOS, Apple Silicon (M1 or later) | `PlexConfigControl Setup.app` |
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

## HTTPS and connection repair (1.6.2)

Normal setup does not require finding a CA file. After authenticating the NAS over SSH, setup reads its configured public HTTPS certificate. It can identify the signing CA from public certificates in your computer's system stores. Unrelated certificates are not trusted: the issuer chain must cryptographically match the NAS certificate obtained over SSH. If no issuer is available, setup can use an exact certificate pin. A public PEM file chooser is a fallback; private keys are never requested.

For an installed app, run Setup and choose **Update application** to install 1.6.2. An old stopped or unhealthy app can be updated if its local state and operation checks permit it. Then choose **Repair connection** when the API certificate/CA has changed. Setup verifies the NAS certificate through SSH, updates only PCC's public trust file and restarts PCC. Settings, API keys, Plex data, archives and logs are retained. A trust repair cannot interrupt a live operation; retained recovery records and snapshots remain for review after connectivity returns.

Renewal under the same stored CA is accepted automatically. Replacing the CA or renewing an exact-certificate pin requires repair through independently authenticated SSH. The panel remains available and shows a specific connection error instead of depending on remote API readiness. An expired certificate or a certificate for the wrong NAS address still requires correcting the NAS HTTPS configuration; certificate checking is never disabled.

Enter the NAS DNS name in Setup when its HTTPS certificate covers that DNS name rather than its numeric IP. The installer keeps that name for hostname verification and checks that it resolves to the NAS being installed. Entering an address absent from the certificate is not fixed by turning off verification.
