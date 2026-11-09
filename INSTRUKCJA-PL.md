# PlexConfigControl Release Candidate

## Wymagania

- TrueNAS w wersji stabilnej **25.10.8 lub nowszej**, procesor **x86-64 (amd64)** oraz skonfigurowana pula Apps. Na TrueNAS 25.10.8 sprawdzono dotychczasowy przebieg instalacji i działania aplikacji. Zgodność z każdą nowszą wersją TrueNAS oraz pełny przebieg tego wydania RC od zera wymagają potwierdzenia na rzeczywistym serwerze.
- Oficjalna aplikacja Plex o nazwie **`plex`** w TrueNAS Apps. Podczas instalacji Plex musi działać. Jego `/config` ma wskazywać osobny dataset ZFS, typowo `ixVolume` o nazwie `config`. Instalator wykrywa obraz `plexinc/pms-docker` i działającą wersję Plex SQLite. Własne obrazy lub obrazy bez działającej binarki Plex SQLite wykraczają poza zakres tego wydania.
- Istniejący dataset ZFS na archiwa, poza pamięcią Apps. Jeśli chcesz widzieć kopie przez SMB, wybierz dataset dostępny przez Twój udział. Instalator utworzy w nim nowy folder na archiwa i jego podfolder `Logs`.
- Lokalny Shell TrueNAS z dostępem przez `sudo`, dostępny port panelu, poprawny certyfikat HTTPS API TrueNAS oraz dostęp do rejestru obrazów Docker i repozytoriów pakietów wykorzystywanych podczas budowy.

## 1. Rozpakuj paczkę

Skopiuj `PlexConfigControl_RC_Install.zip` przez SMB na NAS. W przykładzie zastąp ścieżkę do ZIP-a swoją. Suma SHA-256 paczki jest podana przy pobraniu. Możesz ją porównać przed rozpakowaniem.

```bash
ZIP='/mnt/MojaPula/MojDataset/PlexConfigControl_RC_Install.zip'
PCC_DIR=$(sudo mktemp -d /var/tmp/pcc-rc.XXXXXXXX)
sudo install -m 600 -- "$ZIP" "$PCC_DIR/installer.zip" &&
sudo sha256sum "$PCC_DIR/installer.zip"
```

Jeśli suma się zgadza, w tym samym Shell wklej poniższy blok.

```bash
sudo python3 -m zipfile -e "$PCC_DIR/installer.zip" "$PCC_DIR" &&
sudo sh -c 'cd "$1" && sha256sum -c --quiet SHA256SUMS && exec sh INSTALUJ.sh' sh "$PCC_DIR/PlexConfigControl_RC_Install"
```

## 2. Odpowiedz na pytania kreatora

- Podaj lokalny adres IPv4 TrueNAS i pełną ścieżkę datasetu, np. `/mnt/MojaPula/MojDataset`.
- Zatwierdź domyślną nazwę folderu `Plex Config` i port `8787` lub wpisz własne. Jeśli folder o wybranej nazwie już istnieje, wybierz nową nazwę.
- Ustaw hasło do panelu PlexConfigControl. Skrypt zapyta o nie dwa razy i nie wyświetli go podczas pisania.
- Sprawdź podsumowanie i wpisz `przygotuj`. Powstanie dedykowane konto techniczne z rolami odczytu aplikacji i obsługi migawek oraz plik ustawień w prywatnym katalogu `/mnt/<nazwa-puli>/PCC-Private`. Ten katalog ma znajdować się poza udziałem SMB. Jeśli udostępniasz całą pulę, wskaż inny prywatny katalog opcją `--prywatny`.
- Po zbudowaniu obrazów sprawdź ścieżki i wpisz `plexconfigcontrol`. Aplikacja pojawi się w **Apps → Installed**. Instalator zweryfikuje gotowość panelu i workera.

Możesz też uruchomić kreator z opcjami, np. z inną nazwą folderu, prefiksem archiwum lub portem. Opcje sprawdzisz przez `sudo sh INSTALUJ.sh --help` z rozpakowanego katalogu.

### HTTPS TrueNAS

Kreator próbuje zweryfikować aktywny certyfikat TrueNAS. Jeśli certyfikat pasuje do nazwy DNS, użyj przy ponownym uruchomieniu opcji `--api-host nas.example.net`. Ta nazwa ma wskazywać na wybrany adres NAS również z kontenera. Jeśli potrzebna jest własna CA, wskaż jej **publiczny** plik PEM przez `--ca /ścieżka/do/ca.pem`.

Jeśli domyślny certyfikat TrueNAS pasuje tylko do `localhost`, możesz użyć dotychczasowej, poprawnej konfiguracji DNS i certyfikatu albo przygotować certyfikat LAN. W tym drugim przypadku wykonaj, podstawiając swój adres i prywatną ścieżkę z kreatora:

```bash
sudo sh "$PCC_DIR/PlexConfigControl_RC_Install/INSTALUJ.sh" certyfikat \
  --ip 192.168.1.120 --prywatny '/mnt/MojaPula/PCC-Private'
```

Następnie w **System → General → GUI → Settings** zapisz nazwę poprzedniego certyfikatu i wybierz `pcc_lan_https`. Zmienia to certyfikat **interfejsu administracyjnego TrueNAS**. Po zmianie przeglądarka może wymagać dodania publicznej CA do zaufanych. W razie potrzeby wróć do poprzedniego certyfikatu. Uruchom ponownie kreator z tym samym katalogiem prywatnym. [Ustawienia GUI TrueNAS](https://www.truenas.com/docs/scale/25.10/scaletutorials/systemsettings/general/).

### Wznowienie po błędzie

Jeżeli kreator zapisał `settings.json`, ale aplikacja jeszcze nie powstała, możesz ponowić etap instalacji bez tworzenia konta od nowa:

```bash
sudo sh "$PCC_DIR/PlexConfigControl_RC_Install/INSTALUJ.sh" \
  --wznow '/mnt/MojaPula/PCC-Private/settings.json'
```

Jeśli TrueNAS zdążył utworzyć aplikację lub jej wolumen, najpierw sprawdź stan w **Apps → Installed** i komunikat instalatora. Kreator zatrzyma się przy istniejącej aplikacji lub wolumenie. Do diagnozy udostępniaj komunikaty o błędach z pominięciem klucza API, hasła i zawartości prywatnych plików.

## 3. Pierwsze uruchomienie

Otwórz adres HTTPS podany przez instalator, np. `https://192.168.1.120:8787`, i zaloguj się hasłem z kreatora. Publiczny certyfikat panelu PlexConfigControl znajduje się w `/mnt/.ix-apps/app_mounts/plexconfigcontrol/state/tls/panel.crt`.

Przy uruchomionym Plexie utwórz kopię i poczekaj na weryfikację. Sprawdź archiwum w wybranym folderze oraz wpis w `Logs`. Przywracanie wymaga wcześniejszej weryfikacji archiwum i ręcznego zatrzymania aplikacji Plex. Po zakończeniu uruchamiasz Plex ręcznie.

## Zakres wydania

Paczka służy do świeżej instalacji z Shell TrueNAS. Zawiera kod potrzebny do zbudowania obrazów na NAS i instaluje aplikację zarządzaną przez TrueNAS Apps. Źródło i licencja MIT są w [repozytorium PlexConfigControl](https://github.com/ykrisw/PlexConfigControl).
