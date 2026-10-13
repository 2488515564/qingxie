#!/usr/bin/python3
"""Build explicit release artifacts without including local files or Git metadata."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tarfile

root = Path(__file__).resolve().parent
dist = root / "dist"
dist.mkdir(exist_ok=True)
subprocess.run([sys.executable, str(root / "build_deb.py")], check=True)
archive = dist / "qingxie-0.1.4-portable.tar.gz"
files = ["main.py", "backend.py", "desktop_integration.py", "README.md", "CHANGELOG.md",
         "build_deb.py", "build_release.py", "启动轻卸.sh", ".gitignore"]
files += [str(p.relative_to(root)) for folder in ("assets", "tests")
          for p in sorted((root / folder).rglob("*"))
          if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"]
with tarfile.open(archive, "w:gz") as tar:
    for name in files:
        tar.add(root / name, arcname="qingxie/" + name)
artifacts = [dist / "qingxie_0.1.4_all.deb", archive]
(dist / "SHA256SUMS").write_text("".join(
    hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name + "\n" for p in artifacts))
print("Release files:")
for p in artifacts + [dist / "SHA256SUMS"]:
    print(p)
