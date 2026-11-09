#!/bin/sh
# Runs inside the official Plex image, with only the isolated cache mounted.
set -eu
umask 022

check_version() {
    output=$(LD_LIBRARY_PATH="$1/lib" "$1/Plex SQLite" -version)
    [ "${output%% *}" = "$PCC_SQLITE_VERSION" ] || {
        printf '%s\n' 'PlexConfigControl: unexpected Plex SQLite version.' >&2
        return 1
    }
}

if [ -e /runtime/files ] || [ -L /runtime/files ]; then
    if [ ! -d /runtime/files ] || [ -L /runtime/files ]; then
        printf '%s\n' 'PlexConfigControl: invalid Plex SQLite cache directory.' >&2
        exit 1
    fi
    check_version /runtime/files
    exit 0
fi

stage=$(mktemp -d /runtime/.sqlite-XXXXXXXX)
trap 'rm -rf -- "$stage"' EXIT
# Plex SQLite launches its sibling Plex Media Server executable.
cp '/usr/lib/plexmediaserver/Plex SQLite' '/usr/lib/plexmediaserver/Plex Media Server' "$stage/"
cp -R /usr/lib/plexmediaserver/lib "$stage/lib"
chmod -R a+rX "$stage"
check_version "$stage"
mv -T -- "$stage" /runtime/files
