"""Qingxie backend. Read-only discovery/planning; mutations require explicit apply.

No shell commands, no autoremove, no guessed recursive deletions.
The privileged entry point re-plans under APT's system lock before committing.
"""
from __future__ import annotations

import argparse
import configparser
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


class BackendError(Exception):
    pass


@dataclasses.dataclass
class App:
    id: str
    name: str
    source: str
    version: str = ""
    size: int = 0
    icon: str = "application-x-executable"
    scope: str = "system"
    protected: bool = False
    description: str = ""

    @property
    def key(self):
        return f"{self.source}:{self.scope}:{self.id}"


CRITICAL = re.compile(
    r"^(linux-|ubuntu-(desktop|standard|minimal|session)|kubuntu-|xubuntu-|"
    r"lubuntu-|systemd|libc6|libpam|libnss|grub|shim|initramfs|"
    r"gnome-(shell|session|settings-daemon)|gdm3|sddm|lightdm|"
    r"network-manager|networkmanager|netplan|dbus|polkit|policykit|"
    r"apt$|dpkg$|sudo$|snapd$|python3($|-)|qingxie$)"
)


def run(argv, timeout=30, check=True):
    try:
        p = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, errors="replace", timeout=timeout,
                           env={**os.environ, "LC_ALL": "C", "LANG": "C"})
    except subprocess.TimeoutExpired as e:
        raise BackendError("软件管理服务响应超时，请稍后刷新。") from e
    except OSError as e:
        raise BackendError(str(e)) from e
    if check and p.returncode:
        raise BackendError(p.stderr.strip() or p.stdout.strip() or "操作失败")
    return p


def protected_package(name, essential="", priority="", protected=""):
    return bool(essential == "yes" or protected == "yes" or
                priority in ("required", "important") or
                CRITICAL.match(name.split(":")[0]))


def desktop_meta(path):
    c = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        c.read(path, encoding="utf-8")
        d = c["Desktop Entry"]
        if d.get("Type") != "Application" or d.get("NoDisplay") == "true" or d.get("Hidden") == "true":
            return None
        return (d.get("Name[zh_CN]", d.get("Name", Path(path).stem)),
                d.get("Icon", "application-x-executable"),
                d.get("Comment[zh_CN]", d.get("Comment", "")))
    except (OSError, ValueError, configparser.Error, KeyError):
        return None


def list_apt(all_packages=False):
    fmt = "${binary:Package}\t${db:Status-Abbrev}\t${Installed-Size}\t${Version}\t${Essential}\t${Priority}\t${Protected}\n"
    rows = run(["/usr/bin/dpkg-query", "-W", "-f=" + fmt]).stdout
    packages = {}
    for line in rows.splitlines():
        cols = line.split("\t")
        if len(cols) != 7 or not cols[1].startswith("ii"):
            continue
        name, _, size, version, essential, priority, protected = cols
        packages[name] = App(name, name, "APT", version, int(size or 0) * 1024,
                             protected=protected_package(name, essential, priority, protected))
    files = sorted(Path("/usr/share/applications").glob("*.desktop"))
    owners = {}
    if files:
        result = run(["/usr/bin/dpkg-query", "-S", *map(str, files)], check=False)
        for line in result.stdout.splitlines():
            if ": /" in line:
                owner, path = line.split(": ", 1)
                owners[path] = owner.split(", ")[0]
    visible = set()
    for f in files:
        name = owners.get(str(f))
        if name not in packages:
            continue
        meta = desktop_meta(f)
        if meta:
            visible.add(name)
            app = packages[name]
            if app.name == app.id:
                app.name, app.icon, app.description = meta
    return list(packages.values()) if all_packages else [packages[n] for n in visible]


def list_snap():
    if not Path("/usr/bin/snap").exists():
        return []
    p = run(["/usr/bin/snap", "list"], timeout=12, check=False)
    if p.returncode:
        if "No snaps are installed" in p.stderr:
            return []
        raise BackendError(p.stderr.strip() or "Snap 服务不可用")
    result = []
    for line in p.stdout.splitlines()[1:]:
        cols = line.split()
        if len(cols) < 6:
            continue
        name, version, revision = cols[:3]
        notes = cols[-1]
        protected = name in ("snapd", "bare") or name.startswith("core") or any(
            x in notes.split(",") for x in ("base", "kernel", "gadget", "snapd"))
        size = 0
        try:
            size = Path(f"/var/lib/snapd/snaps/{name}_{revision}.snap").stat().st_size
        except OSError:
            pass
        app = App(name, name, "Snap", f"{version} · rev {revision}", size, protected=protected)
        for f in sorted(Path("/var/lib/snapd/desktop/applications").glob(name + "_*.desktop")):
            meta = desktop_meta(f)
            if meta:
                app.name, app.icon, app.description = meta
                break
        result.append(app)
    return result


