# PlexConfigControl — instalacja testowa na TrueNAS 25.10.7

To pierwsza wersja do sprawdzania panelu, logowania, historii i trwałości ustawień.
Nie wykonuje Backup ani właściwego Restore. Nie tworzy i nie usuwa snapshotów.
Nie podłączaj do niej konfiguracji Plex, urządzeń ZFS ani gniazda Dockera.

## Pobranie

W repozytorium GitHub otwórz **Actions → Build test installation**. Wybierz
zakończone zielonym wynikiem wykonanie i pobierz z sekcji **Artifacts** paczkę
**PlexConfigControl-test-installation**. Pobieranie może wymagać zalogowania do
GitHuba. Paczka zawiera obraz kontenera, instrukcje i sumę SHA256. Zwykły ZIP
ze źródłami repozytorium nie jest instalką. Paczka wygasa po 30 dniach.

## 1. Wczytaj obraz

Rozpakuj paczkę na komputerze. Skopiuj `PlexConfigControl-test-image.tar.gz`
przez SMB do wybranego folderu na NAS-ie. W shellu TrueNAS wpisz polecenie,
zastępując przykładową ścieżkę faktyczną lokalizacją pliku:

```sh
sudo docker load --input '/TU/WPISZ/SWOJA/SCIEZKE/PlexConfigControl-test-image.tar.gz'
```

Powinien zostać załadowany obraz `plexconfigcontrol:test`. To jednorazowy import
obrazu. Po sprawdzeniu instalacji plik instalacyjny można ręcznie usunąć.

## 2. Wybierz hasło

Ta paczka testowa używa dodatkowego kroku, żeby nie zapisywać jawnego hasła
w zmiennych kontenera. Uruchom:

```sh
sudo docker run --rm -it --entrypoint python plexconfigcontrol:test -m plexconfigcontrol.installation
```

Wpisz hasło i powtórz je. Podczas wpisywania nic się nie wyświetla. Skopiuj
wygenerowany wiersz zaczynający się od `pbkdf2-sha256$`. Nie wklejaj go do
rozmowy — to wrażliwy weryfikator hasła. Kontener pomocniczy usunie się sam.
Docelowy formularz wyboru hasła bezpośrednio przy instalacji nadal wymaga pracy.

## 3. Zainstaluj w Apps

Otwórz **Apps → Discover Apps → Custom App**. Użyj formularza, nie Install via YAML.

| Pole | Wartość |
| --- | --- |
| Application Name | `plexconfigcontrol-test` |
| Image Repository | `plexconfigcontrol` |
| Tag | `test` |
| Pull Policy | **Never pull image even if it’s not present on host** |
| Restart Policy | **Unless Stopped** |
| Privileged | Wyłączone |
| Custom User, jeśli potrzebny | UID `568`, GID `568` |
| Host IP | `192.168.1.120` |
| Host Port | `8787` lub inny wolny port |
| Container Port | `8443`, TCP |
| Portal Protocol / Path | HTTPS / `/` |

Pozostaw domyślne Entrypoint i Command. Dodaj zmienne środowiskowe:

| Name | Value |
| --- | --- |
| `PCC_PUBLIC_HOST` | `192.168.1.120` |
| `PCC_BOOTSTRAP_VERIFIER` | Cały wiersz wygenerowany w kroku 2 |

W **Storage** dodaj **ixVolume**, nazwij dataset `state`, a jako Mount Path wpisz:

```text
/var/lib/plexconfigcontrol
```

Nowy wolumen aplikacji musi być zapisywalny przez UID/GID 568. Jeśli formularz
wymaga wpisu ACL, nadaj go wyłącznie temu nowemu wolumenowi aplikacji. Nie używaj
Force ACL i nie zmieniaj uprawnień istniejących datasetów ani konfiguracji Plex.
Nie dodawaj żadnych innych montowań do pierwszego testu.

Po uruchomieniu aplikacji otwórz **https://192.168.1.120:8787**. Przeglądarka
ostrzeże o certyfikacie aplikacji, ponieważ jest samopodpisany. Certyfikat
pozostaje w iXVolume i nie zmienia się po restarcie aplikacji.

## Co sprawdzić

1. Logowanie wybranym hasłem i wygląd Dashboard.
2. Change Password: po zmianie następuje wylogowanie wszystkich sesji.
3. History: zdarzenia, zaznaczanie, filtry, pobieranie i potwierdzenie usuwania.
4. Restart wyłącznie tej aplikacji przez Apps: hasło, sesja, historia i certyfikat
   powinny pozostać zachowane.

**UNKNOWN przy Plex jest oczekiwane**, dopóki osobno nie skonfigurujemy odczytu
statusu z TrueNAS. Aplikacja nie zgaduje jego stanu. Backup jest jeszcze
nieukończony. Settings jest podłączony w paczkach nowszych od pierwszej wersji testowej;
pierwsza paczka zawiera jeszcze jego placeholder. Pobieranie logów dotyczy tekstu zapisanego przy zdarzeniach historii,
a nie pełnych operacyjnych plików `.log` z katalogu użytkownika.

Przy testowaniu usuwania historii pliki w `Plex Config/Logs` pozostają nietknięte.
Opcjonalną walidację archiwów opisuje `TEST-INSTALL.md`: katalog archiwów wolno
podłączyć wyłącznie do odczytu, bez zmieniania jego ACL i bez montowania live config.

Weryfikator startowy nie resetuje hasła przy kolejnych uruchomieniach. Po pierwszym
udanym logowaniu można usunąć zmienną `PCC_BOOTSTRAP_VERIFIER` w ustawieniach Apps.

## Odinstalowanie

Usuń `plexconfigcontrol-test` przez TrueNAS Apps. Usunięcie iXVolume usuwa konto,
ustawienia, sesje, historię WWW i certyfikat tej aplikacji. Zachowanie wolumenu
zachowuje te dane. Testowa aplikacja nie usuwa zewnętrznych archiwów ani ich logów.
