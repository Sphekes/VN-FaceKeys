# FaceKeys VN：iPad 面部控制 → Windows VN

本目录包含 Windows HTTP 输入映射服务端，**不包含 iPad 面部识别程序**。

## 快速运行

1. 在 Windows 10/11 上安装 Python 3.10 或更新版本。
2. 双击或终端运行 `python facekeys_server.py`。
3. 首次启动时自动生成 `config.json`（包含随机 API 密钥）。
4. 在 `config.json` 的 `mappings` 中编辑动作映射。配置更改自动生效（监听 IP 和端口要重启）。
5. 在 Windows PowerShell 中本机测试：

   ```powershell
   curl.exe -X POST "http://127.0.0.1:8765/press/blink" -H "X-Api-Key: 从config.json复制token"
   ```

6. iPad 连接相同可信局域网，创建「快捷指令」→「获取 URL 内容」，方法 POST、URL `http://Windows主机局域网IP:8765/press/blink`、自定义请求头 `X-Api-Key` 为配置中的 token。
7. 先在 iPad 手动运行快捷指令，验证 Windows VN 是否收到输入；最后再验证 iPadOS「头部跟踪」是否可将表情设置为运行该快捷指令。

> 注意：iPadOS 头部跟踪确认可以通过表情触发系统动作，但将表情直接绑定到任意快捷指令的兼容性取决于系统版本和可选动作列表，并未保证一定支持。如果无法绑定，需要换用可以发 HTTP 的前端触发方式。

## JSON 动作格式

- 单键 `{"type":"key","key":"ENTER"}`
- 组合键 `{"type":"hotkey","keys":["CTRL","S"]}`
- 鼠标点击 `{"type":"mouse","button":"left"}`（支持 `right`/`middle` 和 `count`: 1~3）
- 滚轮 `{"type":"scroll","steps":1}`（正数上滚，负数下滚）
- 顺序执行 `{"type":"sequence","steps":[{"type":"key","key":"ESC"},{"type":"wait","ms":100},{"type":"key","key":"ENTER"}]}`
- `hold_ms`: 单次按住时长，20~2000 毫秒；`cooldown_ms`: 同一动作两次触发的最小间隔，0~60000 毫秒。

例子：把 `blink` 映射成 Enter：

```json
"blink": {"type":"key", "key":"ENTER", "cooldown_ms":700}
```

## 安全与兼容

- 仅在私人可信的局域网内使用，不要在路由器上开放/映射 8765 端口。
- iPad 与 Windows 主机不在同一 Wi-Fi 时，考虑可信 VPN（例如 Tailscale）；不要直接暴露无加密 HTTP 到公网。
- Windows 防火墙首次提示时，只允许私人网络。可以通过主机 IP `ipconfig` 查找局域网 IPv4 地址。
- 如果 VN 以管理员权限运行而服务端是普通用户，Windows 的 UIPI 可能拦截 SendInput；一般让两个程序运行在同一权限级别即可。
- 游戏可能对模拟输入有兼容性限制。先用记事本、窗口化 VN 测试，再测全屏 VN。
- 鼠标左键总是点击 Windows **当前鼠标位置**，而不是固定游戏区域；如果只是推进文本，通常 Enter 更稳定。
- 系统默认眨眼可能频繁触发。推荐将推进绑定到故意做出的表情，利用 cooldown 限制重复；cooldown 并不能判断意图。
