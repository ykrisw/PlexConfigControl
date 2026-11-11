"""Explicit opt-in, developer-only snapshot lifecycle diagnostic."""


def snapshot_probe_main():
    import getpass
    import os
    import sys
    from pathlib import Path

    if sys.argv[1:] != ['--test-snapshot']:
        print('Test jednej tymczasowej migawki QNAP. Uruchom z --test-snapshot.')
        return 2
    print('PlexConfigControl — test migawki QNAP', flush=True)
    print('Utworzy jedną migawkę wolumenu Plexa, sprawdzi odczyt danych i usunie tę migawkę.')
    print('Nie zatrzymuje Plexa i nie przywraca danych. Nie usuwa istniejących migawek.', flush=True)
    api = None
    try:
        installation = discover_qnap_plex()
        print('Identyfikator wolumenu Plexa:', installation.volume_id)
        context, pin = local_certificate_context(Path('/etc/stunnel/stunnel.pem').read_text())
        api = QnapLocalReadOnlyApi(443, tls_context=context, certificate_sha256=pin)
        if api.probe()['root'] != 'QDocRoot':
            raise QnapApiError('QNAP_API_INVALID_XML')
        print('HTTPS i certyfikat: OK')
        default_user = os.environ.get('SUDO_USER') or getpass.getuser()
        username = input('Użytkownik QNAP ['+default_user+']: ').strip() or default_user
        password = getpass.getpass('Hasło konta QNAP: ')
        try:
            api.login(username, password)
        finally:
            del password
        print('Logowanie: OK', flush=True)
        labels = {
            'CREATING': 'Tworzenie migawki testowej',
            'CREATED': 'Utworzono migawkę — ID',
            'READ_ONLY_PLEX_DATA_CONFIRMED': 'Odczyt plików Plexa z migawki tylko do odczytu: OK — ID',
            'CLEANUP_CONFIRMED': 'Usunięcie migawki potwierdzone przez API i ZFS — ID',
        }
        probe = OwnedSnapshotProbe(api, installation,
            report=lambda stage, value: print(labels[stage]+': '+str(value), flush=True))
        result = probe.run()
        if result['error']:
            print('Błąd testu:', result['error'], flush=True)
        if result['cleanup_error']:
            print('NIE POTWIERDZONO USUNIĘCIA:', result['cleanup_error'])
            print('Nazwa migawki:', result['name'])
            print('ID migawki:', result['id'] or 'nieustalone')
            print('Zażądano wygaśnięcia po 15 minutach; nie zastępuje to potwierdzenia usunięcia.')
        if result['created'] and result['readable'] and result['cleanup_confirmed'] and not result['error']:
            print('Wynik całego testu: OK', flush=True)
            return 0
        return 1
    except (QnapApiError, QnapDiscoveryError, SnapshotProbeError) as error:
        print('Wynik testu:', str(error), flush=True)
        return 1
    except (Exception, KeyboardInterrupt) as error:
        print('Wynik testu:', type(error).__name__, flush=True)
        return 1
    finally:
        if api is not None:
            api.forget_session()


if __name__ == '__main__':
    raise SystemExit(snapshot_probe_main())
