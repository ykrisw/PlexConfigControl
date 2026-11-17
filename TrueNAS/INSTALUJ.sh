#!/bin/sh
set -eu
[ "$(id -u)" -eq 0 ] || { printf '%s\n' 'Uruchom: sudo sh INSTALUJ.sh' >&2; exit 1; }
cd "$(dirname "$0")"
exec python3 -m deploy.install_pl "$@"
