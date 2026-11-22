"""Verified TLS WebSocket transport for the restricted TrueNAS RPC client."""
import ssl
import hashlib
from pathlib import Path
from .installer_trust import read_leaf_pin
from urllib.parse import urlsplit
from .rpc import TrueNASClient

class SecureWebSocket:
    def __init__(self,ca_file=None,timeout=30,connector=None):
        if not 0<timeout<=600: raise ValueError('Invalid network timeout')
        self.ca_file=ca_file
        self.timeout=timeout
        self.connector=connector

    def _tls_config(self):
        pin = read_leaf_pin(Path(self.ca_file).read_text()) if self.ca_file else None
        context = (ssl.create_default_context(cadata=pin[0]) if pin else
                   ssl.create_default_context(cafile=self.ca_file))
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
        if pin:
            # Replace hostname verification only with a strict exact-leaf pin.
            context.check_hostname = False
        return context, pin

    @property
    def context(self):
        return self._tls_config()[0]

    def __call__(self,url):
        return self.connect_with_timeout(url,self.timeout)

    def connect_with_timeout(self,url,timeout):
        if not 0<timeout<=600: raise ValueError('Invalid network timeout')
        parsed=urlsplit(url)
        if parsed.scheme!='wss' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('WSS endpoint required')
        # Re-read trust each time; certificate replacement requires SSH repair.
        context, pin = self._tls_config()
        connector = self.connector
        if connector is None:
            from websocket import create_connection
            connector = create_connection
        connection = connector(url, timeout=min(self.timeout, timeout),
                               sslopt={'context':context}, redirect_limit=0,
                               http_no_proxy=['*'], enable_multithread=True)
        if pin:
            try:
                peer = connection.sock.getpeercert(binary_form=True)
                if not peer or hashlib.sha256(peer).hexdigest() != pin[1]:
                    raise ssl.SSLCertVerificationError('TrueNAS HTTPS leaf pin mismatch')
            except BaseException:
                connection.close()
                raise
        return connection


def build_client(url,username,api_key,ca_file=None,timeout=30):
    if not username or not api_key:
        raise ValueError('TrueNAS API username and key are required')
    return TrueNASClient(url,username,api_key,SecureWebSocket(ca_file,timeout),timeout=timeout)
