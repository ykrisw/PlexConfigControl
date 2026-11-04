# PlexConfigControl — restricted test installation for TrueNAS SCALE

This package installs the HTTPS web panel: sign-in/password changes, profile
photo, web history, English/Polish and Light/Dark/System preferences. Private
state and the application certificate persist across application restarts.

**Backup/Restore host execution is disabled.** Plex control, snapshot mutations
and archive deletion are unavailable. The new storage-setup component is present
in source but is not mounted by this restricted installation. Do not attach live
Plex configuration, a Docker socket, devices or API credentials for the first test.

1. Extract the package on your computer. Copy `PlexConfigControl-test-image.tar.gz`
   to a chosen ordinary location on your NAS (never protected PBS storage).
2. In TrueNAS shell, substitute the actual image path:

   ```sh
   sudo docker load --input '/YOUR/PATH/PlexConfigControl-test-image.tar.gz'
   ```

   Expect `Loaded image: plexconfigcontrol:test`. Do not extract the image tarball.
3. Generate the salted initial password verifier:

   ```sh
   sudo docker run --rm -it --entrypoint python plexconfigcontrol:test -m plexconfigcontrol.installation
   ```

   Enter and confirm your password. Copy the full `pbkdf2-sha256$...` output;
   treat it as sensitive and do not paste it into chat.
4. In **Apps → Discover Apps → Custom App**, use the form, not Install via YAML:

   | Field | Value |
   | --- | --- |
   | Application Name | `plexconfigcontrol-test` |
   | Image Repository / Tag | `plexconfigcontrol` / `test` |
   | Pull Policy | Never pull image even if it’s not present on host |
   | Restart Policy | Unless Stopped |
   | Privileged | off |
   | User if requested | UID 568, GID 568 |
   | Host IP / Port | your NAS IP, e.g. `192.168.1.120` / `8787` |
   | Container Port | `8443`, TCP |
   | Portal Protocol / Path | HTTPS / `/` |

   Keep the image's default Entrypoint and Command. Add environment variables:
   `PCC_PUBLIC_HOST` = your NAS IP; `PCC_BOOTSTRAP_VERIFIER` = the entire verifier.
   Never supply a plaintext password variable.
5. Add one new **ixVolume** named `state`, mounted at `/var/lib/plexconfigcontrol`.
   It must be writable by UID/GID 568. If needed, configure ACL only on this new
   app volume. Never force ACLs or alter existing datasets. Add no other mounts.
6. Install, wait for RUNNING, then visit `https://YOUR_NAS_IP:8787`. The app's
   self-signed certificate produces a browser warning. Verify the NAS address
   before accepting the exception. Sign in with your chosen password.

Check preferences/language, photo upload/change/removal, password changes,
sign-out, web history and a restart of this application only. UNKNOWN Plex state,
empty archive lists and disabled execution buttons are expected without optional
integration. This does not mean Plex is stopped. No inactivity logout is intended.

After first successful sign-in, `PCC_BOOTSTRAP_VERIFIER` may be removed from app
configuration. It does not reset an existing account. Preserve the iXVolume to
retain settings, account, sessions, photo, history and certificate.

If startup fails, inspect this app's logs and check the complete verifier, public
host, non-root identity and new state-volume write access. Do not enable root,
privileged mode or Docker socket access as a workaround.

Uninstall only `plexconfigcontrol-test` through Apps. Deleting its iXVolume removes
its private state; preserving it retains that state. Production Plex data is not
modified by this first-test configuration.

`BUILD-INFO.txt` identifies the exact source commit and build time. `SHA256SUMS`
covers the image, both installation guides and build information. The image is
built for the Linux x86_64 CI runner; this package is not an ARM image.
