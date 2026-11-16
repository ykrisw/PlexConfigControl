# PlexConfigControl 1.0.5 for QNAP

This is the native `PCC_1.0.5_x86_64.qpkg` installer for **QNAP QuTS hero with ZFS snapshot APIs on x86_64**. The TrueNAS SCALE desktop installer is a separate product artifact.

## Build inputs preserved in Git

- `/PCC_QNAP_Source_1.0.5.zip`: verified application, launcher, service, setup page, builder and GNU tar redistribution bundle.
- `SOURCE-CHECKPOINT-1.0.5.md`: exact source SHA-256 and provenance.
- `build_dependencies.py` and `requirements-cp312-x86_64.txt`: offline, hash-locked dependencies.
- `qpkg/qpkg.cfg` and `qpkg/package_routines`: generic package identity and lifecycle hooks.
- `prepare_release.py`: verifies the source archive, overlays the shared current frontend and retains QNAP-specific controls.
- `/.github/workflows/qnap-installer.yml`: pinned runtime/QDK download, package build, self-tests and separate QNAP release checksum.

The source ZIP has 122 files. SHA-256:
`6d71dd5161101fcc8dba84c9ec6181ffa50ac2ff9e66678c18653d48a233b0e9`.

It excludes private application state, passwords, TLS keys, history, operation logs, backup archives and Plex data. Rebuilding does not require access to the original NAS.

## Installation and update

Download the QNAP QPKG from release 1.0.5 after its build completes and verify against `SHA256SUMS_QNAP`. Install manually through App Center. It is not digitally signed by QNAP.

Finish active operations, recovery and retained-configuration review before updating or removing PCC. The package refuses routine maintenance while these are outstanding. Existing private settings remain in the package's private state directory during an update. A fresh installation opens first-run setup.

Open the application through App Center. Its URL uses the NAS host address and selected HTTPS port (default 8443); it does not assign or change the NAS IP. The package includes its own Python, dependency library and GNU tar. Package and Plex data paths are discovered dynamically.

## Operational behavior

Snapshot Backup verifies archive data before confirming success. Restore requires the user to stop Plex manually, retains the previous configuration for review/rollback, and requires manual Plex startup afterward. Never substitute a whole-dataset rollback for this process.

QNAP authentication supports a current TOTP when required. NAS credentials are not included in installers. A new installation has no hardcoded local username.

## Compatibility limits

Development hardware was a TVS-h674 running QuTS hero. Other x86_64 models require compatible glibc/runtime and the same native snapshot APIs; they have not all been device-tested. ARM and non-ZFS QTS are unsupported by this build. The native management API currently assumes local HTTPS port 443. A customized management port needs additional support.

A successful package build and browser regression tests do not prove a full restore on every NAS. Keep an independent backup when testing a new device.
