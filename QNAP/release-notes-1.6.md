# PlexConfigControl 1.6

**Confirmed working baseline — 17 November 2026.** The project owner has confirmed successful backup creation and restore on QNAP QuTS hero and TrueNAS SCALE, with no current objections to the interface appearance. The existing tested binaries are retained; this finalization updates the release record and documentation.

Current archive labels show the new backup rather than the previous comparison archive. Full archive names precede validation and restore progress, in both languages and themes.

## QNAP QuTS hero — x86-64 (64-bit)

[**Download PlexConfigControl_QuTShero_x86-64v1.6.qpkg**](https://github.com/ykrisw/PlexConfigControl/releases/download/v1.6/PlexConfigControl_QuTShero_x86-64v1.6.qpkg)

**Purpose and operation:** Back up and restore your Plex Media Server configuration. Backups use a ZFS snapshot while Plex keeps running, then verify the archive data. Restore verifies the selected archive, waits for you to stop Plex manually, and retains the previous configuration for review or rollback.

**Installation:** Download the `.qpkg` and install it manually in QNAP App Center. Open PlexConfigControl, set the panel password, sign in to QNAP and choose the backup folder. Requires compatible QuTS hero with ZFS on x86-64; ARM and plain QTS are unsupported. The package is currently unsigned.

**QNAP maintenance update:** Added a guarded directory-rename path for QNAP ZFS rejecting `RENAME_NOREPLACE` with errno 22. Existing destinations are refused. Legacy moves require a recorded source inode and a verified private workspace endpoint; QNAP Library permissions and ACLs remain unchanged, including mode 0777. Recovery status now points to the QNAP Dashboard recovery control. Added atomic-rename compatibility for older NAS libraries, explicit selected-archive validation, archive refresh on tab navigation, permanent profile/account event logs, and persistent NAS sessions with periodic read-only validation. Local backup errors no longer clear NAS sign-in. Session tokens remain in root-only application storage; passwords and TOTP codes are not saved. Unchanged App Center settings are no longer rewritten on each startup. Restore failures now retain their detailed cause in the operation log.

**License:** PlexConfigControl uses the MIT License (© 2026 Krzysztof Wojciechowski): free to use, modify and redistribute, including commercially, with the copyright and license notices retained. Provided without warranty. Bundled third-party components retain their own licenses. This package also includes GNU tar under GPLv3, with its source and license files.

[Source code, build files and instructions](https://github.com/ykrisw/PlexConfigControl/tree/main/QNAP) · [MIT License](https://github.com/ykrisw/PlexConfigControl/blob/main/QNAP/LICENSE) · [SHA-256 checksums](https://github.com/ykrisw/PlexConfigControl/releases/download/v1.6/SHA256SUMS_QNAP)

## TrueNAS SCALE — x86-64 (64-bit)

[**Download PlexConfigControl_TrueNAS_x86-64v1.6.zip**](https://github.com/ykrisw/PlexConfigControl/releases/download/v1.6/PlexConfigControl_TrueNAS_x86-64v1.6.zip)

**Purpose and operation:** Back up and restore your Plex Media Server configuration. Backups use a ZFS snapshot while Plex keeps running, then verify the archive data. Restore verifies the selected archive, waits for you to stop Plex manually, and retains the previous configuration for review.

**Installation:** Download and extract the ZIP on your computer. Run the setup tool for Windows x64, Linux x64 or macOS Apple Silicon, connect to your TrueNAS server and choose the backup location and panel settings. The application runs on TrueNAS SCALE x86-64, not on your computer.

**License:** PlexConfigControl uses the MIT License (© 2026 Krzysztof Wojciechowski): free to use, modify and redistribute, including commercially, with the copyright and license notices retained. Provided without warranty. Bundled third-party components retain their own licenses.

[Source code, build files and instructions](https://github.com/ykrisw/PlexConfigControl/tree/main/TrueNAS) · [MIT License](https://github.com/ykrisw/PlexConfigControl/blob/main/TrueNAS/LICENSE) · [SHA-256 checksums](https://github.com/ykrisw/PlexConfigControl/releases/download/v1.6/SHA256SUMS)

## Verification and exact packages

- **QNAP QuTS hero x86-64:** `PlexConfigControl_QuTShero_x86-64v1.6.qpkg` — SHA-256 `772687998b1a5520260dba43551a5715aabaca8280b0f2d30f7f9960060f8568`. [Verification record](https://github.com/ykrisw/PlexConfigControl/blob/main/QNAP/VALIDATION-1.6.md).
- **TrueNAS SCALE x86-64:** `PlexConfigControl_TrueNAS_x86-64v1.6.zip` — SHA-256 `c224e879853b8b30b2c7693c179e53a73a4aa5d63597ddd4776cc83b78185d03`. [Verification record](https://github.com/ykrisw/PlexConfigControl/blob/main/TrueNAS/VALIDATION-1.6.md).

Both binaries were built from application commit `3971b155a30a042c7f99e39bf31279765b606a1a`. The release tag includes the final documentation; platform manifests preserve the exact build commit, sizes, checksums and build links. Source and documentation are mirrored in `main` and `master`.
