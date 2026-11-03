"""Bounded local-fixture bootstrap GET retries; never retry mutating app calls."""
import time
from urllib.parse import urlsplit


def open_fixture(page, url, *, pause=time.sleep, ready_selector=None):
    target=urlsplit(url)
    if (target.scheme!='https' or target.hostname not in ('127.0.0.1','localhost')
            or target.username or target.password or target.path not in ('','/')
            or target.query or target.fragment):
        raise ValueError('Only the local HTTPS fixture root may be retried')
    for attempt in range(3):
        transient_assets=[]
        writes=[]
        def requested(request):
            if request.method not in ('GET','HEAD'):
                writes.append(True)
        def failed(request):
            parsed=urlsplit(request.url)
            if (request.method=='GET' and parsed.scheme==target.scheme and parsed.netloc==target.netloc
                    and parsed.path.startswith('/assets/') and parsed.path.endswith(('.mjs','.css'))
                    and 'net::ERR_NETWORK_CHANGED' in (request.failure or '')):
                transient_assets.append(parsed.path)
        page.on('request',requested)
        page.on('requestfailed',failed)
        try:
            response=page.goto(url)
            if ready_selector is not None:
                page.locator(ready_selector).wait_for(state='visible',timeout=8000)
            return response
        except Exception as error:
            transient=('net::ERR_NETWORK_CHANGED' in str(error) or bool(transient_assets))
            if not transient or writes or attempt==2:
                raise
            pause(.5)
            if writes:
                raise
        finally:
            page.remove_listener('request',requested)
            page.remove_listener('requestfailed',failed)
