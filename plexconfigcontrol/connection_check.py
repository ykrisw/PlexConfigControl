"""Read-only connectivity probe; credentials are loaded locally, never printed."""
import argparse
import json
import os
import stat
from pathlib import Path
from .transport import build_client


def read_secret(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'r',encoding='utf-8') as file:
        info=os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size>16384:
            raise ValueError('Invalid secret file')
        if info.st_mode & 0o077:
            raise ValueError('Secret file must not be accessible by group or others')
        value=file.read().strip()
        if not value: raise ValueError('Empty API key file')
        return value


def probe(client):
    rows=client.call('app.query',[['name','=','plex']],{'select':['name','state','version']})
    if not isinstance(rows,list) or len(rows)!=1 or rows[0].get('name')!='plex':
        raise ValueError('Plex app not found')
    row=rows[0]
    return {'connected':True,'app':row['name'],'state':row.get('state','UNKNOWN'),
            'version':row.get('version')}


def main(argv=None):
    parser=argparse.ArgumentParser(description='Read-only TrueNAS/Plex connectivity check')
    parser.add_argument('--url',required=True,help='Verified wss://host/api/current endpoint')
    parser.add_argument('--username',required=True)
    parser.add_argument('--key-file',required=True,help='Private local API key file')
    parser.add_argument('--ca-file',help='Trusted TrueNAS certificate/CA file')
    args=parser.parse_args(argv)
    try:
        client=build_client(args.url,args.username,read_secret(args.key_file),args.ca_file)
        result=probe(client)
        print(json.dumps(result))
        return 0
    except Exception:
        print(json.dumps({'connected':False,'error':'Connection check failed. Verify endpoint, credentials, permissions and certificate.'}))
        return 1

if __name__=='__main__':
    raise SystemExit(main())
