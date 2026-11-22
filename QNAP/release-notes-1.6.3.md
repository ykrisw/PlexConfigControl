# PlexConfigControl 1.6.3 — QNAP QuTS hero x86-64

[Download the full QNAP installer](https://github.com/ykrisw/PlexConfigControl/releases/download/qnap-v1.6.3/PlexConfigControl_QuTShero_x86-64v1.6.3.qpkg)

Back up, verify and restore Plex configuration on QNAP QuTS hero. Install or update the QPKG manually through App Center. Open PCC, sign in to QNAP if required and select the archive folder. Stop Plex manually before restoring.

The API client reloads the root-controlled local NAS certificate before every HTTPS connection. A certificate change does not itself discard the existing NAS session. Verification and exact certificate pinning remain enabled; passwords and Authenticator codes are not retained. QNAP can still invalidate its own session, requiring a new login. Storage mutations are never automatically replayed after connection errors.

Lifecycle tests cover refusal to uninstall during active operations, stopping the service, removing its package directory and releasing the port while preserving Plex and archives. These are disposable CI tests, not a claim of a new owner-run NAS backup/restore validation.

MIT License, © 2026 Krzysztof Wojciechowski. Bundled dependencies retain their licenses, including GNU tar under GPLv3. The QPKG is not digitally signed. [Source, instructions and licenses](https://github.com/ykrisw/PlexConfigControl/tree/main/QNAP).
