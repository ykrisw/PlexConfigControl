# PlexConfigControl 1.0.5 — QNAP source checkpoint

This directory is for the QNAP QPKG, separate from the TrueNAS SCALE installer.

## Export pending import

The source export was created successfully on 2026-11-16:
- File: `QNAP/source/PlexConfigControl-source-baseline.zip`
- Files: 122
- SHA-256: `6d71dd5161101fcc8dba84c9ec6181ffa50ac2ff9e66678c18653d48a233b0e9`

The archive is not yet stored in this repository. This checkpoint does not constitute a new QNAP installer. Import and inspect the source archive before building.

The export selects application source, launcher, service script, setup page, QPKG builder, LICENSE, verified private GNU tar redistribution files and dependency provenance. It excludes private var state, credentials, TLS keys, history, logs and Plex data. Review archive contents before public import.

## Required build inputs

- Internal package ID: PCC; service: PCC.sh.
- Do not use PlexConfigControl as the package directory name: Plex service-stop process matching can otherwise terminate this application.
- CPython: https://github.com/astral-sh/python-build-standalone/releases/download/20261110/cpython-3.12.16%2B20261110-x86_64-unknown-linux-gnu-install_only.tar.gz
- Python archive SHA-256: c2f87d4b4e8db3abddb0f116c6ccfc503d0cbdbb9ee8faacddad1b679ec12e99
- QDK repository: qnap-dev/QDK
- QDK commit: b7b5f4c86ebe95b10a62d64725515e7cdcf4bb35
- Dependency builder, hashed wheel lock and GNU tar build recipe are preserved on branch work/qnap-qpkg under deploy/qnap/.
- Bundled GNU tar binary SHA-256: c7dc25fa1b3c55399081637652a2001e96518073bd7111509ec2ff481a9d5a28

## Changes to consolidate

Preserve the exported native QNAP backend and QNAP tools. Apply the shared frontend fixes from main: compact Backup/Restore action cards, helper text beside headings, Refresh in the archive-list heading and active operation workspace, login form preservation on repeated expired-session callbacks, password clearing only after successful login, touch landscape scrolling.

Keep the QNAP-only equal account button gaps (34px, 12px on short screens) and remove any username default specific to a user. TrueNAS must not gain QNAP authentication/folder controls.

Restore must wait for manual Plex stop. Do not auto-start/stop Plex, change dataset ACLs broadly or use dataset rollback. Preserve staged-file verification, stale PID cleanup and durable restore/rollback state.

## Compatibility and release verification

Target is QNAP QuTS hero with ZFS snapshot APIs, x86_64. Do not describe this as an ARM or generic QTS package. Validate runtime/library and firmware requirements before broader compatibility claims. Discover package/data locations dynamically. App Center URLs must use the NAS host address and selected port, without a fixed user IP.

Publish a new PlexConfigControl_QuTShero_x86-64v1.6.qpkg only after build/self-tests and UI checks pass. Keep separate QNAP and TrueNAS descriptions and checksums. Do not replace the TrueNAS installer with a QPKG.
