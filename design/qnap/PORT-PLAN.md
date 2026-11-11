# PlexConfigControl for QNAP — initial port

The released TrueNAS application remains the reference implementation. QNAP
development takes place separately on `work/qnap-qpkg`.

## Confirmed on the development NAS

- User-reported hardware: TVS-h674; system model family: TS-X74.
- Architecture: x86_64.
- Firmware: version 6.0.0, build 20260520; user reports QuTS hero.
- Registered Plex package: PlexMediaServer, version 1.43.5, enabled.
- Package installation: `/share/ZFS530_DATA/.qpkg/PlexMediaServer`.
- Existing data directory: `Library/Plex Media Server` under the package.
- Filesystem reported for the installation: `zpool1/zfs530`, mounted at
  `/share/ZFS530_DATA`. This does not establish an exclusive Plex dataset.
- Present executables: `/sbin/zfs`, `/usr/local/bin/python3`,
  `/usr/bin/rsync`, `/bin/tar`.
- Canonical data directory is the same package-local path reported above.
- Python 3.12.4, glibc 2.39, OpenSSL 3.0.20, Python SQLite 3.26.0.
  Do not use stock Python SQLite to validate Plex's databases.
- The reported ZFS listing contains the filesystem and `@:init:` snapshot,
  with no child filesystem reported. The existing snapshot is not app-owned
  and must remain untouched.

## Scope and boundaries

- Produce an x86-64 `.qpkg` installed and managed through QNAP App Center.
- Retain the current UI, Polish/English support and backup/restore/history behavior.
- Keep private state in PlexConfigControl's own package storage, with archives
  and operation logs only in the user-selected archive folder and its `Logs` child.
- Preserve manual Plex stop before restore and manual start afterwards.
- Keep the web panel unprivileged and privileged filesystem operations narrowly scoped.
- Do not modify Plex ownership or ACLs to obtain access.
- Never roll back a shared dataset or pool to restore Plex: only the verified
  Plex data subtree may be replaced. No executable restore implementation is enabled yet.
- Reuse platform-neutral archive validation, operation state and UI code.
  Implement QNAP package discovery, service status and storage/snapshot access separately.
- Select a supported snapshot integration after verifying the installed firmware
  and storage layout. Presence of `/sbin/zfs` alone is not authorization to alter
  QNAP-managed storage directly.
- Keep firmware/package credentials and Plex Preferences.xml contents out of diagnostics.

## Next required observations

1. Plex's bundled SQLite executable and its in-memory version probe.
2. Plex process executable location without dumping command arguments or environment.
3. QNAP snapshot integration and runtime compatibility for package dependencies.

Read-only QNAP package/storage discovery is implemented in
`plexconfigcontrol/qnap_discovery.py` and covered by fixture tests. It is not
wired to application execution and does not enable backup or restore yet.

Initial NAS commands remain read-only. The first `.qpkg` must be clearly
identified as a test build until real-device backup, verification and restore pass.
