<p align="center"><img src="assets/qingxie.png" width="128" alt="轻卸图标"></p>

# 轻卸 Qingxie

一个简洁直观的 Ubuntu 软件卸载工具。找到软件，查看卸载范围，再确认执行。

基于 Python 3 和 GTK 3，支持 APT、Snap、Flatpak。当前版本：**0.1.4**。

[下载安装包或免安装版](https://github.com/2488515564/qingxie/releases/latest) · [反馈问题](https://github.com/2488515564/qingxie/issues)

## 功能

- 统一浏览软件，按名称或软件包 ID 搜索，按来源筛选、按大小排序。
- APT 默认显示桌面应用，高级选项可查看所有已安装包。
- 先预览完整关联删除范围，再确认卸载；涉及配置或数据清理时额外确认。
- 拦截已知关键系统组件，检查关联删除项，不自动清理共享依赖。
- 图标等比例缩放，支持主题图标、pixmaps、Snap/Flatpak 导出路径。
- 实时日志与错误提示。免安装版支持 Wayland 的桌面图标关联。

## 安装与启动

### DEB 安装包

在 [Releases](https://github.com/2488515564/qingxie/releases/latest) 下载 `qingxie_0.1.4_all.deb`，用系统软件安装器打开，或在下载目录运行：

```bash
sudo apt install ./qingxie_0.1.4_all.deb
```

然后从应用菜单搜索“轻卸”。升级时安装新版 DEB 即可。

### 免安装版

下载 `qingxie-0.1.4-portable.tar.gz` 并完整解压，在解压后的 `qingxie` 文件夹中运行：

```bash
./启动轻卸.sh
```

也可以在文件管理器中选择“作为程序运行”。依赖缺失时：

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 python3-apt pkexec
```

首次运行会创建当前用户的 `~/.local/share/applications/qingxie-portable.desktop`（尊重 `XDG_DATA_HOME`），用于任务栏图标与应用菜单关联，无需管理员权限。移动程序目录后重新运行启动脚本会更新路径。删除免安装版时，可一并删除此入口。

请在 Ubuntu 图形桌面中以普通用户运行；APT 和 Snap 卸载会通过系统授权窗口请求管理员权限。轻卸不保存密码。

## 卸载与数据保留

| 来源 | 卸载范围 | 数据处理 |
| --- | --- | --- |
| APT | 使用 Python APT 计算完整删除计划；授权后在系统锁内复核，范围或版本变化则停止 | 默认保留配置，可清除包管理器管理的系统配置；用户目录中的个人配置和缓存保留 |
| Snap | 先显式创建数据快照，成功后卸载；snapd 会检查组件依赖 | 原应用数据目录会移除，本机快照保留；快照占用空间，因此卸载不一定立即净释放空间 |
| Flatpak | 区分当前用户和默认系统安装，使用完整应用引用；不自动移除运行时或关联扩展 | 默认保留数据；可选择删除当前用户的全部应用数据。多个安装或分支共享数据时禁止清理 |

Flatpak 的“删除全部应用数据”可能涉及账号、存档和应用内部文件，并不只是偏好设置。

Snap 快照 ID 会显示在日志中。恢复时先重新安装相同 Snap，再通过 `snap saved` 查找快照，执行 `sudo snap restore <快照ID>`。轻卸目前没有一键恢复按钮。

## 版本范围

- 适用于常规 Ubuntu 桌面；当前验证环境为 Ubuntu 24.04 / GTK 3 / Wayland。
- 显示的是包管理器报告的安装大小或 Snap 镜像大小，不保证等于释放空间。
- 不处理 AppImage、手工解压和脚本安装的软件，不扫描未知缓存或个人配置目录。
- Flatpak 支持当前用户和默认系统安装，不包含自定义命名安装目录。
- 系统组件保护策略较保守，可能拦截高级操作，没有强制删除开关。
- 卸载期间窗口禁止关闭。失败后会重新读取列表，但不保证所有步骤都已回滚。
- 日志仅保留在当前窗口内，不上传信息，不添加后台服务，不自动更新。

## 从源码运行与构建

```bash
git clone https://github.com/2488515564/qingxie.git
cd qingxie
python3 main.py
```

生成 DEB、免安装包和校验和（无需 root）：

```bash
python3 build_release.py
```

文件生成在 `dist/`。构建需要 `dpkg-deb` 和上述 Python/GTK 依赖。

测试：

```bash
python3 -m unittest discover -s tests -v
```

GUI 测试需要图形显示；无显示时会跳过。也可以安装 `xvfb` 后运行 `xvfb-run -a python3 -m unittest discover -s tests -v`。

26 项测试覆盖卸载计划与组件保护、模拟执行、图标缩放、桌面入口及特殊路径处理。测试不会执行真实卸载。本机只读扫描和 APT 卸载计划已验证；Snap/Flatpak 真实事务仍需在一次性虚拟机中进一步验收。

## 项目结构

- `main.py`：GTK 界面
- `backend.py`：软件发现、卸载计划和执行
- `desktop_integration.py`：免安装版桌面关联
- `build_deb.py` / `build_release.py`：打包
- `tests/`：测试
- `assets/`：图标及生成说明

## 参考

[Ubuntu APT](https://manpages.ubuntu.com/manpages/noble/man8/apt-get.8.html) · [Flatpak 命令参考](https://docs.flatpak.org/en/latest/flatpak-command-reference.html) · [Snap 数据快照](https://snapcraft.io/docs/how-to-guides/manage-snaps/create-data-snapshots/)
