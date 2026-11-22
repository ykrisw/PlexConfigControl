# PlexConfigControl 1.0.5 — instalacja

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

## HTTPS i naprawa połączenia (1.6.2)

Zwykła instalacja nie wymaga szukania pliku CA. Po uwierzytelnieniu serwera przez SSH kreator odczytuje publiczny certyfikat HTTPS skonfigurowany w TrueNAS. Może rozpoznać podpisującą CA w publicznych certyfikatach systemowych komputera. Obce certyfikaty nie stają się zaufane: łańcuch wystawcy musi kryptograficznie pasować do certyfikatu NAS-a odczytanego przez SSH. Gdy wystawca nie jest dostępny, kreator może zaufać temu konkretnemu certyfikatowi. Ręczny wybór publicznego pliku PEM jest wariantem awaryjnym. Klucz prywatny nie jest potrzebny.

Dla istniejącej aplikacji uruchom Setup i wybierz **Aktualizuj aplikację**, aby wgrać 1.6.2. Można zaktualizować także starą aplikację zatrzymaną lub niekończącą startu, jeśli pozwalają na to jej lokalne zapisy operacji. Następnie wybierz **Napraw połączenie**, jeśli zmienił się certyfikat lub CA API. Kreator potwierdzi certyfikat przez SSH, zmieni wyłącznie publiczny plik zaufania PCC i uruchomi PCC ponownie. Zachowuje ustawienia, klucze API, dane Plexa, archiwa i logi. Naprawa zaufania nie przerywa aktywnego zapisu; wcześniejsze zapisy odzyskiwania i migawki pozostają do sprawdzenia po odzyskaniu połączenia.

Odnowienie certyfikatu pod tą samą zapisaną CA działa automatycznie. Zmiana CA lub odnowienie certyfikatu przypiętego bez CA wymaga naprawy przez niezależnie uwierzytelnione SSH. Panel pozostaje dostępny i wyświetla konkretną przyczynę problemu. Certyfikat wygasły albo niepasujący do adresu NAS-a wymaga poprawienia konfiguracji HTTPS w TrueNAS — weryfikacja certyfikatów nie jest wyłączana.

Jeżeli certyfikat HTTPS obejmuje nazwę DNS NAS-a zamiast jego numerycznego IP, wpisz tę nazwę DNS w Setup. Instalator zachowa ją do weryfikacji nazwy i sprawdzi, czy wskazuje instalowany NAS. Adresu nieobecnego w certyfikacie nie naprawia się przez wyłączenie weryfikacji.
