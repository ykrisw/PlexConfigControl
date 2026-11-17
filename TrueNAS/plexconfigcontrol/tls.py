"""Persistent application TLS identity, stored only in the application volume."""
import ipaddress
import os
import shutil
import ssl
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


def ensure_tls(state_directory,public_host):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    if not isinstance(public_host,str) or not public_host or len(public_host)>253:
        raise ValueError('A public IP address or DNS name is required')
    try:
        host=x509.IPAddress(ipaddress.ip_address(public_host))
    except ValueError:
        import re
        if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?',public_host):
            raise ValueError('Invalid public host') from None
        host=x509.DNSName(public_host)
    state=Path(state_directory); target=state/'tls'
    cert=target/'panel.crt'; key=target/'panel.key'
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_dir() or cert.is_symlink() or key.is_symlink():
            raise ValueError('Invalid TLS storage')
        # Never silently replace a damaged or incomplete identity.
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert,key)
        if key.stat().st_mode & 0o077: raise ValueError('TLS key permissions are too broad')
        saved=x509.load_pem_x509_certificate(cert.read_bytes())
        names=saved.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        if host not in names: raise ValueError('Public host differs from the saved TLS certificate')
        if saved.not_valid_after_utc<=datetime.now(timezone.utc): raise ValueError('TLS certificate expired')
        return cert,key
    temporary=Path(tempfile.mkdtemp(prefix='.tls-',dir=state))
    try:
        private=ec.generate_private_key(ec.SECP256R1())
        now=datetime.now(timezone.utc)
        subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'PlexConfigControl')])
        certificate=(x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(private.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=825))
            .add_extension(x509.SubjectAlternativeName([host,x509.DNSName('localhost'),
                 x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False)
            .add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True)
            .sign(private,hashes.SHA256()))
        def write(name,data,mode):
            fd=os.open(temporary/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,mode)
            with os.fdopen(fd,'wb') as output:
                output.write(data); output.flush(); os.fsync(output.fileno())
        write('panel.key',private.private_bytes(serialization.Encoding.PEM,
              serialization.PrivateFormat.PKCS8,serialization.NoEncryption()),0o600)
        write('panel.crt',certificate.public_bytes(serialization.Encoding.PEM),0o644)
        os.rename(temporary,target)
        directory=os.open(state,os.O_RDONLY|os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if temporary.exists(): shutil.rmtree(temporary)
    return cert,key
