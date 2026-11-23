# PlexConfigControl

**Current releases — 23 November 2026.** **TrueNAS SCALE 1.6.3** has been installed and successfully tested by the project owner on an actual TrueNAS host: installation, Plex configuration backup and restore all completed without problems. **QNAP QuTS hero 1.6.3** is functioning in the owner's ongoing tests; final acceptance testing is still in progress. Earlier validation records: [QNAP](QNAP/VALIDATION-1.6.md) · [TrueNAS](TrueNAS/VALIDATION-1.6.md). Each platform has its own download and checksum.

## QNAP QuTS hero — x86-64 (64-bit)

[**Download PlexConfigControl_QuTShero_x86-64v1.6.3.qpkg**](https://github.com/ykrisw/PlexConfigControl/releases/download/qnap-v1.6.3/PlexConfigControl_QuTShero_x86-64v1.6.3.qpkg)

**Purpose and operation:** Back up and restore your Plex Media Server configuration. Backups use a ZFS snapshot while Plex keeps running, then verify the archive data. Restore verifies the selected archive, waits for you to stop Plex manually, and retains the previous configuration for review or rollback.

**Installation:** Download the `.qpkg` and install it manually in QNAP App Center. Open PlexConfigControl, set the panel password, sign in to QNAP and choose the backup folder. Requires compatible QuTS hero with ZFS on x86-64; ARM and plain QTS are unsupported. The package is currently unsigned.

**License:** PlexConfigControl uses the MIT License (© 2026 Krzysztof Wojciechowski): free to use, modify and redistribute, including commercially, with the copyright and license notices retained. Provided without warranty. Bundled third-party components retain their own licenses. This package also includes GNU tar under GPLv3, with its source and license files.

[Source code, build files and instructions](QNAP/README.md) · [MIT License](QNAP/LICENSE) · [SHA-256 checksums](https://github.com/ykrisw/PlexConfigControl/releases/download/qnap-v1.6.3/SHA256SUMS_QNAP)

## TrueNAS SCALE 1.6.3 — x86-64 (64-bit)

[**Download PlexConfigControl_TrueNAS_x86-64v1.6.3.zip**](https://github.com/ykrisw/PlexConfigControl/releases/download/v1.6.3/PlexConfigControl_TrueNAS_x86-64v1.6.3.zip)

**Purpose and operation:** Back up and restore your Plex Media Server configuration. Backups use a ZFS snapshot while Plex keeps running, then verify the archive data. Restore verifies the selected archive, waits for you to stop Plex manually, and retains the previous configuration for review.

**Installation:** Download and extract the ZIP on your computer. Run the setup tool for Windows x64, Linux x64 or macOS Apple Silicon, connect to your TrueNAS server and choose the backup location and panel settings. The application runs on TrueNAS SCALE x86-64, not on your computer.

**License:** PlexConfigControl uses the MIT License (© 2026 Krzysztof Wojciechowski): free to use, modify and redistribute, including commercially, with the copyright and license notices retained. Provided without warranty. Bundled third-party components retain their own licenses.

[Source code, build files and instructions](TrueNAS/README.md) · [MIT License](TrueNAS/LICENSE) · [SHA-256 checksums](https://github.com/ykrisw/PlexConfigControl/releases/download/v1.6.3/SHA256SUMS)

**Owner-tested release (23 November 2026):** Installation, backup creation, and restore succeeded on TrueNAS SCALE. Current published installer ZIP SHA-256: `3967090989d239bc3d7c7f35aa61ec850fed91af267df7c0d2dc912c2b0ce2ab`. The same TrueNAS 1.6.3 release is tracked on both `main` and `master`; QNAP 1.6.3 remains separately distributed and under testing.

TrueNAS 1.6.3 adds certificate recovery through authenticated SSH and keeps the local panel available when the API cannot be verified. [HTTPS and repair instructions](TrueNAS/INSTALL-EN.md#https-and-connection-repair-161). Superseded TrueNAS 1.6 and 1.6.1 installers have been removed; QNAP 1.6.3 reloads the trusted local certificate before each API connection.
