# QNAP development packaging

Target currently verified by device diagnostics: QuTS hero 6.0.0, x86_64,
Python 3.12.4, glibc 2.39. This directory is build tooling, **not a finished
installer**. The released TrueNAS installer is unchanged.

## Private, offline Python dependencies

`requirements-cp312-x86_64.txt` pins the application dependencies and their
transitive dependencies, with SHA-256 hashes for the selected binary wheels.
Native wheels require glibc 2.28 or later. Other Python/CPU/firmware versions
have not been validated.

On the build host:

```sh
python3 deploy/qnap/build_dependencies.py --output /tmp/pcc-qnap-lib --smoke-test
```

An existing wheel directory can be supplied with `--wheelhouse PATH` for a
fully offline build. Hash checks apply to both downloaded and supplied wheels.
The output must not exist. Output includes dependency license metadata and a
file/hash manifest. Generated console-script wrappers are removed because their
shebangs refer to the build host; the QPKG will use its own Python entry point.

The resulting directory belongs inside the application's own QPKG installation.
The NAS must not download packages, run pip, or change its system Python packages.
The package launcher must use isolated Python (`-I -S`) and explicitly add its
private dependency directory to `sys.path` before importing application modules.

The smoke test runs imports and native cryptography/image operations on the
build host with global/user site packages disabled. This does not establish
real-device ABI compatibility; it still needs a QNAP run.

## Private GNU tar

The development NAS's GNU tar lacks `--acls` and `--xattrs`. Do not fall back to
archiving without that metadata, or replace the NAS's `/bin/tar`.

On a Linux x86_64 build host with Python 3.12+, a C toolchain, make, curl,
readelf and sha256sum:

```sh
sh deploy/qnap/build_tar.sh /tmp/pcc-qnap-tar-payload
```

This builds GNU tar 1.35 with private static ACL/attribute libraries and the
system libc. The output is rejected if it needs a glibc symbol newer than 2.39,
an unexpected shared library, or lacks required archive options. Source downloads
are pinned by SHA-256. Output includes corresponding source tarballs, build
instructions, license files and a hash manifest. GNU tar remains a separate
GPL-licensed program; PlexConfigControl retains its existing license.

The QNAP worker must explicitly supply its private `bin/pcc-tar` path to both
archive creation and staging extraction. The existing TrueNAS default is unchanged.
Build checks still need a real-device metadata round trip before use with Plex.

Exercise the built binary on the build host:

```sh
PCC_TEST_TAR_EXECUTABLE=/tmp/pcc-qnap-tar-payload/bin/pcc-tar \
    PYTHONPATH=tests:. python3 -m unittest tests.test_qnap_archive
```

The archive tests check file contents, mode bits and user xattrs after extraction.
The POSIX ACL round trip is skipped when the build host's filesystem or user
namespace cannot set ACLs; a skip must not be reported as device verification.

## Experimental read-only management API

`plexconfigcontrol/qnap_api.py` contains a fixed-loopback HTTPS probe, in-memory
login and bounded snapshot inventory reads. Login credentials use a POST form
body; snapshot inventory uses the native GET query with an in-memory session
parameter over verified loopback HTTPS. No application logging of request
targets/session values is permitted. It never follows redirects or uses an HTTP proxy.
It cannot create/delete snapshots or perform a rollback. Unknown response
schemas, expired sessions and full inventory pages fail closed.
TLS verification is required. A certificate read from trusted local NAS
configuration can anchor the trust chain and pin the exact leaf certificate
for loopback, without relying on an IP SAN. Pin verification happens before
any HTTP request, so a mismatch cannot receive login credentials. Certificate
expiry/chain verification stays enabled; redirects are never used as trust.

The authentication/snapshot field names are informed by the QNAP-authored
OpenStack driver at https://github.com/openstack/manila/blob/master/manila/share/drivers/qnap/api.py .
That driver targets ES NAS; it does **not** establish compatibility with QuTS
hero. The implementation currently passes mocked protocol tests only. Do not
enable any storage mutations based on these fixtures or infer public API support.
Device diagnostics confirmed login but not inventory: sending inventory fields
in a POST returned a generic response without `SnapshotList`. An authenticated
QCLI inventory attempt also failed on its runtime files. GET inventory still
needs a device test; a missing list must never be interpreted as an empty list.

## Still required before an installable QPKG

- QNAP-supported snapshot creation, read access and scoped removal.
- File-subtree restoration that cannot roll back the shared dataset.
- Unprivileged panel/privileged worker lifecycle and first-run web setup.
- QDK package hooks and App Center start/stop/open integration.
- Device backup, verification, restore and uninstall testing.
