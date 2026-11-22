# PlexConfigControl 1.6.2 — TrueNAS SCALE x86-64 (64-bit)

**Potwierdzona działająca wersja — 17.11.2026:** właściciel potwierdził wykonanie kopii i przywracanie oraz brak bieżących zastrzeżeń do wyglądu. [Zapis weryfikacji](VALIDATION-1.6.md) · [Plik i suma SHA-256](RELEASE-1.6.json).

[**Pobierz instalator TrueNAS SCALE x86-64 (64-bit) — 1.6.2**](https://github.com/ykrisw/PlexConfigControl/releases/download/v1.6.2/PlexConfigControl_TrueNAS_x86-64v1.6.2.zip)

Poprawka 1.6.2 obsługuje zaufanie do HTTPS przez uwierzytelnione SSH, odłączone API i naprawę połączenia bez reinstalacji. [Instrukcja HTTPS](INSTALL-EN.md#https-and-connection-repair-161). Poprzednia [wersja 1.6 pozostaje do pobrania](https://github.com/ykrisw/PlexConfigControl/releases/tag/v1.6).

Aplikacja działa na serwerze TrueNAS SCALE x86-64. ZIP zawiera narzędzia instalacyjne na komputer Windows x64, Linux x64 lub macOS Apple Silicon.

| Zawartość | Lokalizacja |
| --- | --- |
| Źródła aplikacji i panelu | [plexconfigcontrol](plexconfigcontrol/) |
| Instalatory i pakowanie | [deploy](deploy/) |
| Testy | [tests](tests/) |
| Kontenery | [Dockerfile](Dockerfile), [Dockerfile.worker](Dockerfile.worker) |
| Projekt i integracja | [design](design/) |
| Instrukcje | [Polski](INSTRUKCJA-PL.md), [English](INSTALL-EN.md) |
| Licencja | [LICENSE](LICENSE) |

Budowanie i testy uruchamiaj z katalogu TrueNAS. Automatyzacja jest w wymaganym przez GitHub katalogu `.github/workflows`.

[QNAP](../QNAP/README.md)
