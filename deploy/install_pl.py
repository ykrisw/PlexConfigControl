"""Kreator instalacji PlexConfigControl na TrueNAS."""
import argparse
import errno
import getpass
import ipaddress
import json
import os
import platform
import re
import shlex
import socket
import ssl
import stat
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from plexconfigcontrol.host_install import APPS_MOUNT, APP, InstallError, LocalMiddleware, form_settings, require_truenas_version
from plexconfigcontrol.installation import password_verifier
from plexconfigcontrol.installation_storage import plan_storage
from plexconfigcontrol.naming import folder_component
from plexconfigcontrol.plex_runtime import PlexRuntimeError, detect_plex_runtime
from plexconfigcontrol.plex_storage import StorageDiscoveryError, _zfs
from plexconfigcontrol.storage import RenameRequired

ROLES = ["APPS_READ", "FILESYSTEM_ATTRS_READ", "SNAPSHOT_READ", "SNAPSHOT_WRITE", "SNAPSHOT_DELETE"]
CERT_NAME = "pcc_lan_https"
PREPARATION_FILES = ("truenas-key", "panel-verifier", "settings.json")
PREPARATION_RECORDS = (
    ("user.query", "username", "konto techniczne"),
    ("group.query", "name", "grupa techniczna"),
    ("privilege.query", "name", "uprawnienia techniczne"),
    ("api_key.query", "name", "klucz API"),
)


def private_directory(path):
    if (not path.is_absolute() or len(path.parts) < 4 or path.parts[:2] != ("/", "mnt")
            or path.resolve() != path or path.parts[2].startswith(".")):
        raise ValueError("Wskaż prywatny katalog na puli danych, poza obszarem Apps.")
    if not path.exists():
        if not path.parent.is_dir():
            raise ValueError("Katalog nadrzędny dla plików prywatnych musi już istnieć.")
        return path
    info = path.stat()
    if not path.is_dir() or info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError("Prywatny katalog musi należeć do roota i mieć uprawnienia 0700.")
    return path


def save(path, value, *, owner=0, mode=0o600):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        os.fchown(file.fileno(), owner, owner)
        os.fchmod(file.fileno(), mode)
        file.write(value)
        file.flush()
        os.fsync(file.fileno())


def check_host(client, ip):
    require_truenas_version(client.call("system.version"))
    if platform.machine() != "x86_64":
        raise ValueError("Wymagany jest procesor x86-64 (amd64).")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((str(ip), 0))
        except OSError:
            raise ValueError(f"Adres {ip} nie jest przypisany do tego serwera. Podaj lokalny adres IPv4 TrueNAS.") from None


def local_ipv4_addresses(client):
    try:
        rows = client.call("interface.ip_in_use", {"ipv4": True, "ipv6": False, "loopback": False, "any": False})
    except Exception:
        return []
    if not isinstance(rows, list):
        return []
    addresses = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("type") != "INET" or not isinstance(row.get("address"), str):
            continue
        try:
            address = ipaddress.IPv4Address(row["address"])
        except ValueError:
            continue
        if not (address.is_loopback or address.is_link_local or address.is_unspecified or address.is_multicast):
            addresses.add(address)
    return sorted(addresses)


def ask_ipv4_address(addresses):
    if len(addresses) > 1:
        print("Adresy IPv4 TrueNAS:")
        for index, address in enumerate(addresses, 1):
            print(f"  {index}. {address}")
        prompt = "Wybierz numer lub wpisz adres IPv4 TrueNAS: "
    elif addresses:
        prompt = f"Adres IPv4 TrueNAS [{addresses[0]}]: "
    else:
        prompt = "Adres IPv4 TrueNAS: "
    while True:
        entry = input(prompt).strip()
        if not entry and len(addresses) == 1:
            return addresses[0]
        try:
            if len(addresses) > 1 and entry.isascii() and entry.isdecimal():
                index = int(entry)
                if 1 <= index <= len(addresses):
                    return addresses[index - 1]
                raise ValueError
            return ipaddress.IPv4Address(entry)
        except ValueError:
            print("Podaj poprawny adres IPv4 lub wybierz numer z listy.", flush=True)


