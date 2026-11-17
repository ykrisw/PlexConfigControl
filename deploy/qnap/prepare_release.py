#!/usr/bin/env python3
"""Prepare the verified QNAP source export with the shared 1.6 frontend."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import shutil
import stat
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
BUNDLE_SHA256 = "6d71dd5161101fcc8dba84c9ec6181ffa50ac2ff9e66678c18653d48a233b0e9"
FRONTEND = ("panel-app.mjs", "panel-app.css", "panel-layout.css",
            "backup-view.mjs", "restore-view.mjs", "backup-controller.mjs",
            "archive-refresh.mjs", "pcc-logo.svg")

def prepare(destination):
    destination = Path(destination).absolute()
    if destination.exists():
        raise ValueError("Build source output already exists")
    bundle = ROOT / "PCC_QNAP_Source_1.0.5.zip"
    assert hashlib.sha256(bundle.read_bytes()).hexdigest() == BUNDLE_SHA256
    with zipfile.ZipFile(bundle) as archive:
        assert len(archive.infolist()) == 122
        names = set()
        for member in archive.infolist():
            relative = PurePosixPath(member.filename)
            assert not relative.is_absolute() and ".." not in relative.parts
            assert not stat.S_ISLNK(member.external_attr >> 16)
            assert member.filename not in names
            names.add(member.filename)
            assert relative.parts[0] in {"plexconfigcontrol", "deploy", "qnap-private-tar",
                                         "LICENSE", "source-provenance.json"}
            assert member.file_size < 8 * 1024 * 1024
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(member))
    static = destination / "plexconfigcontrol/static"
    for name in FRONTEND:
        shutil.copy2(ROOT / "plexconfigcontrol/static" / name, static / name)
    web = destination / "plexconfigcontrol/web.py"
    code = web.read_text()
    anchor = "assets={'/assets/panel-client.mjs':'panel-client.mjs',"
    assert code.count(anchor)==1
    web.write_text(code.replace(anchor, anchor+"\n                '/assets/archive-refresh.mjs':'archive-refresh.mjs',"))
    # Retain QNAP's runtime integration and the approved QNAP-only button gaps.
    tools = static / "qnap-tools.mjs"
    text = tools.read_text()
    text = text.replace("info?.username||'ykrisw'", "info?.username||''")
    tools.write_text(text)
    css = (static / "qnap-tools.css").read_text()
    assert "row-gap:34px" in css and "row-gap:12px" in css
    login = (static / "panel-app.mjs").read_text()
    assert "const existing=root.querySelector('.pcc-login')" in login
    assert "input.readOnly=true" in login
    assert "const password = input.value; input.value = ''" not in login
    assert "any-pointer:coarse" in (static / "panel-layout.css").read_text()
    assert 'data-restore-progress-heading' in (static / "restore-view.mjs").read_text()
    for file in destination.rglob("*.py"):
        compile(file.read_text(), str(file), "exec")
    for file in static.glob("*.mjs"):
        subprocess.run(["node", "--check", str(file)], check=True)
    for file in (destination / "plexconfigcontrol/__init__.py", static / "settings-view.mjs"):
        text = file.read_text()
        for old in ("0.3.0", "0.1.0.dev0", "1.0.10", "1.0.5"):
            text = text.replace(old, "1.6")
        file.write_text(text)
    (destination / "qnap-private-tar/bin/pcc-tar").chmod(0o755)
    (destination / "deploy/qnap/qpkg/PCC.sh").chmod(0o755)
    # Let QDK install the official App Center icon slots, including disabled state.
    import cairosvg
    icons = destination / "deploy/qnap/qpkg/icons"
    icons.mkdir()
    for name, size in (("PCC.png",64),("PCC_gray.png",64),("PCC_80.png",80)):
        cairosvg.svg2png(url=str(static / "pcc-logo.svg"),write_to=str(icons/name),
                        output_width=size,output_height=size)
    builder = destination / "deploy/qnap/build_qpkg_preview.py"
    code = builder.read_text()
    anchor = "    (project/'shared').mkdir()"
    assert code.count(anchor)==1
    builder.write_text(code.replace(anchor, anchor+"\n    copytree(ROOT/'deploy/qnap/qpkg/icons',project/'icons')"))
    print("QNAP sources, frontend guards and JavaScript syntax: OK")
    return destination

if __name__ == "__main__":
    prepare(sys.argv[1])
