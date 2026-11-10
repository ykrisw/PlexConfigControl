"""Local HTTPS health probe with certificate verification, never insecure TLS."""
import os
import http.client
import ssl
import urllib.request
from pathlib import Path


def check_catalog_certificate(port):
    # Trust the exact certificate allocated to this container. It names the
    # NAS, while this local probe connects to the container's loopback address.
    pem=Path('/catalog-panel.crt').read_text(encoding='ascii')
    leaf=pem.split('-----END CERTIFICATE-----',1)[0]+'-----END CERTIFICATE-----'
    context=ssl.create_default_context(cadata=leaf)
    context.check_hostname=False
    context.verify_flags|=ssl.VERIFY_X509_PARTIAL_CHAIN
    conn=http.client.HTTPSConnection('127.0.0.1',port,timeout=5,context=context)
    try:
        conn.connect()
        if conn.sock.getpeercert(binary_form=True)!=ssl.PEM_cert_to_DER_cert(leaf):
            return 1
        conn.request('GET','/healthz')
        return 0 if conn.getresponse().status==200 else 1
    finally:
        conn.close()


def main():
    try:
        port=int(os.environ.get('PCC_PORT','8443'))
        if os.environ.get('PCC_CATALOG_CERTIFICATE')=='1':
            return check_catalog_certificate(port)
        state=Path(os.environ.get('PCC_STATE_DIRECTORY','/var/lib/plexconfigcontrol'))
        context=ssl.create_default_context(cafile=str(state/'tls'/'panel.crt'))
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=context))
        with opener.open(f'https://127.0.0.1:{port}/healthz',timeout=5) as result:
            return 0 if result.status==200 else 1
    except Exception: return 1


if __name__=='__main__': raise SystemExit(main())
