#!/bin/sh
# Production installer entry point. No deployment occurs before explicit confirmation.
set -eu
if [ "$#" -ne 1 ]; then
    printf 'Użycie: sudo sh deploy/install.sh /ścieżka/do/ustawienia.json\n' >&2
    exit 2
fi
case "$1" in
    /*) config=$1 ;;
    *) config=$PWD/$1 ;;
esac
[ "$(id -u)" -eq 0 ] || { printf 'Uruchom instalator jako administrator TrueNAS.\n' >&2; exit 1; }
cd "$(dirname "$0")/.."
[ -r "$config" ] || { printf 'Nie można odczytać pliku ustawień.\n' >&2; exit 1; }
panel=plexconfigcontrol:0.1.0
runtime=$(python3 -m plexconfigcontrol.plex_runtime)
IFS=' ' read -r plex sqlite _ <<EOF
$runtime
EOF
worker=plexconfigcontrol-worker:0.1.0-plex-${plex##*@sha256:}
printf 'Wykryto Plex SQLite %s w obrazie %s\n' "$sqlite" "$plex"
docker build --tag "$panel" .
docker build --file Dockerfile.worker --tag "$worker" \
    --build-arg "PCC_PANEL_IMAGE=$panel" --build-arg "PLEX_IMAGE=$plex" .
docker run --rm --network none --read-only --tmpfs /tmp \
    --security-opt no-new-privileges:true --cap-drop ALL \
    --cap-add SETUID --cap-add SETGID --cap-add SETPCAP \
    --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER --cap-add FSETID \
    "$worker" --check-runtime --panel-uid 568 --plex-sqlite /usr/local/bin/pcc-plex-sqlite \
    --sqlite-version "$sqlite"
exec python3 -m plexconfigcontrol.host_install "$config" \
    --panel-image "$panel" --worker-image "$worker" --sqlite-version "$sqlite" \
    --plex-runtime "$runtime" --install
