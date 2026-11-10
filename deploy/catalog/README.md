# TrueNAS Community catalog candidate

This candidate targets TrueNAS 25.10.8 or newer. Its form, image definition
and templates are under `plexconfigcontrol/`. The catalog runtime only reads
the selected archive folder and does not use the TrueNAS management API,
Docker socket or Plex configuration dataset. The permissions helper only
initializes the application's own state volume.

The first application field is the language. It defaults to English and
shows the settings fields for the chosen language. TrueNAS's own navigation
and install controls follow the TrueNAS interface language.

The panel uses HTTPS. Selecting a trusted NAS certificate matching the
address used in the browser avoids a browser certificate warning. Without
a selected certificate the panel uses its own self-signed certificate.
The install form hashes the initial password with the catalog's bcrypt
helper before passing the verifier to the container. TrueNAS owns the form
values. Password changes in the panel are stored in its iXVolume.

## Before submitting

- Publish the panel image from the root Dockerfile, then set the published
  image reference and digest in `ix_values.yaml`. The current candidate
  points to the publicly available, tested Linux amd64 image.
- Render the English and Polish fixture values with the TrueNAS Apps library
  and test a clean installation from the TrueNAS form. Verify language
  switching, login, opening the HTTPS portal, archive validation and state
  retention after restart. Confirm the archive mount remains read-only.
- Complete the catalog metadata and artwork with the maintainers' required
  values before opening a Community catalog pull request.
