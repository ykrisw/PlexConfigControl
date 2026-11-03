"""Verified TLS WebSocket transport for the restricted TrueNAS RPC client."""
import ssl
from urllib.parse import urlsplit
from .rpc import TrueNASClient

class SecureWebSocket:
    def __init__(self,ca_file=None,timeout=30,connector=None):
        if not 0<timeout<=600: raise ValueError('Invalid network timeout')
        self.context=ssl.create_default_context(cafile=ca_file)
        self.context.minimum_version=ssl.TLSVersion.TLSv1_2
        self.timeout=timeout
        self.connector=connector

    def __call__(self,url):
        return self.connect_with_timeout(url,self.timeout)

    def connect_with_timeout(self,url,timeout):
        if not 0<timeout<=600: raise ValueError('Invalid network timeout')
        parsed=urlsplit(url)
        if parsed.scheme!='wss' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('WSS endpoint required')
        connector=self.connector
        if connector is None:
            from websocket import create_connection
            connector=create_connection
        return connector(url,timeout=min(self.timeout,timeout),
                         sslopt={'context':self.context},redirect_limit=0,
                         http_no_proxy=['*'],enable_multithread=True)


def build_client(url,username,api_key,ca_file=None,timeout=30):
    if not username or not api_key:
        raise ValueError('TrueNAS API username and key are required')
    return TrueNASClient(url,username,api_key,SecureWebSocket(ca_file,timeout),timeout=timeout)
