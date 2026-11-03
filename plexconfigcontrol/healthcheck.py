"""Local HTTPS health probe with certificate verification, never insecure TLS."""
import os
import ssl
import urllib.request
from pathlib import Path


def main():
    try:
        state=Path(os.environ.get('PCC_STATE_DIRECTORY','/var/lib/plexconfigcontrol'))
        context=ssl.create_default_context(cafile=str(state/'tls'/'panel.crt'))
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=context))
        port=int(os.environ.get('PCC_PORT','8443'))
        with opener.open(f'https://127.0.0.1:{port}/healthz',timeout=5) as result:
            return 0 if result.status==200 else 1
    except Exception: return 1


if __name__=='__main__': raise SystemExit(main())
