#!/bin/bash
set -eu

installer="$(cd "$(dirname "$0")" && pwd)/PlexConfigControl_Instalator.py"
if [ ! -r "$installer" ]; then
    printf '%s\n' 'Rozpakuj cały ZIP. Plik instalatora .py musi leżeć obok tego skrótu.' >&2
    exit 1
fi
if ! command -v ssh >/dev/null || ! command -v scp >/dev/null; then
    printf '%s\n' 'Brakuje klienta OpenSSH. Potrzebne są polecenia ssh i scp.' >&2
    exit 1
fi

read -r -p 'Adres IPv4 lub nazwa TrueNAS: ' host
read -r -p 'Użytkownik SSH TrueNAS z dostępem do sudo: ' user
if [[ ! $host =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*$ || ! $user =~ ^[a-zA-Z_][a-zA-Z0-9_.-]*$ ]]; then
    printf '%s\n' 'Podaj poprawny adres i nazwę użytkownika.' >&2
    exit 1
fi
destination="$user@$host"
local_dir=$(mktemp -d /tmp/pcc-ssh.XXXXXXXX)
control="$local_dir/session"
cleanup() {
    if [ -S "$control" ]; then
        ssh -S "$control" -O exit "$destination" >/dev/null 2>&1 || true
    fi
    rm -f -- "$control"
    rmdir -- "$local_dir" || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# SSH prompts for authentication and verifies the host key itself.
ssh -M -N -f -o StrictHostKeyChecking=ask -o ControlPersist=no -o "ControlPath=$control" "$destination"
remote_dir=$(ssh -S "$control" "$destination" 'umask 077; mktemp -d /var/tmp/pcc-mac.XXXXXXXX')
if [[ ! $remote_dir =~ ^/var/tmp/pcc-mac\.[a-zA-Z0-9]{8}$ ]]; then
    printf '%s\n' 'TrueNAS nie zwrócił poprawnej ścieżki tymczasowej.' >&2
    exit 1
fi
remote_file="$remote_dir/PlexConfigControl_Instalator.py"
scp -o "ControlPath=$control" "$installer" "$destination:$remote_file"

if ssh -S "$control" -tt "$destination" "sudo python3 '$remote_file'"; then
    ssh -S "$control" "$destination" "rm -f -- '$remote_file' && rmdir -- '$remote_dir'" ||
        printf '%s\n' "Plik instalatora pozostał na TrueNAS w $remote_dir."
else
    status=$?
    printf '%s\n' "Kreator przerwał pracę. Plik do ewentualnego wznowienia jest na TrueNAS w $remote_dir."
    exit "$status"
fi