def panel_port_available(ip, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((str(ip), port))
        except OSError as error:
            if error.errno == errno.EADDRINUSE:
                return False
            raise ValueError(f"Nie można sprawdzić portu {port} pod adresem {ip}. Sprawdź adres IPv4 TrueNAS.") from None
    return True


def ask_panel_port(ip):
    default = 8787
    while True:
        prompt = f"Port panelu [{default}]: " if default is not None else "Port panelu: "
        entry = input(prompt).strip()
        try:
            port = int(entry or str(default))
        except ValueError:
            port = 0
        if not 1024 <= port <= 65535:
            print("Podaj port od 1024 do 65535.", flush=True)
            continue
        if panel_port_available(ip, port):
            return port
        print(f"Port {port} jest zajęty. Wybierz inny.", flush=True)
        default = next((candidate for candidate in range(port + 1, min(port + 11, 65536))
                        if panel_port_available(ip, candidate)), None)


def verified_ca(client, ui, ip, host, path, supplied):
    def verify(pem):
        context = ssl.create_default_context(cadata=pem)
        with socket.create_connection((str(ip), ui["ui_httpsport"]), timeout=8) as conn:
            with context.wrap_socket(conn, server_hostname=host):
                pass

    if path.is_symlink():
        raise ValueError("Plik CA nie może być dowiązaniem symbolicznym.")
    if path.exists() or supplied:
        pem = (path if path.exists() else supplied).read_text()
        verify(pem)
        return pem

    configured = ui.get("ui_certificate")
    cert_id = configured.get("id") if isinstance(configured, dict) else configured
    if type(cert_id) is int:
        cert = client.call("certificate.query", [["id", "=", cert_id]],
                           {"get": True, "select": ["certificate_path"]})
        if cert.get("certificate_path"):
            pem = Path(cert["certificate_path"]).read_text()
            try:
                verify(pem)
                return pem
            except ssl.SSLError:
                pass
    bundle = Path("/etc/ssl/certs/ca-certificates.crt")
    if bundle.is_file():
        pem = bundle.read_text()
        try:
            verify(pem)
            return pem
        except ssl.SSLError:
            pass
    raise ValueError("Certyfikat HTTPS TrueNAS nie pasuje do adresu lub brakuje zaufanej CA. "
                     "Sprawdź sekcję HTTPS w INSTRUKCJA-PL.md.")


def certificate(client, ip, private):
    ca_file = private / "truenas-ca.pem"
    if ca_file.exists() or client.call("certificate.query", [["name", "=", CERT_NAME]]):
        raise ValueError("Certyfikat lub plik CA już istnieje. Sprawdź stan przed ponowieniem.")
    with TemporaryDirectory(prefix="pcc-tls-") as temporary:
        root = Path(temporary)

        def openssl(*args):
            subprocess.run(["openssl", *args], cwd=root, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

        openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", "366",
                "-subj", "/CN=PlexConfigControl LAN CA", "-addext", "basicConstraints=critical,CA:TRUE",
                "-addext", "keyUsage=critical,keyCertSign,cRLSign", "-keyout", "ca.key", "-out", "ca.pem")
        openssl("req", "-new", "-newkey", "rsa:2048", "-nodes", "-subj", f"/CN={ip}",
                "-keyout", "server.key", "-out", "server.csr")
        (root / "server.ext").write_text(
            f"subjectAltName=IP:{ip}\n"
            "basicConstraints=critical,CA:FALSE\n"
            "keyUsage=critical,digitalSignature,keyEncipherment\n"
            "extendedKeyUsage=serverAuth\n"
            "authorityKeyIdentifier=keyid,issuer\n"
            "subjectKeyIdentifier=hash\n"
        )
        openssl("x509", "-req", "-in", "server.csr", "-CA", "ca.pem", "-CAkey", "ca.key",
                "-CAcreateserial", "-days", "365", "-sha256", "-extfile", "server.ext", "-out", "server.pem")
        openssl("verify", "-CAfile", "ca.pem", "-verify_ip", str(ip), "server.pem")
        client.call("certificate.create", {
            "name": CERT_NAME, "create_type": "CERTIFICATE_CREATE_IMPORTED",
            "certificate": (root / "server.pem").read_text(),
            "privatekey": (root / "server.key").read_text(),
        }, job=True)
        save(ca_file, (root / "ca.pem").read_text(), mode=0o644)
    print(f"Zaimportowano {CERT_NAME}. Wybierz go w ustawieniach HTTPS TrueNAS.")


def archive_parent(value):
    path = Path(value)
    if not path.is_absolute():
        path = Path("/mnt") / path
    if len(path.parts) < 3 or path.parts[:2] != ("/", "mnt") or ".." in path.parts:
        raise ValueError("Podaj ścieżkę datasetu, np. /mnt/Pula/Dataset albo Pula/Dataset.")
    return path


def available_archive_datasets(client):
    # Discovery is a convenience. The install preflight always verifies the
    # selected storage independently, including when the list is unavailable.
    try:
        apps = client.call("docker.config")["dataset"]
        rows = client.call("pool.dataset.query", [["type", "=", "FILESYSTEM"]], {
            "select": ["id", "mountpoint", "readonly"],
            "extra": {"flat": True, "retrieve_user_props": False},
        })
    except Exception:
        return []
    if not isinstance(rows, list):
        return []
    choices = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        dataset, mount = row.get("id"), row.get("mountpoint")
        if not isinstance(dataset, str) or not isinstance(mount, str) or not mount.startswith("/mnt/"):
            continue
        if apps and (dataset == apps or dataset.startswith(apps + "/")):
            continue
        path = Path(mount)
        if (len(path.parts) < 3 or not dataset.isprintable()
                or any(part.startswith(".") or not part.isprintable() for part in path.parts[2:])):
            continue
        readonly = row.get("readonly")
        if (isinstance(readonly, dict) and readonly.get("value") == "on") or not path.is_mount():
            continue
        choices[dataset] = path
    return sorted(choices.items())


def ask_archive_parent(choices=()):
    if choices:
        print("Wybierz dataset na kopie:")
        for index, (dataset, path) in enumerate(choices, 1):
            print(f"  {index}. {dataset} ({path})")
    while True:
        try:
            prompt = "Numer z listy lub własna ścieżka: " if choices else "Dataset na kopie [/mnt/Pula/Dataset]: "
            entry = input(prompt).strip()
            if choices and entry.isascii() and entry.isdecimal():
                index = int(entry)
                if not 1 <= index <= len(choices):
                    raise ValueError("Wybierz numer z listy lub wpisz pełną ścieżkę.")
                return choices[index - 1][1]
            return archive_parent(entry)
        except ValueError as error:
            print(error, flush=True)


def suggest_archive_folder(parent, base):
    if not os.path.lexists(parent / base):
        return base
    for number in range(2, 100):
        try:
            candidate = folder_component(f"{base} {number}")
        except ValueError:
            return None
        if not os.path.lexists(parent / candidate):
            return candidate
    return None


def ask_archive_folder(parent):
    default = suggest_archive_folder(parent, "Plex Config")
    while True:
        try:
            prompt = f"Nazwa nowego folderu kopii [{default}]: " if default else "Nazwa nowego folderu kopii: "
            folder = folder_component(input(prompt).strip() or default)
        except ValueError:
            print("Wpisz poprawną nazwę folderu, bez ukośników i znaków specjalnych.", flush=True)
            continue
        if not os.path.lexists(parent / folder):
            return folder
        print(f"Folder {parent / folder} już istnieje. Wpisz inną nazwę.", flush=True)
        default = suggest_archive_folder(parent, folder)


def resume_command(config):
    installer = os.environ.get("PCC_INSTALLER_FILE")
    if installer and Path(installer).is_absolute():
        command = ["sudo", "python3", installer]
    else:
        command = ["sudo", "sh", str(Path.cwd() / "INSTALUJ.sh")]
    return shlex.join([*command, "--wznow", str(config)])


def previous_preparation(client, private):
    files = [private / name for name in PREPARATION_FILES if os.path.lexists(private / name)]
    records = {}
    for method, field, label in PREPARATION_RECORDS:
        rows = client.call(method, [[field, "=", APP]])
        if not isinstance(rows, list) or len(rows) > 1:
            raise ValueError(f"Nie udało się sprawdzić poprzedniego przygotowania ({label}).")
        if rows:
            records[method] = rows[0]
    return files, records


def previous_preparation_summary(private, files, records):
    existing = [path.name for path in files]
    existing.extend(label for method, _, label in PREPARATION_RECORDS if method in records)
    return f"Znaleziono pozostałości poprzedniego przygotowania: {', '.join(existing)}. Katalog ustawień: {private}."


def check_previous_preparation(client, private):
    files, records = previous_preparation(client, private)
    if not (files or records):
        return
    message = previous_preparation_summary(private, files, records)
    if len(records) == len(PREPARATION_RECORDS) and len(files) == len(PREPARATION_FILES) and all(
        path.is_file() and not path.is_symlink() for path in files
    ):
        retry = resume_command(private / "settings.json")
        message += f"\nJeśli chcesz użyć zapisanych ustawień, uruchom:\n{retry}"
    message += "\nAby zacząć od nowa, uruchom kreator w trybie instalacji."
    raise ValueError(message)


def require_fresh_app(client):
    if client.call("app.query", [["name", "=", APP]]) != []:
        raise ValueError("PlexConfigControl już istnieje w Apps. Ta paczka służy do nowej instalacji.")
    if client.call("app.ix_volume.query", [["app_name", "=", APP]]) != []:
        raise ValueError("Wolumen stanu PlexConfigControl już istnieje. Sprawdź poprzednią instalację.")


def reset_previous_preparation(client, private, expected_files, expected_records):
    require_fresh_app(client)
    private_directory(private)
    files, records = previous_preparation(client, private)
    if files != expected_files or records != expected_records:
        raise ValueError("Poprzednie przygotowanie zmieniło się. Uruchom kreator ponownie.")

    for path in files:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid not in (0, 568) or info.st_mode & 0o077:
            raise ValueError(f"Nie można bezpiecznie usunąć pliku {path.name}.")

    user = records.get("user.query")
    group = records.get("group.query")
    privilege = records.get("privilege.query")
    key = records.get("api_key.query")
    if user and (user.get("full_name") != "PlexConfigControl" or user.get("builtin") is not False
                 or user.get("smb") is not False or user.get("password_disabled") is not True
                 or user.get("shell") != "/usr/sbin/nologin" or user.get("home") != "/var/empty"):
        raise ValueError("Konto o tej nazwie nie pasuje do konta technicznego instalatora.")
    if group and (group.get("builtin") is not False or group.get("smb") is not False
                  or set(group["users"]) - ({user["id"]} if user else set())):
        raise ValueError("Grupa nie pasuje do grupy technicznej instalatora lub ma innych użytkowników.")
    if privilege and (privilege.get("builtin_name") is not None or privilege["ds_groups"]
                      or set(privilege["roles"]) != set(ROLES) or privilege.get("web_shell") is not False
                      or any(not group or item.get("gid") != group["gid"] for item in privilege["local_groups"])):
        raise ValueError("Uprawnienia o tej nazwie nie pasują do ustawień instalatora.")
    if key and key.get("username") != APP:
        raise ValueError("Klucz API o tej nazwie należy do innego konta.")
    keys = client.call("api_key.query", [["username", "=", APP]], {"select": ["id"]})
    if keys != ([{"id": key["id"]}] if key else []):
        raise ValueError("Konto ma dodatkowe klucze API.")

    if key:
        client.call("api_key.delete", key["id"])
    if privilege:
        client.call("privilege.delete", privilege["id"])
    if user:
        client.call("user.delete", user["id"], {"delete_group": False})
    if group:
        client.call("group.delete", group["id"], {"delete_users": False})
    for path in files:
        path.unlink(missing_ok=True)
    print("Usunięto poprzednie przygotowanie PlexConfigControl.", flush=True)


def preflight(client, args, private, *, check_preparation=True):
    require_fresh_app(client)
    if check_preparation:
        check_previous_preparation(client, private)
    reference, sqlite_version, _, _ = detect_plex_runtime()
    api = LocalMiddleware()
    parent = args.archiwa
    if parent.resolve() != parent or not parent.is_dir():
        raise ValueError("Wskaż rzeczywisty, istniejący katalog archiwów pod /mnt.")
    apps_dataset = client.call("docker.config").get("dataset")
    if not apps_dataset or _zfs(api, APPS_MOUNT) != (apps_dataset, APPS_MOUNT):
        raise ValueError("Wybierz i uruchom pulę aplikacji w TrueNAS → Apps.")
    archive_dataset, _ = _zfs(api, str(parent))
    if archive_dataset == apps_dataset or archive_dataset.startswith(apps_dataset + "/"):
        raise ValueError("Wybierz katalog archiwów poza pamięcią TrueNAS Apps.")
    plan = plan_storage(api, str(parent), folder_name=args.folder, archive_prefix=args.prefiks)
    if archive_dataset == plan.plex.dataset or archive_dataset.startswith(plan.plex.dataset + "/"):
        raise ValueError("Archiwa muszą być poza datasetem konfiguracji Plexa.")
    target = parent / plan.naming.folder_name
    if private == target or private in target.parents or target in private.parents:
        raise ValueError("Katalog prywatny i folder kopii muszą być osobne.")

    ca = private / "truenas-ca.pem"
    key, verifier, _ = (private / name for name in PREPARATION_FILES)
    ui = client.call("system.general.config")
    https_port = ui["ui_httpsport"]
    api_host = args.api_host or str(args.ip)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", api_host):
        raise ValueError("Podaj nazwę DNS bez schematu, portu i ścieżki.")
    addresses = {info[4][0] for info in socket.getaddrinfo(api_host, https_port, type=socket.SOCK_STREAM)}
    if addresses != {str(args.ip)}:
        raise ValueError("Nazwa API musi wskazywać wyłącznie podany adres TrueNAS.")
    pem = verified_ca(client, ui, args.ip, api_host, ca, args.ca)
    print("Certyfikat API TrueNAS zweryfikowany.")

    if not panel_port_available(args.ip, args.port):
        raise ValueError(f"Port {args.port} jest zajęty pod adresem {args.ip}. Wybierz inny port.")
    values = {
        "panel": {"host_ip": str(args.ip), "host_port": args.port, "verifier_file": str(verifier)},
        "backup": {"archive_parent": str(parent), "folder_name": plan.naming.folder_name,
                   "archive_prefix": plan.naming.archive_prefix},
        "connection": {"api_url": f"wss://{api_host}:{https_port}/api/current", "api_user": APP,
                       "api_key_file": str(key), "api_ca_file": str(ca)},
        "plex": {"storage_mode": "automatic"},
    }
    form_settings(values, panel_image="plexconfigcontrol:0.1.0",
                  worker_image="plexconfigcontrol-worker:0.1.0-base", sqlite_version=sqlite_version)
    print(f"Dataset Plexa: {plan.plex.dataset}\nObraz Plexa: {reference}\nPlex SQLite: {sqlite_version}"
          f"\nFolder kopii: {target}\nPanel: https://{args.ip}:{args.port}"
          f"\nPrywatne pliki instalacji: {private}", flush=True)
    return values, pem


def ask_password_verifier():
    while True:
        password = getpass.getpass("Nowe hasło do panelu PlexConfigControl: ")
        if not password:
            print("Hasło nie może być puste.", flush=True)
        elif password != getpass.getpass("Powtórz hasło: "):
            print("Hasła się różnią. Wpisz je ponownie.", flush=True)
        else:
            try:
                return password_verifier(password)
            except ValueError:
                print("Hasło jest za długie. Wpisz krótsze.", flush=True)


def settings(client, args, private):
    values, pem = preflight(client, args, private, check_preparation=False)
    files, records = previous_preparation(client, private)
    replacing = bool(files or records)
    if replacing:
        print(previous_preparation_summary(private, files, records), flush=True)
        print("Ponowna instalacja zastąpi konto techniczne i ustawienia kreatora. Kopie i certyfikat CA zostaną zachowane.",
              flush=True)
    encoded = ask_password_verifier()

    action = "utworzyć konto techniczne i zainstalować aplikację" if args.krok == "instaluj" else "utworzyć konto techniczne i pliki"
    confirmation = "od nowa" if replacing else "tak"
    if input(f"Wpisz {confirmation}, aby {action}: ").strip().lower() != confirmation:
        raise ValueError("Przygotowanie anulowane.")

    if replacing:
        reset_previous_preparation(client, private, files, records)
    private.mkdir(mode=0o700, exist_ok=True)
    private_directory(private)
    require_fresh_app(client)
    check_previous_preparation(client, private)
    ca = private / "truenas-ca.pem"
    key, verifier, config = (private / name for name in PREPARATION_FILES)
    if not ca.exists():
        save(ca, pem, mode=0o644)
    group_id = client.call("group.create", {"name": APP, "smb": False})
    group = client.call("group.query", [["name", "=", APP]], {"get": True})
    client.call("privilege.create", {"name": APP, "local_groups": [group["gid"]],
                                     "roles": ROLES, "web_shell": False})
    client.call("user.create", {"username": APP, "full_name": "PlexConfigControl",
                                "group_create": False, "group": group_id, "password_disabled": True,
                                "smb": False, "home": "/var/empty", "shell": "/usr/sbin/nologin"})
    result = client.call("api_key.create", {"name": APP, "username": APP})
    save(key, result["key"] + "\n", owner=568)
    save(verifier, encoded + "\n", owner=568)
    save(config, json.dumps(values, indent=2, ensure_ascii=False) + "\n")
    print(f"Ustawienia instalatora gotowe. Plik {config}")
    return config


def deploy(config, *, confirmed=False):
    command = ["sh", "deploy/install.sh", str(config)]
    if confirmed:
        command.append("--confirmed")
    result = subprocess.call(command)
    if result:
        retry = resume_command(config)
        print(f"Jeśli PlexConfigControl nie pojawił się w Apps, możesz ponowić instalację:\n{retry}", flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("krok", nargs="?", default="instaluj", choices=("sprawdz", "certyfikat", "ustawienia", "instaluj"))
    parser.add_argument("--ip", type=ipaddress.IPv4Address)
    parser.add_argument("--api-host", help="Nazwa DNS w istniejącym certyfikacie HTTPS TrueNAS.")
    parser.add_argument("--ca", type=Path, help="Publiczny plik PEM zaufanej CA TrueNAS.")
    parser.add_argument("--prywatny", type=Path)
    parser.add_argument("--archiwa", type=Path)
    parser.add_argument("--folder")
    parser.add_argument("--prefiks", default="PlexConfig")
    parser.add_argument("--port", type=int)
    parser.add_argument("--wznow", type=Path, help="Plik settings.json z przerwanej instalacji.")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Uruchom polecenie przez sudo w Shell TrueNAS.")
    if args.wznow and args.krok != "instaluj":
        parser.error("--wznow służy wyłącznie do ponowienia instalacji.")
    # Private files and directories set their own modes. Keep the caller's
    # umask for the child installer that creates the archive and Logs folders.
    try:
        from truenas_api_client import Client
    except ImportError:
        parser.exit(1, "Uruchom kreator w Shell TrueNAS. Brakuje klienta API TrueNAS.\n")
    try:
        if args.wznow:
            return deploy(args.wznow)
        needs_dataset = args.krok != "certyfikat" and args.archiwa is None
        if args.ip is None or needs_dataset:
            with Client() as client:
                addresses = local_ipv4_addresses(client) if args.ip is None else []
                choices = available_archive_datasets(client) if needs_dataset else []
        if args.ip is None:
            args.ip = ask_ipv4_address(addresses)
        if needs_dataset:
            args.archiwa = ask_archive_parent(choices)
        if args.krok != "certyfikat":
            args.archiwa = archive_parent(args.archiwa)
            if args.folder is None:
                args.folder = ask_archive_folder(args.archiwa)
            if args.port is None:
                args.port = ask_panel_port(args.ip)
            if not 1024 <= args.port <= 65535:
                raise ValueError("Podaj port od 1024 do 65535.")
            args.prywatny = args.prywatny or Path(*args.archiwa.parts[:3]) / "PCC-Private"
            print(f"Wybrany folder kopii: {args.archiwa / args.folder}", flush=True)
        elif args.prywatny is None:
            args.prywatny = Path(input("Prywatny katalog poza SMB (np. /mnt/Pula/PCC-Private): ").strip())
        with Client() as client:
            check_host(client, args.ip)
            private = private_directory(args.prywatny)
            if args.krok == "certyfikat":
                private.mkdir(mode=0o700, exist_ok=True)
                private_directory(private)
                certificate(client, args.ip, private)
            elif args.krok == "sprawdz":
                preflight(client, args, private)
                print("Sprawdzono wymagania lokalne. Budowa obrazów i połączenie workera zostaną sprawdzone przy instalacji.")
            else:
                config = settings(client, args, private)
        if args.krok == "instaluj":
            return deploy(config, confirmed=True)
    except RenameRequired:
        parser.exit(1, "Wybrany folder kopii już istnieje. Podaj inną nazwę folderu.\n")
    except StorageDiscoveryError as error:
        parser.exit(1, f"Nie potwierdzono konfiguracji Plexa. Sprawdź, czy aplikacja plex działa i używa osobnego iXVolume dla /config ({error.code}).\n")
    except (ValueError, FileExistsError, FileNotFoundError, ssl.SSLError, InstallError, PlexRuntimeError) as error:
        parser.exit(1, f"Przerwano: {error}\n")
    except (EOFError, KeyboardInterrupt):
        parser.exit(1, "Przerwano przez użytkownika. Jeśli kreator rozpoczął instalację, sprawdź jej stan w Apps.\n")
    except Exception as error:
        parser.exit(1, f"Przerwano ({type(error).__name__}). Sprawdź stan konta i plików przed ponowieniem.\n")


if __name__ == "__main__":
    raise SystemExit(main())
