"""First-install password verifier: plaintext never enters container config."""
import getpass
import re
import secrets
from .auth import Account, ITERATIONS


def password_verifier(password):
    if not isinstance(password,str) or not 1<=len(password)<=4096:
        raise ValueError('A password is required')
    salt=secrets.token_bytes(32)
    digest=Account.derive(password,salt,ITERATIONS)
    return f'pbkdf2-sha256${ITERATIONS}${salt.hex()}${digest.hex()}'


def initialize_from_verifier(account,verifier,*,catalog=False):
    if not isinstance(verifier,str) or len(verifier)>256:
        raise ValueError('Invalid installation verifier')
    if catalog:
        # TrueNAS renders its password field to a bcrypt verifier before passing it to Compose.
        if not re.fullmatch(r'\$2b\$12\$[./A-Za-z0-9]{53}',verifier):
            raise ValueError('Invalid catalog installation verifier')
        salt,digest,iterations=b'',verifier.encode('ascii'),0
    else:
        match=re.fullmatch(r'pbkdf2-sha256\$([0-9]{6,7})\$([0-9a-f]{64})\$([0-9a-f]{64})',verifier)
        if not match or not 600_000<=int(match[1])<=2_000_000:
            raise ValueError('Invalid installation verifier')
        salt,digest,iterations=bytes.fromhex(match[2]),bytes.fromhex(match[3]),int(match[1])
    with account.connect() as db:
        db.execute('INSERT INTO account(id,salt,digest,iterations) VALUES(1,?,?,?)',
                   (salt,digest,iterations))


def main():
    try:
        password=getpass.getpass('Panel password: ')
        confirmation=getpass.getpass('Confirm panel password: ')
        if password!=confirmation: raise ValueError('Passwords do not match')
        print(password_verifier(password))
        return 0
    except (ValueError,EOFError,KeyboardInterrupt):
        print('Password verifier was not created.')
        return 1


if __name__=='__main__':
    raise SystemExit(main())
