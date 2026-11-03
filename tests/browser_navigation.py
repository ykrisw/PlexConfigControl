"""Bounded retries for initial local-fixture GET navigation, never app actions."""
import time
from urllib.parse import urlsplit


def open_fixture(page, url, *, pause=time.sleep):
    target=urlsplit(url)
    if (target.scheme!='https' or target.hostname not in ('127.0.0.1','localhost')
            or target.username or target.password or target.path not in ('','/')
            or target.query or target.fragment):
        raise ValueError('Only the local HTTPS fixture root may be retried')
    for attempt in range(3):
        try:
            return page.goto(url)
        except Exception as error:
            if 'net::ERR_NETWORK_CHANGED' not in str(error) or attempt==2:
                raise
            pause(.5)
