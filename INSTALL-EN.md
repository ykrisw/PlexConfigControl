# Install PlexConfigControl 1.0.10

PlexConfigControl runs on TrueNAS. The Windows, macOS and Linux launchers
connect to the NAS over SSH and start the English installation wizard.

## Requirements

- TrueNAS 25.10.8 or later on x86-64 (amd64), with an active Apps pool.
- The official Plex app installed as `plex` and running. Its `/config`
  must be a dedicated ZFS dataset, normally the `config` iXVolume.
- An existing writable ZFS dataset for archives outside the Apps storage.
  Select a dataset shared via SMB if you plan to copy archives from your
  computer. The wizard creates an archive folder and its `Logs` subfolder.
- A TrueNAS account with `sudo` access, a free port, a trusted HTTPS
  certificate for the TrueNAS API, and access to the Docker image registry
  and package repositories needed to build the application.
- For the desktop launchers, enable SSH on TrueNAS for the chosen account.
  Install OpenSSH Client on Windows if `ssh.exe` and `scp.exe` are missing.
  On Linux, install `openssh-client` if `ssh` and `scp` are missing.

## 1. Start the wizard

Extract the entire ZIP and keep the launcher and
`PlexConfigControl_Installer.py` in the same folder.

| Computer | Open |
|---|---|
| Windows 10 or 11 | `PlexConfigControl_Windows.cmd` |
| macOS | `PlexConfigControl_macOS.command` |
| Debian, Linux Mint or Ubuntu desktop | `PlexConfigControl_Linux.desktop` |

Enter the TrueNAS address and SSH username. Verify the server's SSH host key
before accepting it. SSH and TrueNAS prompt for passwords as needed. The
launchers do not save them. Windows may authenticate separately for upload
and for the interactive session.

On Linux, mark the specific desktop launcher as trusted if asked. If the
desktop opens it as text, run `bash ./PlexConfigControl_macOS.command` in the
extracted folder. On macOS, if Gatekeeper blocks the unsigned launcher, you
can allow that specific file in **System Settings → Privacy & Security**.

Alternatively, copy `PlexConfigControl_Installer.py` to the NAS over SMB
and run it in TrueNAS Shell using your actual path.

```sh
sudo python3 '/mnt/MyPool/MyDataset/PlexConfigControl_Installer.py'
```

## 2. Answer the prompts

1. Confirm the NAS IPv4 address. Select the archive dataset by number or enter
   its path, such as `/mnt/MyPool/MyDataset`.
2. Choose the folder name and panel port. Press Enter to accept a suggested
   value.
3. Enter and repeat the panel password. Review the settings and type `yes`.
   If the wizard finds private setup records left by an uninstalled copy,
   type `start over` only if you want to replace them. Existing archive files
   are preserved. An existing app or state iXVolume blocks fresh installation.
4. Wait for **PlexConfigControl is ready**. Open the HTTPS URL displayed by
   the wizard and sign in. You can find the app under **Apps → Installed**.

Private setup files default to `/mnt/<pool>/PCC-Private`. If the entire pool
is shared via SMB, select a location outside all shares with
`--private-directory`.

### TrueNAS HTTPS certificate

The wizard verifies the active TrueNAS API certificate. If it matches a DNS
name, pass `--api-host nas.example.net`. The name must resolve to the chosen
NAS address from inside the application container. To supply a trusted private
CA, pass `--ca /path/to/public-ca.pem`.

For a LAN setup that needs a new certificate, use the `certificate` command
with your own address and private directory:

```sh
sudo python3 PlexConfigControl_Installer.py certificate \
  --ip 192.168.1.120 --private-directory '/mnt/MyPool/PCC-Private'
```

In **System → General → GUI → Settings**, note the previous certificate and
select `pcc_lan_https`. This changes the TrueNAS administration interface
certificate. Your browser may require trusting the public CA. Rerun the
wizard using the same private directory.

### Check or resume

Use `sudo python3 PlexConfigControl_Installer.py check` for a preflight
without creating accounts, files or volumes. If installation stopped after
saving `settings.json` and no app or iXVolume was created, use the resume
command printed by the wizard or run:

```sh
sudo python3 PlexConfigControl_Installer.py --resume '/mnt/MyPool/PCC-Private/settings.json'
```

## 3. Verify the installation

With Plex running, create a backup and wait for verification. Check that the
archive and its log appear in the chosen folder. To restore, verify the
archive first and stop Plex manually when the panel asks. Start Plex manually
when the restore is complete.

This package is for a fresh installation. The project uses the MIT license.
[Source code](https://github.com/ykrisw/PlexConfigControl)
