"""Kreator instalacji PlexConfigControl na TrueNAS."""
import argparse
import getpass
import ipaddress
import json
import os
import platform
import re
import socket
import ssl
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from plexconfigcontrol.host_install import APP, InstallError, LocalMiddleware, form_settings, require_truenas_version
from plexconfigcontrol.installation import password_verifier
from plexconfigcontrol.installation_storage import plan_storage
from plexconfigcontrol.plex_runtime import PlexRuntimeError, detect_plex_runtime
from plexconfigcontrol.plex_storage import _zfs

ROLES = ["APPS_READ", "FILESYSTEM_ATTRS_READ", "SNAPSHOT_READ", "SNAPSHOT_WRITE", "SNAPSHOT_DELETE"]
CERT_NAME = "pcc_lan_https"


def private_directory(path, *, create=False):
    if (not path.is_absolute() or len(path.parts) < 4 or path.parts[:2] != ("/", "mnt")
            or path.resolve() != path or path.parts[2].startswith(".")):
        raise ValueError("Wskaż prywatny katalog na puli danych, poza obszarem Apps.")
    if create:
        path.mkdir(mode=0o700, exist_ok=True)
    info = path.stat()
    if not path.is_dir() or info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError("Prywatny katalog musi należeć do roota i mieć uprawnienia 0700.")
    return path


def save(path, value, *, owner=0, mode=0o600):
    with path.open("x", encoding="utf-8") as file:
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
        probe.bind((str(ip), 0))


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


def settings(client, args, private):
    if client.call("app.query", [["name", "=", APP]]):
        raise ValueError("PlexConfigControl już istnieje w Apps. Ta paczka służy do nowej instalacji.")
    if client.call("app.ix_volume.query", [["app_name", "=", APP]]) != []:
        raise ValueError("Wolumen stanu PlexConfigControl już istnieje. Sprawdź poprzednią instalację.")
    reference, sqlite_version, _, _ = detect_plex_runtime()
    api = LocalMiddleware()
    parent = args.archiwa
    if parent.resolve() != parent or not parent.is_dir():
        raise ValueError("Wskaż rzeczywisty, istniejący katalog archiwów pod /mnt.")
    apps_dataset = client.call("docker.config").get("dataset")
    archive_dataset, _ = _zfs(api, str(parent))
    if not apps_dataset or archive_dataset == apps_dataset or archive_dataset.startswith(apps_dataset + "/"):
        raise ValueError("Wybierz katalog archiwów poza pamięcią TrueNAS Apps.")
    plan = plan_storage(api, str(parent), folder_name=args.folder, archive_prefix=args.prefiks)
    if archive_dataset == plan.plex.dataset or archive_dataset.startswith(plan.plex.dataset + "/"):
        raise ValueError("Archiwa muszą być poza datasetem konfiguracji Plexa.")
    target = parent / plan.naming.folder_name
    if private == target or private in target.parents or target in private.parents:
        raise ValueError("Katalog prywatny i folder kopii muszą być osobne.")

    ca = private / "truenas-ca.pem"
    key, verifier, config = (private / name for name in ("truenas-key", "panel-verifier", "settings.json"))
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

    if any(path.exists() or path.is_symlink() for path in (key, verifier, config)) or any(
        client.call(method, [[field, "=", APP]])
        for method, field in (("user.query", "username"), ("group.query", "name"),
                              ("privilege.query", "name"), ("api_key.query", "name"))
    ):
        raise ValueError("Konto lub pliki przygotowania już istnieją. Przerwano bez nadpisywania.")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((str(args.ip), args.port))
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
    password = getpass.getpass("Nowe hasło do panelu PlexConfigControl: ")
    if not password or password != getpass.getpass("Powtórz hasło: "):
        raise ValueError("Hasła są puste lub różnią się.")
    encoded = password_verifier(password)
    del password

    print(f"Dataset Plexa: {plan.plex.dataset}\nObraz Plexa: {reference}\nPlex SQLite: {sqlite_version}"
          f"\nFolder kopii: {target}\nPanel: https://{args.ip}:{args.port}")
    if input("Wpisz przygotuj, aby utworzyć konto techniczne i pliki: ") != "przygotuj":
        raise ValueError("Przygotowanie anulowane.")

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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("krok", nargs="?", default="instaluj", choices=("certyfikat", "ustawienia", "instaluj"))
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
    os.umask(0o077)
    from truenas_api_client import Client
    try:
        if args.wznow:
            return subprocess.call(["sh", "deploy/install.sh", str(args.wznow)])
        args.ip = args.ip or ipaddress.IPv4Address(input("Adres IPv4 TrueNAS: ").strip())
        if args.krok != "certyfikat":
            args.archiwa = args.archiwa or Path(input("Ścieżka istniejącego datasetu na kopie (pod /mnt): ").strip())
            if args.folder is None:
                args.folder = input("Nazwa nowego folderu kopii [Plex Config]: ").strip() or "Plex Config"
            if args.port is None:
                args.port = int(input("Port panelu [8787]: ").strip() or "8787")
            if not 1024 <= args.port <= 65535:
                raise ValueError("Podaj port od 1024 do 65535.")
            if not args.archiwa.is_absolute() or len(args.archiwa.parts) < 3 or args.archiwa.parts[1] != "mnt":
                raise ValueError("Podaj pełną ścieżkę datasetu pod /mnt.")
            args.prywatny = args.prywatny or Path(*args.archiwa.parts[:3]) / "PCC-Private"
        elif args.prywatny is None:
            args.prywatny = Path(input("Prywatny katalog poza SMB (np. /mnt/Pula/PCC-Private): ").strip())
        with Client() as client:
            check_host(client, args.ip)
            private = private_directory(args.prywatny, create=True)
            if args.krok == "certyfikat":
                certificate(client, args.ip, private)
            else:
                config = settings(client, args, private)
        if args.krok == "instaluj":
            return subprocess.call(["sh", "deploy/install.sh", str(config)])
    except (ValueError, FileExistsError, FileNotFoundError, ssl.SSLError, InstallError, PlexRuntimeError) as error:
        parser.exit(1, f"Przerwano: {error}\n")
    except (Exception, KeyboardInterrupt) as error:
        parser.exit(1, f"Przerwano ({type(error).__name__}). Sprawdź stan konta i plików przed ponowieniem.\n")


if __name__ == "__main__":
    raise SystemExit(main())
