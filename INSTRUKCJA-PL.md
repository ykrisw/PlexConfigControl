# PlexConfigControl Release Candidate

## Wymagania

- TrueNAS w wersji stabilnej **25.10.8 lub nowszej**, procesor **x86-64 (amd64)** oraz skonfigurowana pula Apps. Na TrueNAS 25.10.8 sprawdzono dotychczasowy przebieg instalacji i działania aplikacji. Zgodność z każdą nowszą wersją TrueNAS oraz pełny przebieg tego wydania RC od zera wymagają potwierdzenia na rzeczywistym serwerze.
- Oficjalna aplikacja Plex o nazwie **`plex`** w TrueNAS Apps. Podczas instalacji Plex musi działać. Jego `/config` ma wskazywać osobny dataset ZFS, typowo `ixVolume` o nazwie `config`. Instalator wykrywa obraz `plexinc/pms-docker` i działającą wersję Plex SQLite. Własne obrazy lub obrazy bez działającej binarki Plex SQLite wykraczają poza zakres tego wydania.
- Istniejący dataset ZFS na archiwa, poza pamięcią Apps. Jeśli chcesz widzieć kopie przez SMB, wybierz dataset dostępny przez Twój udział. Instalator utworzy w nim nowy folder na archiwa i jego podfolder `Logs`.
- Lokalny Shell TrueNAS z dostępem przez `sudo`, dostępny port panelu, poprawny certyfikat HTTPS API TrueNAS oraz dostęp do rejestru obrazów Docker i repozytoriów pakietów wykorzystywanych podczas budowy.

## 1. Uruchom instalator

Skopiuj `PlexConfigControl_Instalator.py` przez SMB na TrueNAS. Wklej do Shell
poniższe polecenie ze ścieżką do skopiowanego pliku.

```bash
sudo python3 '/mnt/MojaPula/MojDataset/PlexConfigControl_Instalator.py'
```

Instalator sam sprawdza i rozpakowuje paczkę. Dla osobno pobranego ZIP-a
skorzystaj z poniższego bloku.

Skopiuj ZIP instalatora przez SMB na NAS. W poniższym bloku wpisz ścieżkę do pliku oraz sumę SHA-256 podaną przy pobraniu. Następnie wklej cały blok do Shell TrueNAS.

```bash
(
  set -e
  ZIP='/mnt/MojaPula/MojDataset/PlexConfigControl_RC_Install_Kreator.zip'
  SHA='WKLEJ_SUMĘ_SHA256_Z_LINKU'
  PCC_DIR=$(sudo mktemp -d /var/tmp/pcc-rc.XXXXXXXX)
  sudo install -m 600 -- "$ZIP" "$PCC_DIR/installer.zip"
  printf '%s  %s\n' "$SHA" "$PCC_DIR/installer.zip" | sudo sha256sum -c -
  sudo python3 -m zipfile -e "$PCC_DIR/installer.zip" "$PCC_DIR"
  PCC_START="$PCC_DIR/PlexConfigControl_RC_Install/INSTALUJ.sh"
  printf 'Kreator instalacji: %s\n' "$PCC_START"
  sudo sh "$PCC_START"
)
```

## 2. Odpowiedz na pytania kreatora

- Zatwierdź wykryty adres IPv4 TrueNAS klawiszem Enter albo wybierz numer, gdy adresów jest kilka. Możesz też wpisać adres ręcznie. Następnie wybierz dataset z listy lub wpisz ścieżkę, np. `/mnt/MojaPula/MojDataset`.
- Zatwierdź nazwę folderu kopii i port klawiszem Enter lub wpisz własne. Jeśli nazwa folderu jest zajęta, kreator szuka wolnej nazwy z numerem, np. `Plex Config 2`. Przy zajętym porcie proponuje pierwszy wolny port spośród dziesięciu kolejnych.
- Ustaw hasło do panelu PlexConfigControl. Skrypt zapyta o nie dwa razy i nie wyświetli go podczas pisania.
- Sprawdź podsumowanie i wpisz `tak`. Gdy kreator wykryje pozostałości po odinstalowanej aplikacji, wpisz `od nowa`, aby zastąpić jej konto techniczne i prywatne ustawienia. Dotychczasowe archiwa zachowują się w osobnym folderze. Jeśli w Apps nadal istnieje aplikacja albo jej wolumen stanu, kreator przerwie instalację.
- Kreator zapisze prywatne ustawienia w `/mnt/<nazwa-puli>/PCC-Private`. Wybierz katalog poza udziałami SMB. Jeśli udostępniasz całą pulę, wskaż prywatną ścieżkę przez `--prywatny`.
- Poczekaj na komunikat „PlexConfigControl gotowy” z adresem panelu. Aplikacja pojawi się w **Apps → Installed**. Pierwsza budowa obrazów może potrwać kilka minut.

