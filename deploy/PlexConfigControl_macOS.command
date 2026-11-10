#!/bin/bash
set -eu

rule='===================================================='
if [ -t 1 ] && [ "${TERM:-dumb}" != dumb ] && [ "${NO_COLOR+x}" != x ]; then
    printf '\033[1;36m%s\n  PlexConfigControl | Setup\n%s\033[0m\n' "$rule" "$rule"
else
    printf '%s\n' "$rule" '  PlexConfigControl | Setup' "$rule"
fi
printf '\n%s\n' '  1. English' '  2. Polski'
while true; do
    read -r -p 'Choose language [1]: ' choice
    case "$choice" in
        ''|1) language=en; break ;;
        2) language=pl; break ;;
        *) printf '%s\n' 'Enter 1 for English or 2 for Polish.' ;;
    esac
done

message() {
    if [ "$language" = pl ]; then printf '%s' "$2"; else printf '%s' "$1"; fi
}

filename=$(message PlexConfigControl_Installer.py PlexConfigControl_Instalator.py)
installer="$(cd "$(dirname "$0")" && pwd)/$filename"
if [ ! -r "$installer" ]; then
    message 'Extract the entire ZIP. The .py installer must be next to this launcher.' 'Rozpakuj cały ZIP. Plik instalatora .py musi leżeć obok skrótu.' >&2
    printf '\n' >&2
    exit 1
fi
if ! command -v ssh >/dev/null || ! command -v scp >/dev/null; then
    message 'OpenSSH Client is required (ssh and scp).' 'Potrzebny jest klient OpenSSH (ssh i scp).' >&2
    printf '\n' >&2
    exit 1
fi

while true; do
    read -r -p "$(message 'TrueNAS SSH address (user@host or SSH alias): ' 'Adres SSH TrueNAS (użytkownik@host lub alias SSH): ')" destination
    if [[ $destination =~ ^([a-zA-Z_][a-zA-Z0-9_.-]*@)?[a-zA-Z0-9][a-zA-Z0-9.-]*$ ]]; then
        break
    fi
    printf '%s\n' "$(message 'Enter user@host or a valid SSH alias.' 'Wpisz użytkownik@host albo poprawny alias SSH.')"
done
options=(-o StrictHostKeyChecking=ask)
local_dir=$(mktemp -d /tmp/pcc-ssh.XXXXXXXX)
control="$local_dir/session"
remote_dir=
cleanup() {
    if [ -S "$control" ]; then
        if [ -n "$remote_dir" ]; then
            ssh "${options[@]}" -S "$control" "$destination" \
                "rm -f -- '$remote_dir/$filename' && rmdir -- '$remote_dir'" >/dev/null 2>&1 || true
        fi
        ssh -S "$control" -O exit "$destination" >/dev/null 2>&1 || true
    fi
    rm -f -- "$control"
    rmdir -- "$local_dir" || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if ! ssh "${options[@]}" -M -N -f -o ControlPersist=no -o "ControlPath=$control" "$destination"; then
    printf '%s\n' "$(message 'Could not connect. Check the address, SSH service and TrueNAS account.' 'Nie udało się połączyć. Sprawdź adres, usługę SSH i konto TrueNAS.')" >&2
    exit 1
fi
path=$(ssh "${options[@]}" -S "$control" "$destination" 'umask 077; mktemp -d /var/tmp/pcc-ssh.XXXXXXXX')
if [[ ! $path =~ ^/var/tmp/pcc-ssh\.[a-zA-Z0-9]{8}$ ]]; then
    printf '%s\n' "$(message 'TrueNAS did not return a valid temporary path.' 'TrueNAS nie zwrócił poprawnej ścieżki tymczasowej.')" >&2
    exit 1
fi
remote_dir=$path
remote_file="$remote_dir/$filename"
scp "${options[@]}" -o "ControlPath=$control" "$installer" "$destination:$remote_file"
ssh "${options[@]}" -S "$control" -tt "$destination" "sudo -- python3 '$remote_file' --desktop --ssh-connection \$SSH_CONNECTION"
