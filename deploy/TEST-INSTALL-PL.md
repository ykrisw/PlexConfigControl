# PlexConfigControl — instalacja testowa dla TrueNAS SCALE

## Co zawiera ta paczka

To instalowalna wersja testowa panelu WWW: konto i logowanie, zmiana hasła,
zdjęcie konta, historia, język polski/angielski i motywy Light/Dark/System.
Ustawienia, sesje i certyfikat pozostają po restarcie aplikacji.

**Ta paczka NIE tworzy kopii Plex ani nie wykonuje Restore.** Nie steruje Plexem,
nie tworzy snapshotów i nie usuwa archiwów. Nowy formularz konfiguracji magazynu
jest w kodzie, ale nie został jeszcze podłączony do tej instalacji. Pierwszy test
wykonaj bez dostępu do danych Plex, bez klucza API, bez montowania konfiguracji
Plex i bez gniazda Dockera. Możesz testować panel, konto, zdjęcie i ustawienia.

Paczkę rozpakuj na swoim komputerze. W środku znajdziesz:

- `PlexConfigControl-test-image.tar.gz` — gotowy obraz, nie trzeba go kompilować.
- tę instrukcję oraz wersję angielską;
- `BUILD-INFO.txt` — dokładny commit źródłowy i data budowania;
- `SHA256SUMS` — sumy kontrolne.

## 1. Wczytaj gotowy obraz na TrueNAS

Skopiuj **tylko plik obrazu** przez SMB do dowolnego wybranego folderu na NAS-ie.
Nie używaj chronionego PBS-Data. W terminalu TrueNAS uruchom polecenie,
wpisując rzeczywistą ścieżkę do skopiowanego pliku:

```sh
sudo docker load --input '/TU/WPISZ/SCIEZKE/PlexConfigControl-test-image.tar.gz'
```

Oczekiwany wynik zawiera `Loaded image: plexconfigcontrol:test`.
Nie rozpakowuj samego pliku obrazu `.tar.gz`; `docker load` odczyta go bezpośrednio.

## 2. Ustal hasło do panelu

W tym samym terminalu uruchom:

```sh
sudo docker run --rm -it --entrypoint python plexconfigcontrol:test -m plexconfigcontrol.installation
```

Wpisz wybrane hasło i powtórz je. Podczas wpisywania nic się nie wyświetla.
Polecenie wypisze jeden wiersz zaczynający się od `pbkdf2-sha256$`.
Skopiuj CAŁY ten wiersz. To weryfikator hasła potrzebny w następnym kroku;
nie wklejaj go do rozmowy. Kontener pomocniczy usunie się po zakończeniu.

## 3. Dodaj aplikację w TrueNAS Apps

Otwórz **Apps → Discover Apps → Custom App** i użyj formularza instalacji
(**nie** opcji Install via YAML). Wpisz:

| Pole | Wartość |
| --- | --- |
| Application Name | `plexconfigcontrol-test` |
| Image Repository | `plexconfigcontrol` |
| Tag | `test` |
| Pull Policy | `Never pull image even if it’s not present on host` |
| Restart Policy | `Unless Stopped` |
| Privileged | wyłączone |
| Custom User, jeśli formularz tego wymaga | UID `568`, GID `568` |
| Host IP dla portu | `192.168.1.120` — albo adres Twojego TrueNAS |
| Host Port | `8787` — albo inny wolny port |
| Container Port / Protocol | `8443` / TCP |
| Web Portal Protocol / Path | HTTPS / `/` |

Pozostaw domyślne Entrypoint i Command. Dodaj zmienne środowiskowe:

| Name | Value |
| --- | --- |
| `PCC_PUBLIC_HOST` | `192.168.1.120` — ten sam adres TrueNAS |
| `PCC_BOOTSTRAP_VERIFIER` | CAŁY wiersz `pbkdf2-sha256$...` z kroku 2 |

Hasło w postaci jawnej nie jest wpisywane do zmiennych kontenera.

## 4. Dodaj jeden nowy iXVolume na ustawienia

W sekcji **Storage** dodaj **ixVolume**, nazwij go `state` i ustaw Mount Path:

```text
/var/lib/plexconfigcontrol
```

Nowy wolumen musi umożliwiać zapis UID/GID 568. Jeśli formularz wymaga wpisu ACL,
nadaj go wyłącznie temu NOWEMU wolumenowi aplikacji. Nie włączaj Force ACL i nie
zmieniaj uprawnień istniejących datasetów. Nie dodawaj innych montowań do tego testu.

## 5. Zainstaluj i otwórz panel

Kliknij **Install** i poczekaj na RUNNING. Otwórz:

**https://192.168.1.120:8787**

Jeżeli wybrałeś inny adres/port, użyj ich w tym adresie. Panel ma własny
samopodpisany certyfikat, więc przeglądarka wyświetli ostrzeżenie. Sprawdź, że
adres jest Twoim TrueNAS, i zaakceptuj wyjątek dla tej aplikacji.
Zaloguj się hasłem wybranym w kroku 2, a nie wierszem weryfikatora.

## Czego oczekiwać i co sprawdzić

- Domyślnie motyw System. Sprawdź też Light/Dark i zmianę języka na polski.
- Dodaj zdjęcie konta, zmień je, a potem usuń.
- Change Password/Zmień hasło otwiera okno; poprawna zmiana kończy sesje.
- Wylogowanie i ponowne logowanie powinny działać. Brak automatycznego wylogowania
  za bezczynność jest celowy.
- Zrestartuj WYŁĄCZNIE `plexconfigcontrol-test` przez Apps: hasło, ustawienia,
  zdjęcie, historia i certyfikat powinny pozostać zachowane.
- **UNKNOWN/NIEZNANY przy Plex jest oczekiwane.** W tej konfiguracji nie ma
  połączenia API z TrueNAS. Nie oznacza to, że Plex przestał działać.
- Puste listy archiwów i zablokowane Create Backup/Restore są oczekiwane.
- Czyszczenie historii usuwa tylko zaznaczone wpisy panelu. Pobierane logi
  dotyczą tych wpisów, nie plików z produkcyjnej konfiguracji Plex.

Po pierwszym udanym logowaniu możesz usunąć `PCC_BOOTSTRAP_VERIFIER` z ustawień
tej aplikacji. Istniejące hasło nie jest resetowane przy kolejnych uruchomieniach.
Nie usuwaj iXVolume podczas aktualizacji/restartu, jeśli chcesz zachować dane panelu.

## Gdy aplikacja się nie uruchomi

W Apps otwórz logi `plexconfigcontrol-test`. Sprawdź adres `PCC_PUBLIC_HOST`,
pełny weryfikator, UID/GID oraz zapis do nowego iXVolume. Nie rozwiązuj problemu
przez nadanie roota, trybu Privileged, montowanie Docker socket ani zmianę ACL
danych Plex. Wklej komunikat błędu bez sekretów do rozmowy.

## Odinstalowanie

Usuń wyłącznie `plexconfigcontrol-test` przez TrueNAS Apps. Usunięcie jego iXVolume
usuwa konto, sesje, ustawienia, zdjęcie, historię i certyfikat tej aplikacji.
Pozostawienie iXVolume zachowuje je. Ten test nie modyfikuje danych Plex.
