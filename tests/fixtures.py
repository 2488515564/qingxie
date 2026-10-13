from backend import App

def sample_apps():
    return [App("vlc", "VLC 播放器", "APT", "3.0 · 演示", 186*1024**2, "vlc", description="视频和音乐播放器"),
            App("app/org.inkscape.Inkscape/x86_64/stable", "Inkscape", "Flatpak", "1.4 · 演示", 412*1024**2, "org.inkscape.Inkscape", "user", description="矢量图形编辑器"),
            App("obs-studio", "OBS Studio", "Snap", "31.0 · 演示", 328*1024**2, "obs", description="录屏与直播"),
            App("ubuntu-desktop", "Ubuntu 桌面组件", "APT", "系统组件", 12*1024**2, "security-high", protected=True)]


