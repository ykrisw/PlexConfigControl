# PlexConfigControl

**Confirmed working baseline — 17 November 2026.** The project owner confirmed successful backup and restore on both platforms and reported no current appearance issues. [QNAP verification](QNAP/VALIDATION-1.6.md) · [TrueNAS verification](TrueNAS/VALIDATION-1.6.md). Exact package checksums are recorded separately for each platform.

## QNAP QuTS hero — x86-64 (64-bit)

[**Download PlexConfigControl_QuTShero_x86-64v1.6.qpkg**](https://github.com/ykrisw/PlexConfigControl/releases/download/v1.6/PlexConfigControl_QuTShero_x86-64v1.6.qpkg)

**Purpose and operation:** Back up and restore your Plex Media Server configuration. Backups use a ZFS snapshot while Plex keeps running, then verify the archive data. Restore verifies the selected archive, waits for you to stop Plex manually, and retains the previous configuration for review or rollback.

**Installation:** Download the `.qpkg` and install it manually in QNAP App Center. Open PlexConfigControl, set the panel password, sign in to QNAP and choose the backup folder. Requires compatible QuTS hero with ZFS on x86-64; ARM and plain QTS are unsupported. The package is currently unsigned.

**License:** PlexConfigControl uses the MIT License (© 2026 Krzysztof Wojciechowski): free to use, modify and redistribute, including commercially, with the copyright and license notices retained. Provided without warranty. Bundled third-party components retain their own licenses. This package also includes GNU tar under GPLv3, with its source and license files.

[Source code, build files and instructions](QNAP/README.md) · [MIT License](QNAP/LICENSE) · [SHA-256 checksums](https://github.com/ykrisw/PlexConfigControl/releases/download/v1.6/SHA256SUMS_QNAP)

## TrueNAS SCALE 1.6.1 — x86-64 (64-bit)

[**Download PlexConfigControl_TrueNAS_x86-64v1.6.1.zip**](https://github.com/ykrisw/PlexConfigControl/releases/download/v1.6.1/PlexConfigControl_TrueNAS_x86-64v1.6.1.zip)

**Purpose and operation:** Back up and restore your Plex Media Server configuration. Backups use a ZFS snapshot while Plex keeps running, then verify the archive data. Restore verifies the selected archive, waits for you to stop Plex manually, and retains the previous configuration for review.

**Installation:** Download and extract the ZIP on your computer. Run the setup tool for Windows x64, Linux x64 or macOS Apple Silicon, connect to your TrueNAS server and choose the backup location and panel settings. The application runs on TrueNAS SCALE x86-64, not on your computer.

**License:** PlexConfigControl uses the MIT License (© 2026 Krzysztof Wojciechowski): free to use, modify and redistribute, including commercially, with the copyright and license notices retained. Provided without warranty. Bundled third-party components retain their own licenses.

[Source code, build files and instructions](TrueNAS/README.md) · [MIT License](TrueNAS/LICENSE) · [SHA-256 checksums](https://github.com/ykrisw/PlexConfigControl/releases/download/v1.6.1/SHA256SUMS)

TrueNAS 1.6.1 adds certificate recovery through authenticated SSH and keeps the local panel available when the API cannot be verified. [HTTPS and repair instructions](TrueNAS/INSTALL-EN.md#https-and-connection-repair-161). The owner-confirmed [1.6 release](https://github.com/ykrisw/PlexConfigControl/releases/tag/v1.6) remains available; QNAP stays at 1.6.
