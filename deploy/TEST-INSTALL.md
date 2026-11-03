# PlexConfigControl — first test installation

This is a test build, not a complete backup/restore product. Only use an artifact
from a successful **Build test installation** run. It includes the Docker image,
this guide and SHA256SUMS. Artifacts expire after 30 days; a build can recreate one.
The default branch source ZIP is not the installation image.

## What this build can test

- Password-only login, no inactivity logout, password changes and explicit logout.
- The approved shared panel shell, Dashboard, History and Restore validation view.
- Persistent preferences, sessions, history and TLS identity across app restarts.
- Optional Plex status reads using a separately configured read-only connection.
- Optional archive selection/validation with a read-only archive host-path mount.

Backup creation, config restoration, snapshot operations and archive deletion are
blocked by the test runtime. Later builds show Backup archives/planning but keep
creation and deletion disabled. Settings is connected in builds after the first
test image; the first image still has its Backup/Settings placeholders.
History downloads export stored event text, not full permanent operation files.
No Docker socket, ZFS device, host shell, live Plex config or Plex container mounts
are needed or permitted by this test configuration. Do not change Plex ACLs.

## 1. Load the image once

Download and unzip **PlexConfigControl-test-installation** from the successful
GitHub Actions run. Place `PlexConfigControl-test-image.tar.gz` on an accessible
SMB directory. In the TrueNAS shell, use its actual path:

```sh
sudo docker load --input '/YOUR/ACTUAL/PATH/PlexConfigControl-test-image.tar.gz'
```

The loaded image is `plexconfigcontrol:test`. Image import and the password
helper below are installation steps. No backup/restore shell scripts
are installed. The archive can be removed manually after the installation works.

## 2. Prepare the initial password without storing it in Apps configuration

The test packaging uses a salted password verifier, not a plaintext environment
password. Generate it using the loaded image:

```sh
sudo docker run --rm -it --entrypoint python plexconfigcontrol:test -m plexconfigcontrol.installation
```

Enter and confirm the desired password. Input is hidden. Copy the single line
beginning `pbkdf2-sha256$`. This is a sensitive password verifier, not a password;
do not post it in chat or screenshots. The temporary helper container is removed.
This extra step is temporary: the final installation form still needs a verified
password/secret integration. No default password is supplied.

## 3. TrueNAS Apps → Discover Apps → Custom App

Use the guided **Custom App** wizard, not Install via YAML. This allows a real
TrueNAS-managed ixVolume, rather than substituting an ordinary Docker volume.

| Setting | Value |
| --- | --- |
| Application name | `plexconfigcontrol-test` |
| Image repository | `plexconfigcontrol` |
| Image tag | `test` |
| Pull policy | Never (use the image imported above) |
| Restart policy | Unless Stopped |
| Privileged | Off |
| Custom user/group, if needed | UID `568`, GID `568` (same as the image) |
| Host IP | `192.168.1.120` |
| Host port | `8787`, or another free port selected by you |
| Container port | `8443`, TCP |
| Portal protocol/path | HTTPS, `/` |

Keep the image's default entrypoint and command. Add these environment variables:

| Name | Value |
| --- | --- |
| `PCC_PUBLIC_HOST` | `192.168.1.120` (or the actual NAS address used in the browser) |
| `PCC_BOOTSTRAP_VERIFIER` | The complete verifier from step 2 |

Add **Storage → ixVolume** with dataset name `state` and mount path
`/var/lib/plexconfigcontrol`. It must be writable by UID/GID 568. If the wizard
requires an ACL entry for this new app volume, grant that identity access only
on the app volume. Do not enable any force-ACL option or change existing datasets.
Do not use a broad host-path mount as a replacement for this state volume.

No additional storage is required for the first UI test. Install and wait for
the app to run, then open `https://192.168.1.120:8787`. The app generates its own
certificate in its ixVolume. Your browser will warn because it is self-signed.
Confirm only the NAS address you selected. The certificate persists on restart.

Changing the NAS address later requires an explicit TLS-certificate migration;
this test runtime intentionally does not silently replace its saved certificate.

## 4. What to check first

1. Sign in with the password chosen in step 2.
2. Check Dashboard layout and Change Password; changing the password signs all
   sessions out. Log back in with the new password.
3. Check History, filters, selecting entries, downloading and confirmed clearing.
   In newer builds, also test profile-photo upload/replacement, restart persistence
   and confirmed removal. The first image does not include this feature.
4. Restart only this test app through TrueNAS Apps. Check the password, session,
   history and TLS certificate survive.
5. Plex state is **UNKNOWN** until a verified read-only connection is configured.
   This is expected; the app never invents a RUNNING state.

The original bootstrap verifier is ignored once the account exists. It cannot
reset the password after an app restart. Removing it from Apps configuration
after the first successful sign-in is supported.

## Optional archive-validation test

Add one host-path mount containing test archives at `/archives`, **Read Only**,
and set `PCC_ARCHIVE_DIRECTORY=/archives`. Keep Enable ACL/Force ACL off. The app
does not adopt this directory as its managed output destination, create folders
there or change its permissions. It only lists recognized dated archive names
and validates their content. Leave the live Plex config dataset unmounted.

For a Plex status connection, the runtime accepts `PCC_TRUENAS_URL`,
`PCC_API_USERNAME`, `PCC_API_KEY_FILE`, and optional `PCC_CA_FILE`. Credentials
must be privately mounted files readable only by the application identity.
TLS verification is mandatory. Configure this separately; never paste keys into
chat. The runtime accepts only app.query filtered to Plex, with no snapshot or
app start/stop methods. This connection still needs end-to-end TrueNAS testing.

## Removing the test app

Use TrueNAS Apps deletion. Removing the app ixVolume removes account/settings,
sessions, web history and generated certificate. Keeping the volume retains that
state; a new installation requires removing the old state volume. Read-only
external archives and their permanent Logs directory are never deleted by this
test build. TrueNAS controls its Remove ixVolumes/Images options.

## References

- https://www.truenas.com/docs/scale/25.10/scaleuireference/apps/installcustomappscreens/
- https://apps.truenas.com/managing-apps/installing-custom-apps/
- https://gunicorn.org/reference/settings/
