# PlexConfigControl 1.6 — QNAP QuTS hero x86-64 (64-bit)

**Potwierdzona działająca wersja — 17.11.2026:** właściciel potwierdził wykonanie kopii i przywracanie oraz brak bieżących zastrzeżeń do wyglądu. [Zapis weryfikacji](VALIDATION-1.6.md) · [Plik i suma SHA-256](RELEASE-1.6.json).

[**Pobierz instalator QNAP QuTS hero 1.6**](https://github.com/ykrisw/PlexConfigControl/releases/download/v1.6/PlexConfigControl_QuTShero_x86-64v1.6.qpkg)

Pakiet dla QuTS hero z ZFS na x86-64, nie dla ARM ani zwykłego QTS. Wydawca: Krzysztof Wojciechowski. Pakiet pozostaje niepodpisany cyfrowo.

| Zawartość | Lokalizacja |
| --- | --- |
| Pełny zachowany eksport źródeł, narzędzi i licencji | [source](source/) |
| Przygotowanie źródeł i budowanie QPKG | [build](build/) |
| Aktualny interfejs nakładany na bazę | [shared-ui](shared-ui/) |
| Testy QNAP | [tests](tests/) |
| Publikowanie | [publish_release.py](publish_release.py) |
| Instrukcje i ograniczenia | [build/README.md](build/README.md) |
| Licencja aplikacji | [LICENSE](LICENSE) |

ZIP źródeł jest historyczną bazą 1.0.5 o zachowanej sumie kontrolnej. Aplikacja ma wersję **1.6**. Skrypt `build/prepare_release.py` weryfikuje ZIP, rozpakowuje źródła i nakłada aktualny interfejs oraz poprawki QNAP. Przykład: `python build/prepare_release.py .qnap-build/source` (Node.js i CairoSVG 2.8.2 na komputerze budującym).

Ten katalog zawiera własne dane wejściowe budowania i nie wymaga plików z TrueNAS. Zmiany wspólnego wyglądu należy stosować w obu zbiorach. Licencje i źródła GNU tar oraz jego zależności pozostają w eksporcie źródłowym.

[TrueNAS](../TrueNAS/README.md)

## Maintenance source

Native runtime fixes are readable under [runtime](runtime/). The preparation script overlays them onto the verified baseline. The NAS session token is stored only in root-owned private application storage; no password or TOTP code is saved. A read-only keepalive retains the session until QNAP itself invalidates it. Profile/account events create permanent files in the selected `Logs` folder; events before folder selection are queued privately and exported when the folder is configured.

Restore supports QNAP Library parents with mode 0777 without changing permissions or ACLs. On legacy ZFS the move is limited to the recorded Plex/private-workspace directory pairs, with source and destination identity checks and retained-original recovery. Keep Plex stopped and do not modify these directories during Restore.
