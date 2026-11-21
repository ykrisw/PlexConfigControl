"""Explicit public-certificate selection over the already authenticated SSH session."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import sys

MAX_PEM=262144
_PATTERN=re.compile(r'-----BEGIN CERTIFICATE-----\s*[A-Za-z0-9+/=\s]+?-----END CERTIFICATE-----')


def certificate_pem(value):
    """Strip everything except public certificates from a trusted NAS config file."""
    result='\n'.join(_PATTERN.findall(value))
    if not result:raise ValueError('Configured NAS public certificate is unavailable')
    return result+'\n'


def public_certificates(pem):
    if not isinstance(pem,str) or len(pem.encode())>MAX_PEM or 'PRIVATE KEY' in pem:
        raise ValueError('Choose public PEM certificates only; private keys are not accepted')
    certs=_PATTERN.findall(pem)
    remainder=_PATTERN.sub('',pem)
    if not certs or '-----BEGIN' in remainder or '-----END' in remainder:
        raise ValueError('Choose a PEM certificate or CA bundle')
    ssl.create_default_context(cadata=pem)
    fingerprints=[hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert)).hexdigest().upper() for cert in certs]
    return [':'.join(value[i:i+2] for i in range(0,len(value),2)) for value in fingerprints]


def select_certificate(host,verify,language='pl'):
    pl=language=='pl'
    message_pl=f'Wybierz publiczny certyfikat CA dla TrueNAS {host}. Sprawdź odcisk SHA-256 przed zatwierdzeniem. Klucz prywatny nie jest potrzebny.'
    message_en=f'Choose the public CA certificate for TrueNAS {host}. Check its SHA-256 fingerprint before trusting it. No private key is needed.'
    while True:
        if os.environ.get('PCC_SETUP_PROTOCOL')=='1':
            from .setup_protocol import emit
            emit('prompt',input_kind='certificate',message=message_pl,message_en=message_en,
                 secret=False,choices=[],confirmation=None,context='')
            reply=json.loads(sys.stdin.readline())
            encoded=reply.get('answer') if isinstance(reply,dict) else None
            if not encoded:raise ValueError('Certificate selection cancelled')
            if len(encoded)>MAX_PEM*2:raise ValueError('Certificate file is too large')
            pem=base64.b64decode(encoded,validate=True).decode('utf-8')
        else:
            print(message_pl if pl else message_en,flush=True)
            path=input('Publiczny plik CA na TrueNAS (PEM/CRT), Enter = anuluj: ' if pl else 'Public CA file on TrueNAS (PEM/CRT), Enter = cancel: ').strip()
            if not path:raise ValueError('Certificate selection cancelled')
            source=Path(path)
            if not source.is_absolute() or source.is_symlink() or not source.is_file() or source.stat().st_size>MAX_PEM:
                raise ValueError('Choose a regular public certificate file')
            pem=source.read_text()
        try:
            fingerprints=public_certificates(pem)
            if os.environ.get('PCC_SETUP_PROTOCOL')!='1':
                print('SHA-256: '+'; '.join(fingerprints),flush=True)
                if input('Wpisz ZAUFAJ, aby zatwierdzić CA: ' if pl else 'Type TRUST to approve this CA: ').strip() not in (('ZAUFAJ',) if pl else ('TRUST',)):
                    raise ValueError('Certificate trust was not approved')
            verify(pem)
            return pem
        except (ssl.SSLError,ValueError) as error:
            if isinstance(error,ssl.SSLCertVerificationError):
                print(('Certyfikat nadal nie przechodzi weryfikacji: ' if pl else 'Certificate verification still fails: ')+str(error.verify_message),flush=True)
            else:print(str(error),flush=True)


def trusted_issuer_chain(leaf_pem,candidates):
    """Use only an issuer cryptographically bound to the certificate read over SSH.

    Desktop keychains can include unrelated or distrusted certificates. They are
    candidates, never wholesale trust: every link must sign the trusted NAS leaf.
    """
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        leaf=x509.load_pem_x509_certificate(_PATTERN.search(leaf_pem)[0].encode())
        import warnings
        from cryptography.utils import CryptographyDeprecationWarning
        certs=[]
        for pem in _PATTERN.findall(candidates):
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore',CryptographyDeprecationWarning)
                    candidate=x509.load_pem_x509_certificate(pem.encode())
                    if candidate.serial_number>0:certs.append(candidate)
            except ValueError:continue
        current=leaf;chain=[];seen=set()
        for depth in range(12):
            for issuer in certs:
                identifier=issuer.public_bytes(serialization.Encoding.DER)
                if identifier in seen:continue
                try:
                    if not issuer.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:continue
                    current.verify_directly_issued_by(issuer)
                except Exception:continue
                seen.add(identifier);chain.append(issuer);current=issuer
                if issuer.subject==issuer.issuer:
                    try:issuer.verify_directly_issued_by(issuer)
                    except Exception:return None
                    return ''.join(item.public_bytes(serialization.Encoding.PEM).decode() for item in chain)
                break
            else:return None
        return None
    except (ImportError,ValueError,AttributeError,TypeError):
        return None


def desktop_candidates():
    if os.environ.get('PCC_SETUP_PROTOCOL')!='1':return ''
    from .setup_protocol import emit
    emit('trust_candidates')
    reply=json.loads(sys.stdin.readline())
    encoded=reply.get('answer') if isinstance(reply,dict) else None
    if not isinstance(encoded,str) or len(encoded)>4194304:raise ValueError('Invalid public certificate candidates')
    data=base64.b64decode(encoded,validate=True)
    if len(data)>2097152 or b'PRIVATE KEY' in data:raise ValueError('Public certificates only')
    return data.decode('utf-8')
