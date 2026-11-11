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
- There is no executable mutation adapter yet. Do not use a full-volume revert
  to recover Plex's directory on a shared QNAP volume.
