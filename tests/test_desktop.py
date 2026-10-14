import sys
import tempfile
from pathlib import Path
import unittest
import gi
from gi.repository import Gio, GLib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import desktop_integration as desktop


class DesktopTests(unittest.TestCase):
    def root(self, directory, name="轻卸 portable"):
        root = Path(directory) / name
        (root / "assets").mkdir(parents=True)
        (root / "main.py").touch()
        (root / "assets/qingxie.png").touch()
        return root

    def test_valid_entry_has_matching_identity_and_icon(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.root(directory)
            path = desktop.register_portable(root, Path(directory) / "data")
            info = Gio.DesktopAppInfo.new_from_filename(str(path))
            self.assertIsNotNone(info)
            self.assertEqual(info.get_startup_wm_class(), "qingxie-portable")
            self.assertEqual(info.get_icon().get_file().get_path(), str(root / "assets/qingxie.png"))
            self.assertEqual(info.get_executable(), "/usr/bin/python3")
            self.assertEqual(path.stem, "qingxie-portable")
            self.assertTrue(info.get_nodisplay())
            self.assertFalse(info.should_show())
            self.assertFalse(info.get_is_hidden())

    def test_legacy_visible_entry_is_migrated_without_touching_installed_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.root(directory)
            data = Path(directory) / "data"
            path = desktop.register_portable(root, data)
            path.write_text(path.read_text().replace("NoDisplay=true\n", ""))
            installed = path.with_name("qingxie.desktop")
            original = "[Desktop Entry]\nType=Application\nName=轻卸\nExec=qingxie\n"
            installed.write_text(original)
            desktop.register_portable(root, data)
            info = Gio.DesktopAppInfo.new_from_filename(str(path))
            self.assertFalse(info.should_show())
            self.assertTrue(info.get_nodisplay())
            self.assertEqual(installed.read_text(), original)

    def test_repeated_registration_and_folder_move(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.root(directory)
            data = Path(directory) / "data"
            path = desktop.register_portable(root, data)
            before = path.stat().st_mtime_ns
            desktop.register_portable(root, data)
            self.assertEqual(before, path.stat().st_mtime_ns)
            moved = root.rename(root.with_name("moved"))
            desktop.register_portable(moved, data)
            self.assertIn(str(moved / "assets/qingxie.png"), path.read_text())

    def test_unrelated_entry_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.root(directory)
            data = Path(directory) / "data"
            path = data / "applications/qingxie-portable.desktop"
            path.parent.mkdir(parents=True)
            path.write_text("[Desktop Entry]\nName=Other\n")
            with self.assertRaises(OSError):
                desktop.register_portable(root, data)
            self.assertIn("Name=Other", path.read_text())

    def test_exec_escaping_handles_special_directory_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.root(directory, 'space $cash `tick` "quote" %x \\slash')
            path = desktop.register_portable(root, Path(directory) / "data")
            key = GLib.KeyFile.new()
            key.load_from_file(str(path), GLib.KeyFileFlags.NONE)
            command = key.get_string("Desktop Entry", "Exec")
            ok, args = GLib.shell_parse_argv(command)
            self.assertTrue(ok)
            self.assertEqual(args[1].replace("%%", "%"), str(root / "main.py"))


if __name__ == "__main__":
    unittest.main()
