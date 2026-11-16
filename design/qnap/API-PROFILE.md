# QuTS hero snapshot CGI profile — development observations

This profile records interface facts from offline analysis of user-supplied
QNAP programs. No supplied executable was run. The proprietary programs and
disassembly are not part of the project or distribution. These observations
are not a claim that QNAP publishes or supports this interface for third parties.

## Read operations

The CGI selects the ZFS implementation by checking the NAS's ZFS capability.
`prod=hero` strings in auxiliary LUN calls are not evidence that this flag is
required for the snapshot inventory entry point.

All operations below use `/cgi-bin/disk/snapshot.cgi` and an authenticated NAS
session over verified loopback HTTPS.

| Purpose | Parameters in addition to the session |
| --- | --- |
| Inventory | `func=extra_get`, `volumeID`, `snapshot_list=1`, `start`, `end` |
| Volume counter | `func=extra_get`, `volumeID`, `snapshot_count=1`, `by_vol=1` |

Inventory pagination uses zero-based `start` and an inclusive `end`; the
older `snap_start` and `snap_count` fields are not the native pagination inputs
in the inspected ZFS implementation. A nonempty enumeration emits
`total_snapshot_count` and `SnapshotList/row` with `snapshot_id`,
`snapshot_name`, `create_time` and other metadata.

If the enumeration returns zero **or an error**, this implementation can omit
`SnapshotList` while the enclosing result still appears successful. Therefore
absence alone is not evidence of an empty inventory. A separate, authenticated
counter response must echo the requested `volumeID` and report a valid zero.
The native counter itself clamps negative storage-counter returns to zero, so
the volume binding must first be independently established from the registered
Plex path and native volume lookup. Real-device testing is still required.

## Lifecycle facts for the upcoming execution adapter

- The ZFS dispatch table contains `create_snapshot`, `del_snapshot` and
  `del_snapshots`; some names are suffixes of longer strings, explaining why
  a whole-string scan did not show every supported function.
- `create_snapshot` reads `volumeID`, `snapshot_name`, `expire_min`, `vital`,
  `snapshot_type`, and optional description. A synchronous success emits
  `SnapshotInfo` including a native `snapshot_id` and echoed name. A background
  response is a separate case and must not be interpreted as completed creation.
- `del_snapshots` queues deletion for supplied native `snapshotID` values.
  Its outer success response does not prove that the storage operation
  succeeded or completed. Poll and independently confirm absence.
- Never expose arbitrary IDs or mutation functions to the web panel. Persist
  operation intent, bind every owned snapshot to the discovered volume/dataset,
  and verify ID/name provenance before any removal.
- The developer lifecycle diagnostic exercises only a fresh, nonce-owned
  snapshot. Production backup coordination is still pending. Never use a
  full-volume revert to recover Plex's directory on a shared QNAP volume.

## Create result and asynchronous cleanup

The inspected native create handler can return the newly allocated positive
snapshot ID; treating every nonzero result as failure is incorrect for this
operation. The diagnostic accepts a positive result only when it equals the
echoed ID and name, and then independently confirms that identity in inventory.
Delete remains asynchronous: the diagnostic polls for up to 180 seconds with
progress updates and requires API and ZFS absence. A later manual observation
of absence does not establish whether deletion or vendor expiry removed it.

QuTS hero h6.0.3.3670 build 20261106 is a new device-test target. Compatibility
with that build is not yet confirmed; do not infer it from earlier results.

## Device result on h6.0.3

Password plus TOTP authentication, creation of a fresh named snapshot, and
subsequent deletion confirmed by both API and ZFS were exercised successfully
on QuTS hero h6.0.3. The preview failed the strict scoped read-only mount check;
that does not establish that the preview is writable or correctly bound.

The diagnostic now opens the vendor-returned preview directory before checking
mountinfo, allowing lazy automount to occur. It reports metadata for only the
deepest covering mount and the VFS read-only flag. Opening Plex files remains
blocked until both snapshot provenance and read-only checks pass. This change
still needs a device run; no alternative mount layout is accepted speculatively.

## Observed read-only preview layout

A real-device preview reports ZFS with a snapshot-qualified source, per-mount
`rw,relatime`, superblock `ro,xattr,richacl`, and VFS `ST_RDONLY` set. The earlier
check rejected this valid read-only layout because it looked only for `ro` in
per-mount options. The checker now accepts `ro` at either mountinfo layer, while
still requiring `ST_RDONLY` on the held directory descriptor, exact discovered
dataset snapshot provenance and a source absent from the pre-test baseline.
Tests cover the observed layout and reject a writable descriptor even when
mountinfo claims read-only; no Plex subtree is opened in the latter case.

## Successful target-device lifecycle

The corrected checker completed the whole diagnostic on h6.0.3.3670: authenticated
password plus TOTP, one fresh native snapshot, required Plex files accessible
through its read-only preview, and absence confirmed by both API and ZFS after
deleting the owned snapshot. This is evidence for that lifecycle only, not a
full archive, metadata restoration, or QPKG-installation test.
