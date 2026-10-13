"""Per-user desktop association for portable launches; no system installation."""
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parent
PORTABLE = ROOT != Path("/usr/share/qingxie")
APP_ID = "qingxie-portable" if PORTABLE else "qingxie"


def field(value):
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r")


def exec_arg(value):
    value = str(value).replace("%", "%%")
    for char in ("\\", '"', '`', '$'):
        value = value.replace(char, "\\" + char)
    return field('"' + value + '"')


def register_portable(root=ROOT, data_home=None):
    root = Path(root).resolve()
    if not (root / "main.py").is_file() or not (root / "assets/qingxie.png").is_file():
        raise OSError("轻卸程序或图标文件缺失，请完整解压免安装包。")
    data_home = Path(data_home or os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    if not data_home.is_absolute():
        raise OSError("XDG_DATA_HOME 必须是绝对路径。")
    dest = data_home / "applications/qingxie-portable.desktop"
    content = "\n".join([
        "[Desktop Entry]", "Type=Application", "Name=轻卸（免安装版）",
        "Comment=软件卸载，清楚简单", "Terminal=false", "StartupNotify=true",
        "StartupWMClass=qingxie-portable", "Categories=System;PackageManager;",
        "X-Qingxie-Portable=true",
        "Exec=/usr/bin/python3 " + exec_arg(root / "main.py"),
        "Icon=" + field(root / "assets/qingxie.png"), "",
    ])
    if dest.exists():
        old = dest.read_text()
        if "X-Qingxie-Portable=true" not in old.splitlines():
            raise OSError("存在同名非轻卸生成的桌面入口，未覆盖。")
        if old == content:
            return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".qingxie-", dir=dest.parent)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.chmod(temporary, 0o644)
        os.replace(temporary, dest)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return dest


if __name__ == "__main__":
    print(register_portable())
