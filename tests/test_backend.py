import dataclasses
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backend as b


class Package:
    def __init__(self, name="vlc", essential=False, priority="optional", protected="no", delete=True):
        self.name = name
        self.fullname = name + ":amd64"
        self.essential = essential
        self.marked_delete = delete
        self.is_installed = True
        self.installed = SimpleNamespace(priority=priority, record={"Protected": protected}, version="1", installed_size=1024)
        self._pkg = SimpleNamespace(selected_state=1)

    def mark_delete(self, **kwargs):
        self.options = kwargs


class Cache(dict):
    broken_count = 0

    def get_changes(self):
        return list(self.values())


class BackendTests(unittest.TestCase):
    def test_rejects_option_and_shell_injection(self):
        for source, ident in [("APT", "--allow-remove-essential"), ("APT", "vlc;touch /tmp/x"),
                              ("APT", "vlc*"), ("Snap", "../snapd"), ("Flatpak", "--all"),
                              ("Flatpak", "runtime/org.gnome.Platform/x86_64/47")]:
            with self.subTest(ident=ident), self.assertRaises(b.BackendError):
                b.validate_id(source, ident)

    def test_valid_multiarch_and_full_ref(self):
        b.validate_id("APT", "libx11-6:amd64")
        b.validate_id("Flatpak", "app/org.gnome.Calculator/x86_64/stable", "user")

    def test_apt_includes_all_removals_and_versions(self):
        c = Cache(vlc=Package(), addon=Package("addon"))
        result = b.apt_plan("vlc", True, c)
        self.assertEqual([x["id"] for x in result], ["addon:amd64", "vlc:amd64"])
        self.assertTrue(c["vlc"].options["purge"])

    def test_apt_blocks_protected_dependencies(self):
        for pkg in (Package("dep", essential=True), Package("dep", protected="yes"),
                    Package("dep", priority="important"), Package("gnome-shell")):
            with self.subTest(pkg=pkg.name), self.assertRaises(b.BackendError):
                b.apt_plan("vlc", cache=Cache(vlc=Package(), dep=pkg))

    def test_apt_blocks_installs_and_holds(self):
        with self.assertRaises(b.BackendError):
            b.apt_plan("vlc", cache=Cache(vlc=Package(), dep=Package(delete=False)))
        p = Package()
        p._pkg.selected_state = 2
        with self.assertRaises(b.BackendError):
            b.apt_plan("vlc", cache=Cache(vlc=p))

    def test_apt_blocks_broken_or_missing(self):
        c = Cache(vlc=Package())
        c.broken_count = 1
        with self.assertRaises(b.BackendError):
            b.apt_plan("vlc", cache=c)
        with self.assertRaises(b.BackendError):
            b.apt_plan("missing", cache=Cache())

    def test_flatpak_exact_scope_and_ref_preserves_data(self):
        p = {"id": "app/org.gnome.Calculator/x86_64/stable", "scope": "user", "delete_data": False}
        cmd = b.flatpak_command(p)
        self.assertIn("--user", cmd)
        self.assertIn("--no-related", cmd)
        self.assertNotIn("--delete-data", cmd)
        self.assertEqual(cmd[-1], p["id"])

    def test_flatpak_shared_user_data_is_protected(self):
        a = b.App("app/org.gnome.Calculator/x86_64/stable", "Calc", "Flatpak", scope="user")
        other = dataclasses.replace(a, scope="system")
        with patch.object(b, "list_flatpak", return_value=[a, other]), self.assertRaises(b.BackendError):
            b.plan(a, delete_data=True)

    def test_revalidation_detects_version_change(self):
        old = {"id": "vlc", "name": "VLC", "source": "APT", "scope": "system", "purge": False,
               "delete_data": False, "fingerprint": "old"}
        with patch.object(b, "plan", return_value={"fingerprint": "new"}), self.assertRaises(b.BackendError):
            b.revalidate(old)

    def test_snapshot_failure_prevents_snap_removal(self):
        p = {"source": "Snap", "id": "obs-studio", "scope": "system"}
        with patch.object(b.os, "geteuid", return_value=0), patch.object(b, "revalidate"), \
             patch.object(b.subprocess, "call", return_value=1) as call, self.assertRaises(b.BackendError):
            b.privileged_apply(p)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(call.call_args.args[0], ["/usr/bin/snap", "save", "obs-studio"])

    def test_snap_save_precedes_remove(self):
        p = {"source": "Snap", "id": "obs-studio", "scope": "system"}
        with patch.object(b.os, "geteuid", return_value=0), patch.object(b, "revalidate"), \
             patch.object(b.subprocess, "call", return_value=0) as call:
            b.privileged_apply(p)
        self.assertEqual([c.args[0][1] for c in call.call_args_list], ["save", "remove"])

    def test_unprivileged_helper_refuses(self):
        with patch.object(b.os, "geteuid", return_value=1000), self.assertRaises(b.BackendError):
            b.privileged_apply({})

    def test_size_units(self):
        self.assertEqual(b.size_bytes("1.5 GB"), 1500000000)
        self.assertEqual(b.size_bytes("2 MiB"), 2097152)
        self.assertEqual(b.size_bytes("unknown"), 0)

    def test_flatpak_uses_declared_icon_instead_of_guessing_app_id(self):
        output = SimpleNamespace(stdout="org.example.App/x86_64/stable\tApp\t1\t10 MB\n")
        with patch.object(b.Path, "exists", return_value=True), \
             patch.object(b, "run", return_value=output), \
             patch.object(b, "desktop_meta", return_value=("App", "custom-app-icon", "")) as meta:
            apps = b.list_flatpak()
        self.assertEqual([a.icon for a in apps], ["custom-app-icon", "custom-app-icon"])
        self.assertEqual({a.scope for a in apps}, {"user", "system"})
        self.assertTrue(all(str(c.args[0]).endswith("org.example.App.desktop") for c in meta.call_args_list))


if __name__ == "__main__":
    unittest.main()
