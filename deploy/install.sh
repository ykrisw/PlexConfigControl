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
[ "$(midclt call app.query '[["name","=","plexconfigcontrol"]]' '{"select":["name"]}')" = '[]' ] || {
    printf '%s\n' 'Aplikacja plexconfigcontrol już istnieje lub nie udało się odczytać jej stanu.' >&2
    exit 1
}
panel=plexconfigcontrol:0.1.0
runtime=$(python3 -m plexconfigcontrol.plex_runtime)
IFS=' ' read -r plex sqlite _ <<EOF
$runtime
EOF
worker=plexconfigcontrol-worker:0.1.0-base
initializer=$PWD/design/truenas-installation/initialize-plex-sqlite.sh
printf 'Wykryto Plex SQLite %s w obrazie %s\n' "$sqlite" "$plex"
docker build --tag "$panel" .
docker build --file Dockerfile.worker --target worker-base --tag "$worker" \
    --build-arg "PCC_PANEL_IMAGE=$panel" .
cache=$(docker volume create)
trap 'docker volume rm "$cache" >/dev/null 2>&1 || true' EXIT
docker run --rm --network none --read-only --user 0:0 --cap-drop ALL \
    --security-opt no-new-privileges:true --env "PCC_SQLITE_VERSION=$sqlite" \
    --tmpfs /config:ro --tmpfs /transcode:ro --mount "source=$cache,target=/runtime" \
    --mount "type=bind,source=$initializer,target=/pcc-init.sh,readonly" \
    --entrypoint /bin/sh "$plex" /pcc-init.sh
docker run --rm --network none --read-only --tmpfs /tmp \
    --security-opt no-new-privileges:true --cap-drop ALL \
    --cap-add SETUID --cap-add SETGID --cap-add SETPCAP \
    --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER --cap-add FSETID \
    --mount "source=$cache,target=/opt/pcc-plex,readonly" \
    --env PCC_PLEX_RUNTIME=/opt/pcc-plex/files \
    "$worker" --check-runtime --panel-uid 568 --plex-sqlite /usr/local/bin/pcc-plex-sqlite \
    --sqlite-version "$sqlite"
docker volume rm "$cache" >/dev/null
trap - EXIT
exec python3 -m plexconfigcontrol.host_install "$config" \
    --panel-image "$panel" --worker-image "$worker" --sqlite-version "$sqlite" \
    --plex-runtime "$runtime" --install
