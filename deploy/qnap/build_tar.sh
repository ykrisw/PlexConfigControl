#!/bin/sh
# Build on Linux x86_64, never on the NAS. Output includes corresponding sources.
set -eu

if [ "$#" -ne 1 ]; then
    echo 'Usage: sh deploy/qnap/build_tar.sh NEW_OUTPUT_DIRECTORY' >&2
    exit 2
fi
PCC_TAR_OUTPUT=$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$1")
if [ -e "$PCC_TAR_OUTPUT" ] || [ -L "$PCC_TAR_OUTPUT" ]; then
    echo 'Output already exists; refusing to replace it.' >&2
    exit 1
fi
if [ "$(uname -s)" != Linux ] || [ "$(uname -m)" != x86_64 ]; then
    echo 'Build host must be Linux x86_64.' >&2
    exit 1
fi
PCC_TAR_BUILD=$(mktemp -d /var/tmp/pcc-tar-build.XXXXXXXX)
trap 'rm -rf -- "$PCC_TAR_BUILD"' EXIT HUP INT TERM
PCC_TAR_PREFIX="$PCC_TAR_BUILD/prefix"
mkdir -p "$PCC_TAR_BUILD/sources"

fetch_source() {
    pcc_source_url=$1
    pcc_source_hash=$2
    pcc_source_name=${pcc_source_url##*/}
    curl --fail --location --proto '=https' --proto-redir '=https' \
        --retry 2 --output "$PCC_TAR_BUILD/sources/$pcc_source_name" "$pcc_source_url"
    printf '%s  %s\n' "$pcc_source_hash" "$PCC_TAR_BUILD/sources/$pcc_source_name" | sha256sum -c -
    python3 - "$PCC_TAR_BUILD/sources/$pcc_source_name" "$PCC_TAR_BUILD" <<'PY'
import sys
import tarfile
with tarfile.open(sys.argv[1]) as archive:
    archive.extractall(sys.argv[2], filter='data')
PY
}

fetch_source https://download.savannah.gnu.org/releases/attr/attr-2.5.2.tar.xz \
    f2e97b0ab7ce293681ab701915766190d607a1dba7fae8a718138150b700a70b
fetch_source https://download.savannah.gnu.org/releases/acl/acl-2.3.2.tar.xz \
    97203a72cae99ab89a067fe2210c1cbf052bc492b479eca7d226d9830883b0bd
fetch_source https://ftp.gnu.org/gnu/tar/tar-1.35.tar.xz \
    4d62ff37342ec7aed748535323930c7cf94acf71c3591882b26a7ea50f3edc16

export CFLAGS='-O2 -fstack-protector-strong -D_FORTIFY_SOURCE=2'
export CPPFLAGS="-I$PCC_TAR_PREFIX/include"
export LDFLAGS="-L$PCC_TAR_PREFIX/lib"
export PKG_CONFIG_PATH="$PCC_TAR_PREFIX/lib/pkgconfig"
export FORCE_UNSAFE_CONFIGURE=1
for pcc_library in attr-2.5.2 acl-2.3.2; do
    (
        cd "$PCC_TAR_BUILD/$pcc_library"
        ./configure --prefix="$PCC_TAR_PREFIX" --disable-shared --enable-static --disable-nls
        make -j2
        make install
    )
done
(
    cd "$PCC_TAR_BUILD/tar-1.35"
    ./configure --prefix="$PCC_TAR_PREFIX" --disable-nls --without-selinux \
        --with-posix-acls --with-xattrs
    make -j2
)

# Inspect the built ELF, rather than assuming host libc version equals the
# minimum ABI used by this program. Do not ship a private libc or replace NAS tools.
python3 - "$PCC_TAR_BUILD/tar-1.35/src/tar" <<'PY'
import re
import subprocess
import sys
binary = sys.argv[1]
versions = subprocess.check_output(['readelf', '--version-info', binary], text=True)
required = {tuple(map(int, value.split('.'))) for value in re.findall(r'GLIBC_(\d+(?:\.\d+)+)', versions)}
if not required or max(required) > (2, 39):
    raise SystemExit('Built tar exceeds the QNAP development target glibc ABI')
dynamic = subprocess.check_output(['readelf', '--dynamic', binary], text=True)
libraries = re.findall(r'\(NEEDED\).*?\[(.*?)\]', dynamic)
allowed = {'libc.so.6', 'libm.so.6', 'libpthread.so.0', 'librt.so.1', 'libdl.so.2'}
if not libraries or set(libraries) - allowed:
    raise SystemExit('Unexpected external tar dependencies: '+repr(libraries))
help_text = subprocess.check_output([binary, '--help'], text=True)
for option in ('--acls', '--xattrs', '--numeric-owner', '--format', '--transform'):
    if option not in help_text:
        raise SystemExit('Required tar feature is missing: '+option)
print('Built tar ABI and feature checks passed; glibc requirement:', max(required))
PY

mkdir -p "$PCC_TAR_OUTPUT/bin" "$PCC_TAR_OUTPUT/licenses" "$PCC_TAR_OUTPUT/sources"
install -m 755 "$PCC_TAR_BUILD/tar-1.35/src/tar" "$PCC_TAR_OUTPUT/bin/pcc-tar"
cp "$PCC_TAR_BUILD/tar-1.35/COPYING" "$PCC_TAR_OUTPUT/licenses/GNU-tar-GPL-3.0.txt"
for pcc_library in attr-2.5.2 acl-2.3.2; do
    for pcc_license in "$PCC_TAR_BUILD/$pcc_library"/doc/COPYING* "$PCC_TAR_BUILD/$pcc_library"/COPYING*; do
        if [ -f "$pcc_license" ]; then
            cp "$pcc_license" "$PCC_TAR_OUTPUT/licenses/$pcc_library-${pcc_license##*/}"
        fi
    done
done
cp "$PCC_TAR_BUILD/sources/"*.tar.xz "$PCC_TAR_OUTPUT/sources/"
cp "$0" "$PCC_TAR_OUTPUT/sources/build_tar.sh"
python3 - "$PCC_TAR_OUTPUT" <<'PY'
import hashlib
import json
import sys
from pathlib import Path
root = Path(sys.argv[1])
manifest = {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file()}
(root/'SHA256-MANIFEST.json').write_text(json.dumps(manifest, sort_keys=True, indent=2)+'\n')
PY
echo "QNAP private tar payload prepared: $PCC_TAR_OUTPUT"
