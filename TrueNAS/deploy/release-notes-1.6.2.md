# PlexConfigControl 1.6.2 — TrueNAS SCALE x86-64

[Download the full TrueNAS installer](https://github.com/ykrisw/PlexConfigControl/releases/download/v1.6.2/PlexConfigControl_TrueNAS_x86-64v1.6.2.zip)

- Setup obtains the configured public NAS certificate through the authenticated SSH session. It can identify its signing CA using public certificate candidates from the computer's system stores, without trusting unrelated candidates or requesting private keys.
- If no issuer chain is available, setup can trust the exact configured NAS certificate obtained over SSH. A manual PEM selection remains available as a fallback.
- The local application and saved operation state start independently of remote API TLS availability. Storage and permissions must still be verified before any backup or restore execution is admitted.
- The panel distinguishes certificate trust, address and validity failures from authentication and network failures. It keeps archive/history access available while API operations are blocked.
- Setup offers **Repair connection** for an existing app. It verifies the current public certificate over SSH, checks that no live operation holds the execution lock, updates only PCC's trust file and restarts PCC. No reinstall, stored administrator password, NAS certificate replacement or Plex data change is involved.
- Trusted CA certificates are reloaded when reconnecting. A server certificate renewed under the same stored CA continues to verify. A different CA or an exact-certificate pin requires repair through independently authenticated SSH; HTTPS verification is never disabled.

Run the setup program for your computer. For an existing installation, choose **Update** first to install 1.6.2, including when the old app is stopped or unable to finish startup. Then choose **Repair connection** if its API trust requires renewal. Local operation/ownership checks remain mandatory before a code update. Trust-only repair can preserve an interrupted-operation/recovery record so that the API connection needed to inspect it can be restored; it never replays the operation or removes its snapshot. The application runs on TrueNAS SCALE x86-64. QNAP remains a separate 1.6 package.

The previously owner-confirmed [1.6 release](https://github.com/ykrisw/PlexConfigControl/releases/tag/v1.6) is retained. This maintenance release does not claim a new owner-run NAS validation until reported separately.

MIT License, © 2026 Krzysztof Wojciechowski. Bundled dependencies retain their licenses. [Source and instructions](https://github.com/ykrisw/PlexConfigControl/tree/main/TrueNAS).

Installer transport correction: the allocated SSH terminal uses noncanonical input so public certificate replies larger than 4095 bytes are not truncated. A real PTY regression test transfers a 600,000-character reply.
