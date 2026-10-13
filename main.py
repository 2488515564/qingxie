#!/usr/bin/python3
"""Native GTK 3 desktop UI for Qingxie."""
import argparse
from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys
import threading

try:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, Gdk, GdkPixbuf, GLib, Pango
except (ImportError, ValueError):
    sys.exit("缺少 GTK 依赖。请安装：sudo apt install python3-gi gir1.2-gtk-3.0 python3-apt")

import backend
import desktop_integration


def human_size(n):
    if not n:
        return "未提供"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
        n /= 1024


def label(text="", css=None):
    w = Gtk.Label(label=text, xalign=0)
    w.set_line_wrap(True)
    w.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if css:
        w.get_style_context().add_class(css)
    return w


ICON_SIZE = 38


def configure_icon_paths():
    """Include exported application assets even with a minimal desktop environment."""
    theme = Gtk.IconTheme.get_default()
    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    roots = [data_home, Path("/usr/local/share"), Path("/usr/share"),
             data_home / "flatpak/exports/share", Path("/var/lib/flatpak/exports/share"),
             Path("/var/lib/snapd/desktop")]
    existing = set(theme.get_search_path())
    for root in roots:
        for kind in ("icons", "pixmaps"):
            path = root / kind
            if path.is_dir() and str(path) not in existing:
                theme.append_search_path(str(path))
                existing.add(str(path))


def app_icon(value):
    """Bound the decoded image itself; Gtk.Image.pixel_size ignores file pixbufs."""
    theme = Gtk.IconTheme.get_default()
    try:
        if Path(value).is_absolute():
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(value, ICON_SIZE, ICON_SIZE, True)
        else:
            # has_icon() can reject unthemed pixmaps that load_icon() can resolve.
            try:
                pixbuf = theme.load_icon(value, ICON_SIZE, Gtk.IconLookupFlags.FORCE_SIZE)
            except GLib.Error:
                if Path(value).suffix.lower() not in (".png", ".svg", ".xpm"):
                    raise
                pixbuf = theme.load_icon(Path(value).stem, ICON_SIZE, Gtk.IconLookupFlags.FORCE_SIZE)
        width, height = pixbuf.get_width(), pixbuf.get_height()
        if max(width, height) > ICON_SIZE:
            ratio = ICON_SIZE / max(width, height)
            pixbuf = pixbuf.scale_simple(max(1, round(width * ratio)), max(1, round(height * ratio)), GdkPixbuf.InterpType.BILINEAR)
        image = Gtk.Image.new_from_pixbuf(pixbuf)
    except (GLib.Error, OSError, ValueError, TypeError):
        image = Gtk.Image.new_from_icon_name("application-x-executable", Gtk.IconSize.DIALOG)
        image.set_pixel_size(ICON_SIZE)
        image.set_tooltip_text("未找到可用的软件图标，显示通用图标")
    image.set_size_request(ICON_SIZE, ICON_SIZE)
    image.set_valign(Gtk.Align.CENTER)
    image.set_halign(Gtk.Align.CENTER)
    return image


