#!/usr/bin/python3
"""Build a .deb without root; no install scripts and no system modifications."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf

source = Path(__file__).resolve().parent
target = source / "dist/qingxie_0.1.6_all.deb"
target.parent.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix="qingxie-build-") as tmp:
    root = Path(tmp)
    app = root / "usr/share/qingxie"
    app.mkdir(parents=True)
    for filename in ("main.py", "backend.py", "desktop_integration.py", "README.md"):
        shutil.copy2(source / filename, app / filename)
        (app / filename).chmod(0o644)
    shutil.copytree(source / "assets", app / "assets")
    for size in (16, 24, 32, 48, 64, 128, 256, 512):
        icon = root / f"usr/share/icons/hicolor/{size}x{size}/apps/qingxie.png"
        icon.parent.mkdir(parents=True)
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(source / "assets/qingxie.png"), size, size, True)
        pixbuf.savev(str(icon), "png", [], [])
    binary = root / "usr/bin/qingxie"
    binary.parent.mkdir(parents=True)
    binary.write_text('#!/bin/sh\nexec /usr/bin/python3 /usr/share/qingxie/main.py "$@"\n')
    binary.chmod(0o755)
    desktop = root / "usr/share/applications/qingxie.desktop"
    desktop.parent.mkdir(parents=True)
    desktop.write_text('''[Desktop Entry]
Type=Application
Name=轻卸
Name[en]=Qingxie
Comment=软件卸载，清楚简单
Exec=qingxie
Icon=qingxie
StartupWMClass=qingxie
Terminal=false
Categories=System;PackageManager;
Keywords=uninstall;software;remove;卸载;软件;
StartupNotify=true
''')
    control = root / "DEBIAN/control"
    control.parent.mkdir()
    control.write_text('''Package: qingxie
Version: 0.1.6
Section: admin
Priority: optional
Architecture: all
Maintainer: Qingxie Local Build <noreply@localhost>
Depends: python3 (>= 3.10), python3-gi, python3-apt, gir1.2-gtk-3.0, pkexec
Description: Native Ubuntu software uninstaller
 Browse APT, Snap and Flatpak applications with removal previews,
 system-component protection and fixed-size application icons.
''')
    for directory, dirs, files in os.walk(root):
        Path(directory).chmod(0o755)
        for f in files:
            if Path(directory, f) != binary:
                Path(directory, f).chmod(0o644)
    subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(root), str(target)], check=True)
print(target)
