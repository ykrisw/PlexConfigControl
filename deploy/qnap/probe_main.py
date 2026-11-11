"""Developer-only, read-only API compatibility probe; not an installer."""


def probe_main():
    import getpass
    import os
    from pathlib import Path

    # In the self-contained build these names are defined by the bundled
    # standard-library-only discovery and API modules above this entry point.
    print('PlexConfigControl — test odczytu API QNAP', flush=True)
    print('Test nie tworzy, nie usuwa i nie przywraca migawek.', flush=True)
    api = None
    try:
        installation = discover_qnap_plex()
        print('Wykryty identyfikator wolumenu Plexa:', installation.volume_id)
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
        print('Logowanie: OK')
        count = api.snapshot_count(installation.volume_id)
        print('Licznik migawek z API:', count, flush=True)
        rows = api.snapshots(installation.volume_id)
        print('Odczyt listy: OK')
        print('Liczba zwróconych wpisów:', len(rows))
        if len(rows) != count:
            raise QnapApiError('QNAP_INVENTORY_COUNT_CHANGED_OR_INCOMPLETE')
        print('Zgodność licznika i listy: OK')
        return 0
    except (QnapApiError, QnapDiscoveryError) as error:
        print('Wynik testu:', str(error), flush=True)
        return 1
    except Exception as error:
        # Never print response bodies, session tokens or request targets.
        print('Wynik testu:', type(error).__name__, flush=True)
        return 1
    finally:
        if api is not None:
            api.forget_session()


if __name__ == '__main__':
    raise SystemExit(probe_main())
