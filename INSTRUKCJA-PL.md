# PlexConfigControl 1.0.10 — instalacja

Rozpakuj ZIP i otwórz instalator odpowiedni dla Twojego komputera.

| Komputer | Uruchom |
|---|---|
| macOS, Apple Silicon (M1 lub nowszy) | `PlexConfigControl Setup.app` |
| Windows 10/11, 64-bit | `Windows/PlexConfigControl Setup.exe` |
| Ubuntu 22.04+, Mint 21+, Debian 12+, 64-bit z pulpitem | `Linux/PlexConfigControl Setup` |

1. Wybierz **Polski** w oknie instalatora.
2. Wpisz adres TrueNAS i nazwę użytkownika z uprawnieniami administratora.
3. Kliknij **Połącz**. Klucz SSH jest opcjonalny. Jeśli potrzeba hasła konta
   TrueNAS, instalator zapyta o nie w maskowanym polu. Przy pierwszym połączeniu
   porównaj odcisk klucza SSH z serwerem, zanim go zatwierdzisz.
4. Przy nowej instalacji wybierz miejsce na kopie i nazwę folderu. Wpisz
   i powtórz własne hasło do panelu PlexConfigControl.
5. Zatwierdź podsumowanie. Okno pokaże bieżący etap i ruchomy pasek pracy.
   Pierwsza instalacja może potrwać kilka minut.
6. Po zakończeniu kliknij **Otwórz panel**.

Kreator sam rozpoznaje działającą instalację i proponuje aktualizację.
Aktualizacja zachowuje ustawienia, historię, archiwa i dotychczasowe hasło.
W razie błędu popraw wskazany problem i kliknij **Spróbuj ponownie**.
Wpisane ustawienia zostają w pamięci, dopóki okno instalatora jest otwarte.
Hasła nie są zapisywane na komputerze.

Jeśli instalacja została przerwana już po utworzeniu aplikacji w TrueNAS,
sprawdź jej stan w **Apps → Installed** przed kolejną próbą. Instalator
nie usuwa istniejącej aplikacji automatycznie.

## Wymagania

TrueNAS 25.10.8 lub nowszy, procesor x86-64, skonfigurowana pula Apps,
włączony SSH oraz konto z dostępem do sudo. Aplikacja Plex ma nazwę `plex`,
korzysta z oficjalnego obrazu i osobnego iXVolume `config`. Podczas instalacji
Plex musi działać. Folder archiwów wybierz w istniejącym datasecie na dane.
Prywatne pliki nowej instalacji trafiają do iXVolume `pcc`, a stan do `state`.
Kopie i logi trafiają do wybranego folderu.

Pakiety nie mają podpisu wydawcy. System komputera może wymagać zatwierdzenia
uruchomienia konkretnego pobranego instalatora. Na Linuksie plik wykonywalny
musi zachować uprawnienie do uruchamiania po rozpakowaniu ZIP-a.

Instalacja wymaga poprawnego certyfikatu HTTPS API TrueNAS oraz połączenia
NAS z rejestrami obrazów i repozytoriami pakietów. Aktualizacja wymaga
zgodnego obrazu Plexa z wersją, dla której zainstalowano PlexConfigControl.
Sprawdzono działanie na TrueNAS 25.10.8. Nowsze wersje wymagają osobnego
potwierdzenia zgodności.

Przywracanie konfiguracji wymaga zweryfikowania archiwum i ręcznego zatrzymania
Plexa. Po zakończeniu przywracania uruchom Plex ręcznie.

Licencja MIT. https://github.com/ykrisw/PlexConfigControl
