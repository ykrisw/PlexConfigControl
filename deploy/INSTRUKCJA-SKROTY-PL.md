# Uruchamianie instalatora z komputera

Rozpakuj cały ZIP. Dwukrotnie kliknij plik właściwy dla Twojego komputera.

- Windows 10 lub 11 — `PlexConfigControl_Windows.cmd`
- macOS — `PlexConfigControl_macOS.command`
- Debian, Linux Mint lub Ubuntu z pulpitem — `PlexConfigControl_Linux.desktop`

Obok skrótu musi leżeć `PlexConfigControl_Instalator.py` z tej samej paczki.
Skrót zapyta o adres TrueNAS i użytkownika SSH z dostępem do `sudo`, prześle
instalator i otworzy kreator w oknie terminala. Hasła podajesz w zwykłych
pytaniach SSH i TrueNAS. Skrót ich nie zapisuje. Windows może poprosić o
logowanie SSH osobno podczas przesyłania i uruchamiania.

TrueNAS musi mieć już skonfigurowany dostęp przez SSH dla tego użytkownika.
Na Windows potrzebny jest również składnik OpenSSH Client z poleceniami
`ssh.exe` i `scp.exe`. Na Linuksie potrzebne są polecenia `ssh` i `scp`
z pakietu `openssh-client`. Przy pierwszym połączeniu zweryfikuj klucz
hosta przed zaakceptowaniem go w SSH.

Na Linuksie zostaw skrót w rozpakowanym folderze razem z pozostałymi
plikami. Jeśli pulpit pyta, czy zezwolić na uruchomienie, zatwierdź
konkretny skrót. Jeśli menedżer plików otwiera skrót jako tekst, możesz
uruchomić wspólny skrypt SSH z terminala w rozpakowanym folderze.

```sh
bash ./PlexConfigControl_macOS.command
```

Jeśli macOS zablokuje skrót, możesz dopuścić ten konkretny plik w
Ustawieniach systemowych → Prywatność i ochrona. To pobrany skrypt bez
podpisu wydawcy.