Jeśli chcesz najpierw sprawdzić lokalne wymagania, użyj polecenia
`sudo sh "$PCC_START" sprawdz`. Sprawdzenie nie tworzy konta, plików ani
wolumenów. W dalszych przykładach w miejsce `$PCC_START` wstaw ścieżkę
wypisaną po rozpakowaniu albo ustaw tę zmienną na podaną ścieżkę.

### HTTPS TrueNAS

Kreator próbuje zweryfikować aktywny certyfikat TrueNAS. Jeśli certyfikat pasuje do nazwy DNS, użyj przy ponownym uruchomieniu opcji `--api-host nas.example.net`. Ta nazwa ma wskazywać na wybrany adres NAS również z kontenera. Jeśli potrzebna jest własna CA, wskaż jej **publiczny** plik PEM przez `--ca /ścieżka/do/ca.pem`.

Jeśli domyślny certyfikat TrueNAS pasuje tylko do `localhost`, możesz użyć dotychczasowej, poprawnej konfiguracji DNS i certyfikatu albo przygotować certyfikat LAN. W tym drugim przypadku wykonaj, podstawiając swój adres i prywatną ścieżkę z kreatora:

```bash
sudo sh "$PCC_START" certyfikat \
  --ip 192.168.1.120 --prywatny '/mnt/MojaPula/PCC-Private'
```

Następnie w **System → General → GUI → Settings** zapisz nazwę poprzedniego certyfikatu i wybierz `pcc_lan_https`. Zmienia to certyfikat **interfejsu administracyjnego TrueNAS**. Po zmianie przeglądarka może wymagać dodania publicznej CA do zaufanych. W razie potrzeby wróć do poprzedniego certyfikatu. Uruchom ponownie kreator z tym samym katalogiem prywatnym. [Ustawienia GUI TrueNAS](https://www.truenas.com/docs/scale/25.10/scaletutorials/systemsettings/general/).

### Wznowienie po błędzie

Jeżeli kreator zapisał `settings.json`, ale aplikacja jeszcze nie powstała, możesz ponowić etap instalacji bez tworzenia konta od nowa.

Jeśli używasz jednoplikowego instalatora, skopiuj polecenie wznowienia wypisane
przez kreator. Wskazuje ono pobrany plik `PlexConfigControl_Instalator.py` i
zapisany plik ustawień. Dla instalacji z rozpakowanego ZIP-a użyj poniższego
polecenia.

```bash
sudo sh "$PCC_START" \
  --wznow '/mnt/MojaPula/PCC-Private/settings.json'
```

Jeśli TrueNAS zdążył utworzyć aplikację lub jej wolumen, najpierw sprawdź stan w **Apps → Installed** i komunikat instalatora. Kreator zatrzyma się przy istniejącej aplikacji lub wolumenie. Do diagnozy udostępniaj komunikaty o błędach z pominięciem klucza API, hasła i zawartości prywatnych plików.

## 3. Pierwsze uruchomienie

Otwórz adres HTTPS podany przez instalator, np. `https://192.168.1.120:8787`, i zaloguj się hasłem z kreatora. Publiczny certyfikat panelu PlexConfigControl znajduje się w `/mnt/.ix-apps/app_mounts/plexconfigcontrol/state/tls/panel.crt`.

Przy uruchomionym Plexie utwórz kopię i poczekaj na weryfikację. Sprawdź archiwum w wybranym folderze oraz wpis w `Logs`. Przywracanie wymaga wcześniejszej weryfikacji archiwum i ręcznego zatrzymania aplikacji Plex. Po zakończeniu uruchamiasz Plex ręcznie.

## Zakres wydania

Paczka służy do świeżej instalacji z Shell TrueNAS. Zawiera kod potrzebny do zbudowania obrazów na NAS i instaluje aplikację zarządzaną przez TrueNAS Apps. Źródło i licencja MIT są w [repozytorium PlexConfigControl](https://github.com/ykrisw/PlexConfigControl).
