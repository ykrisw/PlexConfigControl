"""Fixed public connection diagnostics; never expose server exception text."""
import ssl

CODES = frozenset({'TLS_UNTRUSTED','TLS_HOSTNAME','TLS_EXPIRED','TLS_CA_UNAVAILABLE',
                   'TLS_INVALID','API_UNREACHABLE','API_AUTHENTICATION'})


def connection_code(error):
    if getattr(error, 'code', None) in CODES:
        return error.code
    if isinstance(error, ssl.SSLCertVerificationError):
        return {62:'TLS_HOSTNAME',64:'TLS_HOSTNAME',9:'TLS_EXPIRED',10:'TLS_EXPIRED'}.get(
            error.verify_code, 'TLS_UNTRUSTED')
    if isinstance(error, PermissionError):return None
    if isinstance(error, FileNotFoundError):
        return 'TLS_CA_UNAVAILABLE'
    if isinstance(error, ssl.SSLError):
        return 'TLS_INVALID'
    if isinstance(error, (OSError, TimeoutError)):
        return 'API_UNREACHABLE'
    return None