def size_bytes(text):
    m = re.match(r"([\d.]+)\s*([kMGT]?i?B)?", text.strip(), re.I)
    if not m:
        return 0
    unit = (m[2] or "B").upper()
    exp = {"B": 0, "KB": 1, "MB": 2, "GB": 3, "TB": 4,
           "KIB": 1, "MIB": 2, "GIB": 3, "TIB": 4}.get(unit, 0)
    return int(float(m[1]) * (1024 if "I" in unit else 1000) ** exp)


def list_flatpak():
    if not Path("/usr/bin/flatpak").exists():
        return []
    apps = []
    for scope in ("user", "system"):
        p = run(["/usr/bin/flatpak", "list", "--" + scope, "--app",
                 "--columns=ref,name,version,size"])
        for line in p.stdout.splitlines():
            cols = line.split("\t")
            if len(cols) < 4:
                continue
            ref, name, version, size = cols[:4]
            if not ref.startswith("app/"):
                ref = "app/" + ref
            app_id = ref.split("/")[1]
            base = (Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "flatpak"
                    if scope == "user" else Path("/var/lib/flatpak"))
            meta = desktop_meta(base / "exports/share/applications" / (app_id + ".desktop"))
            apps.append(App(ref, name, "Flatpak", version, size_bytes(size),
                            icon=meta[1] if meta else app_id, scope=scope))
    return apps


def discover(all_packages=False):
    apps, errors = [], []
    for label, fn in [("APT", lambda: list_apt(all_packages)), ("Snap", list_snap), ("Flatpak", list_flatpak)]:
        try:
            apps.extend(fn())
        except Exception as e:
            errors.append(label + "：" + str(e))
    return sorted(apps, key=lambda a: a.name.casefold()), errors


def validate_id(source, ident, scope="system"):
    patterns = {
        "APT": r"[a-z0-9][a-z0-9+.-]*(?::[a-z0-9-]+)?",
        "Snap": r"[a-z0-9][a-z0-9-]*(?:_[a-z0-9]+)?",
        "Flatpak": r"app/[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+){2,}/[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+",
    }
    if source not in patterns or not re.fullmatch(patterns[source], ident) or scope not in ("user", "system"):
        raise BackendError("无效的软件标识；已停止操作。")


def apt_plan(ident, purge=False, cache=None):
    import apt
    validate_id("APT", ident)
    cache = cache if cache is not None else apt.Cache()
    if cache.broken_count:
        raise BackendError("系统存在未解决的依赖问题，请先用系统软件管理器修复。")
    if ident not in cache or not cache[ident].is_installed:
        raise BackendError("这个软件已不在已安装列表中，请刷新。")
    cache[ident].mark_delete(auto_fix=True, purge=purge)
    if cache.broken_count:
        raise BackendError("卸载会破坏依赖关系，已停止。")
    changed = cache.get_changes()
    removed = []
    for p in changed:
        if not p.marked_delete or not p.installed:
            raise BackendError("此操作需要安装或修改其他软件，当前版本不执行此类事务。")
        record = p.installed.record
        if protected_package(p.name, "yes" if p.essential else "", p.installed.priority, record.get("Protected", "")):
            raise BackendError("卸载将影响受保护的系统组件：" + p.name)
        if p._pkg.selected_state == 2:  # apt_pkg.SELSTATE_HOLD
            raise BackendError("软件包已被锁定版本：" + p.name)
        removed.append({"id": p.fullname, "version": p.installed.version,
                        "size": p.installed.installed_size})
    if not removed:
        raise BackendError("未生成卸载计划。")
    return sorted(removed, key=lambda row: row["id"])