class Window(Gtk.Window):
    def __init__(self):
        super().__init__(title="轻卸 · Ubuntu 软件管家")
        self.apps = []
        self.selected = None
        self.busy = False
        self.removing = False
        self.pending_plan = None
        self.log_lines = []
        self.set_default_size(1040, 760)
        self.set_size_request(760, 580)
        self.set_icon_name("qingxie")
        icon_path = Path(__file__).resolve().parent / "assets/qingxie.png"
        if icon_path.is_file():
            try:
                self.set_icon_list([GdkPixbuf.Pixbuf.new_from_file_at_scale(
                    str(icon_path), size, size, True) for size in (32, 48, 64, 128, 256)])
            except GLib.Error:
                pass
        self.set_wmclass(desktop_integration.APP_ID, desktop_integration.APP_ID)
        self.connect("delete-event", self.on_close)
        self.connect("destroy", Gtk.main_quit)
        css = Gtk.CssProvider()
        css.load_from_data(b"""
        window { background: @theme_bg_color; }
        .hero { font-size: 25px; font-weight: bold; }
        .heading { font-size: 19px; font-weight: bold; }
        .muted { opacity: 0.72; }
        .amount { font-size: 30px; font-weight: bold; }
        .panel { background: @theme_base_color; border-radius: 14px; padding: 20px; }
        .app-row { padding: 13px 10px; border-radius: 10px; margin: 3px; }
        .app-row:selected { background: alpha(#e95420, 0.16); color: @theme_fg_color; }
        .primary { background: #c54116; color: white; border-radius: 8px; padding: 10px 18px; }
        .primary:disabled { background: alpha(#c54116, 0.25); color: @theme_fg_color; }
        .badge { background: alpha(#e95420, 0.12); padding: 4px 9px; border-radius: 8px; }
        .status { padding: 9px 0; }
        """)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        header = Gtk.HeaderBar(title="轻卸", subtitle="软件卸载，清楚简单")
        header.set_show_close_button(True)
        self.set_titlebar(header)
        self.refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        self.refresh_btn.set_tooltip_text("刷新软件列表")
        self.refresh_btn.connect("clicked", lambda _: self.refresh())
        header.pack_end(self.refresh_btn)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, margin=24)
        self.add(outer)
        outer.pack_start(label("让电脑，轻一点。", "hero"), False, False, 0)
        self.subtitle = label("找到不需要的软件，先预览影响，再确认卸载。", "muted")
        outer.pack_start(self.subtitle, False, False, 0)
        toolbar = Gtk.Box(spacing=10)
        self.search = Gtk.SearchEntry(placeholder_text="搜索软件名称或软件包 ID")
        self.search.connect("search-changed", lambda _: self.render_list())
        toolbar.pack_start(self.search, True, True, 0)
        self.source = Gtk.ComboBoxText()
        for text in ("全部来源", "APT", "Snap", "Flatpak"):
            self.source.append_text(text)
        self.source.set_active(0)
        self.source.connect("changed", lambda _: self.render_list())
        toolbar.pack_start(self.source, False, False, 0)
        self.sort = Gtk.ComboBoxText()
        for text in ("按名称", "按占用空间"):
            self.sort.append_text(text)
        self.sort.set_active(0)
        self.sort.connect("changed", lambda _: self.render_list())
        toolbar.pack_start(self.sort, False, False, 0)
        outer.pack_start(toolbar, False, False, 0)
        body = Gtk.Box(spacing=18)
        outer.pack_start(body, True, True, 0)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        body.pack_start(left, True, True, 0)
        self.count = label("正在读取…", "muted")
        left.pack_start(self.count, False, False, 0)
        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.listbox.connect("row-selected", self.select_app)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.listbox)
        left.pack_start(scroll, True, True, 0)
        self.advanced = Gtk.CheckButton(label="显示 APT 的全部软件包（高级）")
        self.advanced.connect("toggled", lambda _: self.refresh())
        left.pack_start(self.advanced, False, False, 0)
        self.panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.panel.set_size_request(320, -1)
        self.panel.get_style_context().add_class("panel")
        detail_scroll = Gtk.ScrolledWindow()
        detail_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        detail_scroll.set_min_content_width(330)
        detail_scroll.add(self.panel)
        body.pack_start(detail_scroll, True, True, 0)
        self.title = label("选择一个软件", "heading")
        self.meta = label("", "muted")
        self.size = label("—", "amount")
        self.description = label()
        for w in (self.title, self.meta, self.size, label("已安装大小 · 不等于实际释放空间", "muted"), self.description):
            self.panel.pack_start(w, False, False, 0)
        self.purge = Gtk.CheckButton(label="同时清除软件包的系统配置")
        self.data = Gtk.CheckButton(label="删除当前用户的全部应用数据")
        self.option_hint = label("", "muted")
        for w in (self.purge, self.data, self.option_hint):
            self.panel.pack_start(w, False, False, 0)
        self.preview = label("先选择软件，再查看卸载范围。")
        self.panel.pack_start(Gtk.Separator(), False, False, 0)
        self.panel.pack_start(self.preview, False, False, 0)
        self.action = Gtk.Button(label="预览卸载")
        self.action.get_style_context().add_class("primary")
        self.action.set_sensitive(False)
        self.action.connect("clicked", self.start_preview)
        self.panel.pack_end(self.action, False, False, 0)
        status_row = Gtk.Box(spacing=8)
        self.spinner = Gtk.Spinner()
        status_row.pack_start(self.spinner, False, False, 0)
        self.status = label("", "status")
        status_row.pack_start(self.status, True, True, 0)
        outer.pack_start(status_row, False, False, 0)
        expander = Gtk.Expander(label="执行日志与诊断")
        self.logview = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        logs = Gtk.ScrolledWindow(min_content_height=100)
        logs.add(self.logview)
        expander.add(logs)
        outer.pack_start(expander, False, False, 0)
        self.show_all()
        self.refresh()

    def on_close(self, *_):
        if self.removing:
            self.status.set_text("卸载正在进行，请等操作结束后再关闭。")
            return True
        return False

    def set_busy(self, busy, text=""):
        self.busy = busy
        for w in (self.refresh_btn, self.advanced, self.search, self.source, self.sort, self.listbox, self.purge, self.data):
            w.set_sensitive(not busy)
        if busy:
            self.spinner.start()
        else:
            self.spinner.stop()
        self.action.set_sensitive(not busy and self.selected is not None and not self.selected.protected)
        if text:
            self.status.set_text(text)

    def async_job(self, fn, success):
        def task():
            try:
                result = fn()
                GLib.idle_add(success, result)
            except Exception as e:
                GLib.idle_add(self.failed, str(e))
        threading.Thread(target=task, daemon=True).start()

    def failed(self, error):
        self.removing = False
        self.set_busy(False, backend.friendly_error(error))
        self.append_log(error)

    def append_log(self, text):
        self.log_lines.append(text)
        self.log_lines = self.log_lines[-1500:]
        self.logview.get_buffer().set_text("\n".join(self.log_lines))

    def refresh(self):
        if self.busy:
            return
        self.set_busy(True, "正在读取软件列表…")
        configure_icon_paths()
        self.subtitle.set_text("预览只读，确认后才会执行卸载。")
        advanced = self.advanced.get_active()
        self.async_job(lambda: backend.discover(advanced), self.loaded)

    def loaded(self, result):
        self.apps, warnings = result
        self.set_busy(False, "；".join(warnings) if warnings else "列表已更新。缺少的安装来源会自动跳过。")
        for warning in warnings:
            self.append_log(warning)
        self.render_list()

    def render_list(self):
        previous = self.selected.key if self.selected else None
        for child in self.listbox.get_children():
            self.listbox.remove(child)
        query = self.search.get_text().casefold().strip()
        source = self.source.get_active_text()
        apps = [a for a in self.apps if (source == "全部来源" or a.source == source) and query in (a.name + " " + a.id).casefold()]
        apps.sort(key=(lambda a: -a.size) if self.sort.get_active() == 1 else (lambda a: a.name.casefold()))
        selected_row = None
        for app in apps:
            row = Gtk.ListBoxRow()
            row.app = app
            row.get_style_context().add_class("app-row")
            box = Gtk.Box(spacing=12)
            icon = app_icon(app.icon)
            box.pack_start(icon, False, False, 0)
            words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            name = label(app.name)
            name.set_ellipsize(Pango.EllipsizeMode.END)
            name.set_max_width_chars(25)
            words.pack_start(name, False, False, 0)
            words.pack_start(label(app.source + (" · 当前用户" if app.scope == "user" else " · 系统") + (" · 已保护" if app.protected else ""), "muted"), False, False, 0)
            box.pack_start(words, True, True, 0)
            box.pack_end(label(human_size(app.size), "muted"), False, False, 0)
            row.add(box)
            self.listbox.add(row)
            if app.key == previous:
                selected_row = row
        self.count.set_text(f"{len(apps)} 个软件" + (" · 搜索无结果" if not apps else ""))
        self.listbox.show_all()
        self.listbox.select_row(selected_row or self.listbox.get_row_at_index(0))
        if not apps:
            self.select_app(self.listbox, None)

    def select_app(self, _, row):
        self.selected = row.app if row else None
        self.purge.set_active(False)
        self.data.set_active(False)
        a = self.selected
        self.purge.set_visible(bool(a and a.source == "APT"))
        self.data.set_visible(bool(a and a.source == "Flatpak"))
        self.title.set_text(a.name if a else "没有匹配的软件")
        self.meta.set_text(f"{a.id}\n{a.source} · {a.version}" if a else "换个关键词或安装来源试试。")
        self.size.set_text(human_size(a.size) if a else "—")
        self.description.set_text(a.description if a else "")
        self.action.set_sensitive(bool(a and not a.protected and not self.busy))
        self.action.set_label("系统组件已保护" if a and a.protected else "预览卸载")
        self.preview.set_text("不能在这里卸载这个系统组件。" if a and a.protected else "预览会列出删除范围，随后再次确认。")
        hints = {"APT": "默认保留个人配置和缓存。系统配置由包管理器清理；不会扫描或删除未知文件。",
                 "Snap": "先创建数据快照，成功后再卸载。应用数据将从原目录移除，可通过 Snap 快照恢复。",
                 "Flatpak": "默认保留数据。勾选将删除全部应用数据，可能包括账号、存档及设置。"}
        self.option_hint.set_text(hints.get(a.source, "") if a else "")

    def start_preview(self, _=None):
        a = self.selected
        if self.busy or not a or a.protected:
            return
        purge, data = self.purge.get_active(), self.data.get_active()
        self.set_busy(True, "正在检查卸载影响…")
        self.async_job(lambda: backend.plan(a, purge, data), self.preview_ready)

    def preview_ready(self, p):
        self.pending_plan = p
        self.set_busy(False, "预览完成，请核对以下卸载范围。")
        text = "将移除：\n" + "\n".join("• " + item["id"] for item in p["removed"])
        text += "\n\n" + "\n".join(p["notes"])
        self.preview.set_text(f"涉及 {len(p['removed'])} 个软件包 · 合计安装大小 {human_size(sum(i['size'] for i in p['removed']))}")
        dialog = Gtk.Dialog(title="确认卸载", transient_for=self, modal=True)
        dialog.set_default_size(560, 400)
        dialog.add_button("取消", Gtk.ResponseType.CANCEL)
        confirm = dialog.add_button("确认卸载", Gtk.ResponseType.OK)
        confirm.get_style_context().add_class("destructive-action")
        dialog.set_default_response(Gtk.ResponseType.CANCEL)
        content = dialog.get_content_area()
        content.set_spacing(12)
        content.set_border_width(20)
        content.pack_start(label("卸载 " + p["name"], "heading"), False, False, 0)
        sw = Gtk.ScrolledWindow(min_content_height=200)
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        details = label(text)
        details.set_max_width_chars(65)
        details.set_selectable(True)
        sw.add(details)
        content.pack_start(sw, True, True, 0)
        acknowledgement = None
        if len(p["removed"]) > 1 or p["delete_data"] or p["purge"]:
            acknowledgement = Gtk.CheckButton(label="我已核对关联删除与数据清理范围")
            confirm.set_sensitive(False)
            acknowledgement.connect("toggled", lambda c: confirm.set_sensitive(c.get_active()))
            content.pack_start(acknowledgement, False, False, 0)
        dialog.show_all()
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            self.execute(p)
        else:
            self.status.set_text("已取消，未更改系统。")

    def execute(self, p):
        self.removing = True
        self.set_busy(True, "正在卸载，请完成可能出现的系统授权…")
        self.append_log(datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " · " + p["name"])
        def work():
            backend.revalidate(p)
            cmd = backend.apply_command(p)
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, errors="replace",
                                    env={**os.environ, "LC_ALL": "C", "LANG": "C", "DEBIAN_FRONTEND": "noninteractive"})
            output = []
            for line in proc.stdout:
                output.append(line)
                GLib.idle_add(self.append_log, line.rstrip())
            return proc.wait(), "".join(output)
        def done(result):
            code, output = result
            self.removing = False
            if code:
                # Refresh after failures too: a package manager can partially complete.
                self.append_log("操作未完成。" + output)
                self.set_busy(False)
                self.refresh()
                message = backend.friendly_error(output.strip() or ("系统授权已取消。" if code in (126, 127) else f"退出码 {code}"))
                dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.ERROR,
                                           buttons=Gtk.ButtonsType.CLOSE, text="卸载未完成")
                dialog.format_secondary_text(message[-1500:] + "\n列表将重新读取，请检查日志。")
                dialog.run()
                dialog.destroy()
                return
            self.append_log("卸载完成。")
            self.set_busy(False)
            self.refresh()
        self.async_job(work, done)


def main():
    GLib.set_prgname(desktop_integration.APP_ID)
    GLib.set_application_name("轻卸")
    parser = argparse.ArgumentParser(description="轻卸 · Ubuntu 软件管家")
    parser.parse_args()
    desktop_error = None
    if os.geteuid() != 0 and desktop_integration.PORTABLE:
        try:
            desktop_integration.register_portable()
        except OSError as e:
            desktop_error = "桌面图标关联失败：" + str(e)
    if not Gtk.init_check()[0]:
        sys.exit("无法连接桌面显示服务。请在 Ubuntu 桌面会话中运行 ./启动轻卸.sh。")
    if os.geteuid() == 0:
        sys.exit("请以普通用户启动轻卸，卸载时会单独请求管理员授权。")
    win = Window()
    if desktop_error:
        win.append_log(desktop_error)
        dialog = Gtk.MessageDialog(transient_for=win, modal=True,
                                   message_type=Gtk.MessageType.WARNING,
                                   buttons=Gtk.ButtonsType.CLOSE, text="桌面图标未能注册")
        dialog.format_secondary_text(desktop_error)
        dialog.run()
        dialog.destroy()
    Gtk.main()


if __name__ == "__main__":
    main()
