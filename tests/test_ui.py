"""Runs against a GTK display; package managers are mocked for all actions."""
import sys
import time
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main
from fixtures import sample_apps


@unittest.skipUnless(main.Gtk.init_check()[0], "GTK display not available")
class InterfaceTests(unittest.TestCase):
    def pump_until(self, check):
        deadline = time.monotonic() + 5
        while not check():
            if time.monotonic() > deadline:
                self.fail("GTK operation timed out")
            while main.Gtk.events_pending():
                main.Gtk.main_iteration_do(False)
            time.sleep(.01)

    def setUp(self):
        self.discover = patch.object(main.backend, "discover", return_value=(sample_apps(), []))
        self.discover.start()
        self.addCleanup(self.discover.stop)
        self.plan = patch.object(main.backend, "plan", side_effect=lambda a, purge, data: {
            "source": a.source, "id": a.id, "name": a.name, "scope": a.scope,
            "purge": purge, "delete_data": data, "notes": [],
            "removed": [{"id": a.id, "version": a.version, "size": a.size}]})
        self.plan.start()
        self.addCleanup(self.plan.stop)
        self.execution_guard = patch.object(main.subprocess, "Popen", side_effect=AssertionError("Unexpected system execution"))
        self.execution_guard.start()
        self.addCleanup(self.execution_guard.stop)
        self.win = main.Window()
        self.pump_until(lambda: not self.win.busy)

    def tearDown(self):
        # Window.destroy triggers main_quit, but this harness has no nested main loop.
        self.win.disconnect_by_func(main.Gtk.main_quit)
        self.win.destroy()

    def select(self, name):
        self.win.search.set_text(name)
        self.win.render_list()

    def test_search_filter_and_protection(self):
        self.select("VLC")
        self.assertEqual(len(self.win.listbox.get_children()), 1)
        self.assertEqual(self.win.selected.id, "vlc")
        self.select("Ubuntu")
        self.assertFalse(self.win.action.get_sensitive())
        self.select("does-not-exist")
        self.assertIsNone(self.win.selected)
        self.assertFalse(self.win.action.get_sensitive())

    def test_cancel_does_not_remove(self):
        self.select("VLC")
        with patch.object(main.Gtk.Dialog, "run", return_value=main.Gtk.ResponseType.CANCEL):
            self.win.start_preview()
            self.pump_until(lambda: not self.win.busy)
        self.assertEqual(len(self.win.apps), 4)
        self.assertEqual(self.win.status.get_text(), "已取消，未更改系统。")

    def test_confirmation_calls_executor_only_after_acceptance(self):
        self.select("VLC")
        with patch.object(main.Gtk.Dialog, "run", return_value=main.Gtk.ResponseType.OK), \
             patch.object(self.win, "execute") as execute:
            self.win.start_preview()
            self.pump_until(lambda: not self.win.busy)
            execute.assert_called_once()
            self.assertEqual(execute.call_args.args[0]["id"], "vlc")

    def test_no_demo_switch(self):
        self.assertFalse(hasattr(self.win, "mode"))
        self.assertFalse(hasattr(self.win, "demo"))

    def test_large_file_icons_are_scaled_and_keep_aspect_ratio(self):
        with tempfile.TemporaryDirectory() as directory:
            for width, height in [(2048, 2048), (2048, 512), (512, 2048)]:
                path = str(Path(directory) / f"{width}x{height}.png")
                pix = main.GdkPixbuf.Pixbuf.new(main.GdkPixbuf.Colorspace.RGB, True, 8, width, height)
                pix.fill(0xE95420FF)
                pix.savev(path, "png", [], [])
                image = main.app_icon(path)
                scaled = image.get_pixbuf()
                self.assertLessEqual(scaled.get_width(), 38)
                self.assertLessEqual(scaled.get_height(), 38)
                self.assertAlmostEqual(scaled.get_width() / scaled.get_height(), width / height, delta=.25)
                image.show()
                self.assertLessEqual(image.get_preferred_width()[1], 38)
                self.assertLessEqual(image.get_preferred_height()[1], 38)

    def test_svg_and_missing_file_icons_are_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "large.svg"
            path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="4096" height="1024"><rect width="4096" height="1024" fill="red"/></svg>')
            for name in (str(path), str(path.with_name("missing.png")), "application-x-executable"):
                image = main.app_icon(name)
                image.show()
                self.assertLessEqual(image.get_preferred_width()[1], 38)
                self.assertLessEqual(image.get_preferred_height()[1], 38)

    def test_unthemed_pixmap_loads_without_has_icon_precheck(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "qingxie-test-unthemed.png")
            pix = main.GdkPixbuf.Pixbuf.new(main.GdkPixbuf.Colorspace.RGB, True, 8, 256, 256)
            pix.fill(0xE95420FF)
            pix.savev(path, "png", [], [])
            theme = main.Gtk.IconTheme.new()
            theme.set_search_path([directory])
            theme.set_custom_theme("hicolor")
            self.assertFalse(theme.has_icon("qingxie-test-unthemed"))
            with patch.object(main.Gtk.IconTheme, "get_default", return_value=theme):
                image = main.app_icon("qingxie-test-unthemed")
            self.assertEqual(image.get_storage_type(), main.Gtk.ImageType.PIXBUF)
            self.assertIsNone(image.get_tooltip_text())
            self.assertLessEqual(image.get_pixbuf().get_width(), 38)

    def test_exported_icon_roots_are_added_once(self):
        with tempfile.TemporaryDirectory() as directory:
            exported = Path(directory) / "flatpak/exports/share/icons"
            exported.mkdir(parents=True)
            theme = main.Gtk.IconTheme.new()
            theme.set_search_path([])
            with patch.dict(main.os.environ, {"XDG_DATA_HOME": directory}), \
                 patch.object(main.Gtk.IconTheme, "get_default", return_value=theme):
                main.configure_icon_paths()
                main.configure_icon_paths()
            self.assertEqual(theme.get_search_path().count(str(exported)), 1)


if __name__ == "__main__":
    unittest.main()
