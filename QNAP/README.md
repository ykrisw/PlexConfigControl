# PlexConfigControl 1.6 — QNAP QuTS hero x86-64 (64-bit)

[**Pobierz instalator QNAP QuTS hero 1.6**](https://github.com/ykrisw/PlexConfigControl/releases/download/v1.6/PlexConfigControlQuTShero_1.6.qpkg)

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
