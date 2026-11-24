# FaceKeys VN — uv + Windows 自动后台启动

这个项目是 Windows 端 HTTP → 键盘/鼠标映射接收器，不含 iPad 的人脸识别代码。

**为何不用 Windows Service？** Windows Service 运行在隔离的 Session 0，无法可靠地向当前桌面上的 VN 注入输入。这里使用 **任务计划程序 + 交互式用户会话**，登录 Windows 后自动启动，可无控制台窗口运行。

## 安装

先安装 uv，例如：

```powershell
winget install --id astral-sh.uv -e
```

打开新的 PowerShell，进入本目录（推荐 `C:\FaceKeysVN`），运行：

```powershell
cd C:\FaceKeysVN
uv python install 3.12
uv venv --python 3.12
.\.venv\Scripts\python.exe .\facekeys_server.py
```

首次会自动生成 `config.json`（其中 `token` 是随机密钥）。按 Ctrl+C 停止。测试通后用下面命令安装后台自启动：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_autostart.ps1
```

会立即启动，并在该 Windows 用户登录时自动运行。会以该用户的普通权限运行。

## 管理

```powershell
Get-ScheduledTask -TaskName FaceKeysVN
Stop-ScheduledTask -TaskName FaceKeysVN
Start-ScheduledTask -TaskName FaceKeysVN
Get-Content .\logs\facekeys.log -Tail 40
```

卸载自启：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\uninstall_autostart.ps1
```

## 重要设置

- **不要**选择“无论用户是否登录都运行”或者改成 `LocalSystem`；那样程序无法可靠地向 VN 注入键鼠输入。
- 在 Windows 登录后运行，屏幕锁定时不能操作锁屏的安全桌面。
- 如果 VN 以管理员权限运行，而 FaceKeys 是普通权限，`SendInput` 可能被 Windows 阻止。优先让 VN 也以普通权限运行。
- Windows 防火墙应只在专用网络允许 TCP 8765，不要向公网暴露；使用配置中的 `X-Api-Key` 认证。
- `facekeys_bg.pyw` 把输出写入 `logs\facekeys.log`，日志会随使用逐渐增大，可以在停止任务后清理。
- `config.json` 在首次启动时创建，不在压缩包里；可热更新 `mappings`，但修改监听端口需要重新启动。
- `uv` 主要用于安装和维护 `.venv`；自动任务直接启动 `.venv\Scripts\pythonw.exe`，因此启动时不依赖 `uv` 命令是否在 PATH 中。
