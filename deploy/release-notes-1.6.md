# PlexConfigControl 1.6

Both packages and the application now report version **1.6**. QNAP publisher: **Krzysztof Wojciechowski**.

## TrueNAS SCALE

[Download PlexConfigControlTrueNAS_1.6.zip](https://github.com/ykrisw/PlexConfigControl/releases/download/v1.6/PlexConfigControlTrueNAS_1.6.zip)

Contains graphical installers for Windows x64, macOS Apple Silicon and Linux x64, in English and Polish. Install or update the application on TrueNAS SCALE. Updates preserve the existing configuration. The installer verifies and updates the custom application's version metadata and prepares its corresponding configuration version directory, preserving the preceding directory for recovery.

## QNAP QuTS hero — x86_64

[Download PlexConfigControlQuTShero_1.6.qpkg](https://github.com/ykrisw/PlexConfigControl/releases/download/v1.6/PlexConfigControlQuTShero_1.6.qpkg)

Publisher: Krzysztof Wojciechowski. Package version: 1.6.

QNAP Backup now prompts for NAS sign-in before login; the prompt disappears immediately after successful sign-in, including when the archive folder has not yet been selected.

Back up and restore your Plex configuration with full data verification. For QNAP QuTS hero x86_64. ARM and plain QTS are unsupported by this build. Includes package-private Python and GNU tar. The package is not digitally signed by QNAP.

For the App Center card description, add one repository URL in App Center → Settings → App Repository:

- Polski: https://github.com/ykrisw/PlexConfigControl/releases/download/v1.6/qnap-repository-pl.xml
- English: https://github.com/ykrisw/PlexConfigControl/releases/download/v1.6/qnap-repository.xml

The installer does not add repositories or change automatic update policy.

## Shared behavior

Snapshot backups with data verification; Restore waits for manual Plex stop and retains the previous configuration for review. Includes the 20% wider yellow shield, matching archive heading/helper typography, shared manual Refresh for Backup and Restore, and slower indeterminate progress animation only on desktop. Existing mobile scrolling and sign-in fixes are retained.

Verify the downloads with SHA256SUMS (TrueNAS) or SHA256SUMS_QNAP (QNAP). A successful build is not a substitute for a device-level restore test.