def plan(app, purge=False, delete_data=False):
    validate_id(app.source, app.id, app.scope)
    if app.protected:
        raise BackendError("这个组件已受保护，不能在这里卸载。")
    if purge and app.source != "APT" or delete_data and app.source != "Flatpak":
        raise BackendError("当前来源不支持这个清理选项。")
    notes = []
    if app.source == "APT":
        removed = apt_plan(app.id, purge)
        notes = ["不自动清理共享依赖。", "保留用户目录中的个人配置、缓存和文件。"]
        if purge:
            notes.append("同时清除上述软件包由包管理器管理的系统配置；不删除个人配置。")
    else:
        current = next((x for x in (list_snap() if app.source == "Snap" else list_flatpak()) if x.key == app.key), None)
        if not current or current.protected:
            raise BackendError("软件状态已变化，请刷新列表。")
        removed = [{"id": app.id, "version": current.version, "size": current.size}]
        if app.source == "Snap":
            notes = ["卸载前创建数据快照；快照创建失败则停止卸载。",
                     "快照保留在本机，可通过 Snap 恢复；这不等于保留原数据目录。",
                     "Snap 自身会检查依赖，使用中的基础组件不会强制移除。"]
        else:
            notes = ["仅移除此安装范围内的应用；保留运行时和关联扩展。",
                     "共享文件会影响实际释放空间，大小仅供参考。"]
            if delete_data:
                same_id = [x for x in list_flatpak() if x.id.split("/")[1] == app.id.split("/")[1]]
                if len(same_id) > 1:
                    raise BackendError("同一应用还有其他安装或分支，共享用户数据，不能一并清理。")
                notes.append("删除当前用户的全部应用数据（可能包含存档、账号和设置）：~/.var/app/" + app.id.split("/")[1])
            else:
                notes.append("保留当前用户的全部应用数据。")
    payload = {"source": app.source, "id": app.id, "scope": app.scope,
               "purge": bool(purge), "delete_data": bool(delete_data), "removed": removed}
    return {**payload, "notes": notes, "name": app.name,
            "fingerprint": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()}


def flatpak_command(p):
    validate_id("Flatpak", p["id"], p["scope"])
    cmd = ["/usr/bin/flatpak", "uninstall", "--" + p["scope"], "--app", "--no-related", "--assumeyes", "--noninteractive"]
    if p["delete_data"]:
        cmd.append("--delete-data")
    return cmd + [p["id"]]


def apply_command(p):
    validate_id(p["source"], p["id"], p["scope"])
    if p["source"] == "Flatpak":
        return flatpak_command(p)
    if not Path("/usr/bin/pkexec").exists():
        raise BackendError("缺少系统授权工具 pkexec，请安装 policykit-1 / polkitd-pkexec。")
    return ["/usr/bin/pkexec", "/usr/bin/python3", "-I", str(Path(__file__).resolve()),
            "--apply", json.dumps(p, ensure_ascii=False)]


def revalidate(p):
    a = App(p["id"], p["name"], p["source"], scope=p["scope"])
    fresh = plan(a, p["purge"], p["delete_data"])
    if fresh["fingerprint"] != p["fingerprint"]:
        raise BackendError("卸载范围或软件版本已经变化，请重新预览并确认。")


def privileged_apply(p):
    if os.geteuid() != 0:
        raise BackendError("需要通过系统授权窗口执行。")
    validate_id(p["source"], p["id"], p["scope"])
    os.environ.update(LC_ALL="C", LANG="C", DEBIAN_FRONTEND="noninteractive",
                      PATH="/usr/sbin:/usr/bin:/sbin:/bin")
    if p["source"] == "APT":
        import apt
        import apt_pkg
        import apt.progress.base
        apt_pkg.init_config()
        apt_pkg.init_system()
        with apt_pkg.SystemLock():
            cache = apt.Cache()
            removed = apt_plan(p["id"], p["purge"], cache)
            if removed != p["removed"]:
                raise BackendError("卸载计划已改变，请重新预览。")
            print("卸载范围复核通过，正在执行…", flush=True)
            if not cache.commit(install_progress=apt.progress.base.InstallProgress()):
                raise BackendError("软件管理器未完成操作，请查看日志。")
    elif p["source"] == "Snap":
        revalidate(p)
        # Explicit save works even when automatic snapshots have been disabled.
        for cmd in (["/usr/bin/snap", "save", p["id"]],
                    ["/usr/bin/snap", "remove", "--purge", p["id"]]):
            print("执行：" + " ".join(cmd), flush=True)
            rc = subprocess.call(cmd, stdin=subprocess.DEVNULL)
            if rc:
                raise BackendError("Snap 操作失败；已停止后续操作，详见日志。")
    else:
        raise BackendError("这个来源不使用管理员辅助程序。")
    print("操作完成。", flush=True)


def friendly_error(message):
    text = message.lower()
    if "lock" in text or "another operation" in text:
        return "另一个软件管理器正在运行，请等它完成后重试。"
    if "not authorized" in text or "authentication" in text or "dismissed" in text:
        return "系统授权未完成，卸载未获授权。"
    if "in use" in text or "running" in text:
        return "软件或组件正在使用中，请关闭相关程序后重试。"
    return message


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    try:
        if args.apply:
            privileged_apply(json.loads(args.apply))
        elif args.list:
            apps, errors = discover()
            print(json.dumps({"apps": [dataclasses.asdict(a) for a in apps], "warnings": errors}, ensure_ascii=False, indent=2))
    except Exception as e:
        print(friendly_error(str(e)), file=sys.stderr)
        sys.exit(1)
