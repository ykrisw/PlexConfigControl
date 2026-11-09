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
worker=plexconfigcontrol-worker:0.1.0
plex=plexinc/pms-docker@sha256:531ad94c469748dcaa9d6f3d6c6160ad3598617a55319d389e7d08216bc680a7
sqlite=3.53.3

containers=$(docker ps --filter 'label=com.docker.compose.project=ix-plex' \
    --filter 'label=com.docker.compose.service=plex' --format '{{.ID}}')
[ "$(printf '%s\n' "$containers" | awk 'NF { n++ } END { print n+0 }')" -eq 1 ] || {
    printf 'Uruchom Plex przed instalacją PlexConfigControl.\n' >&2
    exit 1
}
installed_image=$(docker inspect --type container --format '{{.Image}}' "$containers")
installed_digests=$(docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$installed_image")
printf '%s\n' "$installed_digests" | awk -v expected="$plex" '
    $0 == expected { matched=1 }
    END { exit !matched }
' || {
    printf 'Obraz Plex nie odpowiada wersji obsługiwanej przez tę paczkę.\n' >&2
    exit 1
}
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
    --panel-image "$panel" --worker-image "$worker" --sqlite-version "$sqlite" --install
