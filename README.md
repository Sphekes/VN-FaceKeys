# VN FaceKeys

**VN FaceKeys** 让你在 iPad 串流 Windows 视觉小说（Visual Novel，VN）时，通过眨眼、微笑等面部表情控制电脑的鼠标和键盘，实现免手阅读。

它与 iPadOS 自带的头部追踪（Head Tracking）和快捷指令（Shortcuts）配合使用，支持自定义按键、组合键和宏，以及后台常驻和登录自动启动。

```text
iPad 前置摄像头 → 头部追踪 → 快捷指令
                                │ HTTP POST（局域网）
                                ▼
                  VN FaceKeys → Windows 键盘 / 鼠标 → VN
                  VoidLink    ← Windows 串流画面
```

| 面部表情 | 动作 ID | 默认操作 | VN 常见用途 |
| --- | --- | --- | --- |
| 眨眼 | `blink` | 鼠标左键 | 推进文本 |
| 微笑 | `smile` | 鼠标右键 | 菜单、隐藏文本框 |
| 皱眉 | `frown` | 滚轮向上 | 查看历史文本 |
| 张嘴 | `mouth` | 滚轮向下 | 向后滚动历史文本 |
| 吐舌 | `tongue` | 鼠标中键 | 依游戏而定 |

所有映射均可通过配置文件调整，保存后即时生效。

**版本：0.2.0**

## 1. 环境要求

- Windows 10 / 11。
- Python 3.10+（推荐 3.12），仅使用标准库，零第三方依赖。
- iPadOS 26+，需要支持头部追踪功能。
- iPad 上的快捷指令 App 和串流客户端（推荐 VoidLink）。
- 电脑与 iPad 处于互通的可信局域网或 VPN，默认 TCP 端口 `8765`。

## 2. 电脑端安装指南

### 2.1 解压项目

将项目解压至固定、可读写的目录，例如 `C:\VN FaceKeys`。打开 PowerShell，进入包含 `facekeys_server.py` 的目录：

```powershell
cd 'C:\VN FaceKeys'
```

以下电脑端命令均在项目目录执行。

### 2.2 准备 Python 环境

任选一种方式创建项目专用的 `.venv`。

**方式 A：uv（推荐尚未安装 Python 的用户）**

安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)：

```powershell
winget install --id astral-sh.uv -e
```

重新打开 PowerShell，进入项目目录，执行：

```powershell
uv python install 3.12
uv venv --python 3.12
```

**方式 B：原生 Python**

从 [Python 官网](https://www.python.org/downloads/windows/) 安装 Python 3.12，或使用已有的 3.10+ 版本：

```powershell
python -m venv .venv
```

也可使用 `py -3.12 -m venv .venv` 指定已安装的版本。

环境创建完成后，检查 Python 版本：

```powershell
.\.venv\Scripts\python.exe --version
```

后续统一使用 `.venv` 中的解释器，无需激活环境或安装额外依赖。请保留虚拟环境所依赖的基础 Python；迁移到其他电脑时重新创建 `.venv`。

### 2.3 前台运行

```powershell
.\.venv\Scripts\python.exe .\facekeys_server.py
```

首次启动自动生成 `config.json`，包含默认表情映射和随机访问密钥 `token`。启动成功后，控制台将显示类似日志：

```text
2026-11-25 08:00:00 INFO VN FaceKeys 0.2.0 已启动，监听 0.0.0.0:8765，dry_run=False
```

保持窗口打开即可使用，按 `Ctrl+C` 停止。已有配置会保留。

### 2.4 测试服务和鼠标输入

另开一个 PowerShell 窗口，进入项目目录，读取连接信息并测试健康检查接口：

```powershell
$cfg = Get-Content .\config.json -Raw -Encoding UTF8 | ConvertFrom-Json
$base = "http://127.0.0.1:$($cfg.port)"
$headers = @{ 'X-Api-Key' = $cfg.token }
Invoke-RestMethod -Uri "$base/health" -Method Get -Headers $headers
```

返回 `status: ok` 表示服务和密钥正常。若自定义了 `listen` 为指定网卡地址，请将 `127.0.0.1` 替换为该地址。

然后测试实际点击。打开 VN 或安全的测试窗口，执行以下命令，在三秒内切换至测试窗口并放好鼠标：

```powershell
Start-Sleep -Seconds 3
Invoke-WebRequest -UseBasicParsing -Uri "$base/action/blink" -Method Post -Headers $headers
```

成功时执行一次鼠标左键点击，返回 HTTP `204`，控制台显示完整动作日志。

**模拟模式（Dry Run）：** 用于安全测试表情识别。停止当前服务，改用：

```powershell
.\.venv\Scripts\python.exe .\facekeys_server.py --dry-run --loglevel DEBUG
```

该模式记录收到的动作、完整 JSON 和跳过原因，不会实际发送键鼠输入。认证、冷却、暂停及白名单仍然生效。测试结束后重新以前台普通模式或后台模式启动。

### 2.5 获取电脑 IP 并配置防火墙

```powershell
ipconfig
```

找到与 iPad 相通的网卡 IPv4 地址，例如 `192.168.1.100`（下文均以此为例，请替换为实际地址）。使用 VPN 时选择相应的 VPN 地址。

在可信家庭网络中，将 Windows 网络配置文件设为「专用」。以管理员身份打开 PowerShell，允许本地子网访问服务端口：

```powershell
New-NetFirewallRule -DisplayName 'VN FaceKeys (Private LAN)' `
  -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 `
  -Profile Private -RemoteAddress LocalSubnet
```

也可在「Windows Defender 防火墙（高级安全）」中创建等效入站规则。建议进一步将远程地址限定为 iPad 的 IP 或可信子网。使用自定义端口、VPN 时按实际网络调整规则。

### 2.6 后台常驻与登录自动启动（可选）

完成前台测试后，按 `Ctrl+C` 停止服务，然后执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_autostart.ps1
```

安装脚本会检查 Python 环境及配置，注册名为 `VN FaceKeys` 的计划任务，并立即请求启动。程序通过 `pythonw.exe` 静默运行，每次登录 Windows 后自动启动，异常退出时最多自动重试三次。重复安装可以更新任务设置。

再次执行 2.4 节的 `/health` 测试，并查看运行状态和日志：

```powershell
Get-ScheduledTask -TaskName 'VN FaceKeys'
Get-Content .\logs\facekeys.log -Tail 40 -Encoding UTF8
```

如需指定后台日志级别，可重新执行安装脚本：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_autostart.ps1 -LogLevel DEBUG
```

恢复默认方式时，重新执行普通安装命令即可。计划任务使用当前用户的交互式会话，请保留「仅当用户登录时运行」的设置。

### 2.7 日常管理与卸载

```powershell
# 停止（下次登录仍自动启动）
Stop-ScheduledTask -TaskName 'VN FaceKeys'

# 启动
Start-ScheduledTask -TaskName 'VN FaceKeys'

# 持续查看日志（Ctrl+C 结束；轮转后重新执行）
Get-Content .\logs\facekeys.log -Tail 20 -Wait -Encoding UTF8
```

取消后台自启动：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\uninstall_autostart.ps1
```

卸载会停止并删除计划任务，保留项目、Python 环境、配置和日志。建议先暂停输入，等待 `/status` 中的 `busy` 变为 `false`，再停止任务。

若彻底停止使用，可删除自行创建的防火墙规则（管理员 PowerShell）：

```powershell
Remove-NetFirewallRule -DisplayName 'VN FaceKeys (Private LAN)'
```

后台日志自动轮转，详情见[日志设置](#45-日志设置)。

## 3. iPad 端配置指南

### 3.1 准备连接信息

准备电脑的 IPv4 地址、服务端口（默认 `8765`）以及 `config.json` 中的 `token`。在电脑上查看密钥：

```powershell
(Get-Content .\config.json -Raw -Encoding UTF8 | ConvertFrom-Json).token
```

### 3.2 创建并测试连接捷径

1. 打开 iPad「快捷指令」App，点击 `+` 新建，命名为 `VN FaceKeys - Health`。
2. 搜索「获取 URL 内容」（Get Contents of URL），添加操作。
3. URL 填入 `http://192.168.1.100:8765/health`。
4. 展开操作，方法选择 `GET`，在「请求头」中添加 `X-Api-Key`，值填入实际 token。
5. 添加「显示结果」（Show Result），手动运行；首次访问时允许连接自己的电脑及局域网。

显示 `{"status":"ok"}` 即连接成功。若失败，请确认电脑端服务已启动、IP 和端口正确、防火墙及局域网权限已设置。

### 3.3 创建动作捷径

以眨眼为例，新建 `VN FaceKeys - Blink`，添加「获取 URL 内容」，填写：

| 项目 | 值 |
| --- | --- |
| URL | `http://192.168.1.100:8765/action/blink` |
| 方法 | `POST` |
| 请求头名称 | `X-Api-Key` |
| 请求头值 | 实际 token |
| 请求正文 | 留空，或发送空 JSON 对象 `{}` |

手动运行一次，确认电脑收到点击。成功时返回 HTTP `204`。动作捷径只需这一项操作；省略「显示结果」可减少串流时的弹窗。

复制捷径并修改名称及 URL 最后一段，完成五种默认表情配置：

| 捷径名称 | URL 路径 | 操作 |
| --- | --- | --- |
| VN FaceKeys - Blink | `/action/blink` | 左键 |
| VN FaceKeys - Smile | `/action/smile` | 右键 |
| VN FaceKeys - Frown | `/action/frown` | 滚轮上 |
| VN FaceKeys - Mouth | `/action/mouth` | 滚轮下 |
| VN FaceKeys - Tongue | `/action/tongue` | 中键 |

每条捷径使用相同的 IP、端口、POST 方法及请求头。更换连接信息时同步更新即可。参考 [Apple：在快捷指令中使用 API](https://support.apple.com/guide/shortcuts/apd58d46713f/ios)。

### 3.4 绑定头部追踪

1. 进入「设置 → 辅助功能 → 头部追踪（Head Tracking）」，开启头部追踪。
2. 进入「操作（Actions）」，选择「眨眼（Eye Blink）」。
3. 在操作列表的「快捷指令」区域选择 `VN FaceKeys - Blink`。
4. 按相同方式绑定微笑、皱眉、张嘴和吐舌。
5. 打开 VoidLink 连接 Windows，切换到 VN，逐一测试表情。

菜单名称和可用动作以设备实际显示为准。建议先完成眨眼的绑定和测试，再配置其他表情。若动作列表缺少快捷指令选项，请检查 iPadOS 版本和设备支持情况。参考 [Apple：头部追踪](https://support.apple.com/guide/ipad/ipad06393f31/ipados)。

### 3.5 暂停与恢复（可选）

可按 3.3 节的方法创建控制捷径，使用相同的服务器地址及请求头：

| 路径 | 方法 | 功能 |
| --- | --- | --- |
| `/pause` | POST | 暂停输入 |
| `/resume` | POST | 恢复输入 |
| `/toggle` | POST | 切换暂停状态 |
| `/status` | GET | 查询暂停、模拟和忙碌状态 |

建议将暂停/恢复捷径放在控制中心或主屏幕。暂停期间头部追踪和串流继续运行，新的输入会被跳过。正在执行的宏将在下一次暂停检查时中止，恢复输入后可触发新动作。服务重启后恢复为启用。

## 4. 自定义配置

### 4.1 config.json

编辑项目目录中的 `config.json`。下面是完整的默认配置结构（请保留首次生成的实际 token）：

```json
{
  "listen": "0.0.0.0",
  "port": 8765,
  "token": "REPLACE_WITH_YOUR_GENERATED_TOKEN",
  "default_cooldown_ms": 400,
  "global_cooldown_ms": 0,
  "restrict_foreground": false,
  "allowed_processes": [],
  "logging": {
    "level": "INFO",
    "max_bytes": 2097152,
    "backup_count": 3
  },
  "mappings": {
    "blink": {"type": "mouse", "button": "left", "cooldown_ms": 250},
    "smile": {"type": "mouse", "button": "right", "cooldown_ms": 500},
    "frown": {"type": "scroll", "steps": 1, "cooldown_ms": 400},
    "mouth": {"type": "scroll", "steps": -1, "cooldown_ms": 500},
    "tongue": {"type": "mouse", "button": "middle", "cooldown_ms": 500}
  }
}
```

| 字段 | 说明 |
| --- | --- |
| `listen` | 监听 IPv4 地址，`0.0.0.0` 表示所有 IPv4 网卡 |
| `port` | TCP 端口，1–65535，默认 `8765` |
| `token` | 访问密钥，16–256 位可打印 ASCII 字符（无空格） |
| `default_cooldown_ms` | 动作默认冷却时间，400 ms |
| `global_cooldown_ms` | 全局冷却时间，默认 0（关闭） |
| `restrict_foreground` | 前台进程白名单开关，默认 `false` |
| `allowed_processes` | 允许的前台进程名称列表 |
| `logging` | 日志级别及轮转设置 |
| `mappings` | 自定义动作映射，最多 128 项 |

`token` 和 `mappings` 为必填字段，其余字段可使用默认值。动作 ID 区分大小写，可由 1–40 位英文字母、数字、下划线或连字符组成。新增 `quick_save` 等动作后，即可通过 `POST /action/quick_save` 调用。

JSON 使用双引号、整数和 `true` / `false`；避免注释、重复字段、未知字段及末尾逗号。文件采用 UTF-8 编码。

### 4.2 动作类型

以下示例可作为 `mappings` 中任意动作的值。

| 类型 | JSON 示例 | 效果 |
| --- | --- | --- |
| `mouse` | `{"type":"mouse","button":"left","count":2}` | 左键双击 |
| `scroll` | `{"type":"scroll","steps":2}` | 向上滚动两格 |
| `key` | `{"type":"key","key":"ENTER"}` | 按 Enter |
| `hotkey` | `{"type":"hotkey","keys":["CTRL","S"]}` | Ctrl+S |
| `wait` | `{"type":"wait","ms":100}` | 等待 100 ms |
| `sequence` | 见下方宏示例 | 依次执行多个动作 |

**鼠标和键盘参数**

- `button`：`left`、`right`、`middle`，默认 `left`。
- `count`：点击次数，1–3，默认 1，连续点击间隔 80 ms。
- `hold_ms`：鼠标或键盘按下至释放的时长，0–2000 ms，默认 45 ms。可适当增加以改善部分游戏的按键兼容性。
- `steps`：滚轮刻度，**正数向上、负数向下**，范围 -10 至 10（除 0）。每格为 Windows 的一个滚轮刻度，实际滚动行数由游戏或系统设置决定。
- `keys`：组合键包含 1–5 个不同按键，按指定顺序按下、逆序释放。

支持的键名（大小写均可）：

- `A`–`Z`、`0`–`9`、`F1`–`F12`
- `ENTER`、`SPACE`、`ESC`、`TAB`、`BACKSPACE`、`DELETE`、`INSERT`
- `LEFT`、`RIGHT`、`UP`、`DOWN`、`HOME`、`END`、`PAGEUP`、`PAGEDOWN`
- `CTRL`、`SHIFT`、`ALT`、`WIN`、`CAPSLOCK`、`PAUSE`
- 别名：`RETURN`、`ESCAPE`、`CONTROL`、`PGUP`、`PGDN`

**宏示例**：在 `mappings` 中加入下列动作，通过 `/action/example_macro` 触发。

```json
"example_macro": {
  "type": "sequence",
  "cooldown_ms": 800,
  "steps": [
    {"type": "key", "key": "ESC"},
    {"type": "wait", "ms": 100},
    {"type": "key", "key": "ENTER"}
  ]
}
```

每组 `sequence` 支持 1–16 项，最多两层子级嵌套；`wait.ms` 为 0–2000（默认 100），宏中等待及按住时间合计最多 10000 ms。宏的各步骤在执行前统一校验。

### 4.3 冷却与动作开关

| 参数 | 说明 |
| --- | --- |
| `cooldown_ms` | 单个动作的冷却时间，优先于 `default_cooldown_ms` |
| `global_cooldown_ms` | 任意动作之间的冷却时间 |
| `enabled` | 单个动作开关，默认 `true` |

冷却时间单位为毫秒，范围 0–60000，从动作成功执行结束后开始计时。三个字段中 `cooldown_ms` 和 `enabled` 用于顶层动作，`global_cooldown_ms` 用于整个配置。

例如临时禁用吐舌，修改 `mappings` 中的对应项：

```json
"tongue": {"type": "mouse", "button": "middle", "enabled": false}
```

张嘴与吐舌容易混淆时，可尝试将全局冷却设为 200–300 ms。服务会跳过冷却中及忙时收到的动作，避免连续翻页指令积压。

### 4.4 前台进程白名单

在「任务管理器 → 详细信息」查看游戏的 exe 文件名，修改以下顶层字段：

```json
"restrict_foreground": true,
"allowed_processes": ["game.exe", "SiglusEngine.exe"]
```

| 开关 | 名单 | 行为 |
| --- | --- | --- |
| `false` | 任意 | 允许当前桌面接收输入 |
| `true` | 非空 | 仅允许指定前台进程 |
| `true` | `[]` | 拒绝全部输入 |

名单填写 exe 文件名（不区分大小写），最多 256 项。白名单会在动作及宏步骤执行前检查前台进程。

**注意：** 鼠标点击仍作用于当前指针所在位置。请在执行宏期间保持游戏前台，避免意外操作其他窗口。

### 4.5 日志设置

```json
"logging": {
  "level": "INFO",
  "max_bytes": 2097152,
  "backup_count": 3
}
```

| 日志级别 | 内容 |
| --- | --- |
| `DEBUG` | 请求结果、冷却与跳过原因 |
| `INFO` | 启停、配置更新、完整动作 JSON、暂停恢复 |
| `WARNING` | 认证失败、未知路由、未配置动作、无效 HTTP 请求及连接过载 |
| `ERROR` | 配置错误、输入执行失败 |
| `CRITICAL` | 启动失败等严重错误 |

默认 `INFO`。前台输出到控制台，后台写入 `logs/facekeys.log`。单个日志达到约 2 MiB 时自动轮转，保留三份历史文件，总占用约 8 MiB；启动器异常记录在 `logs/launcher.log`（256 KiB，保留一份备份）。`max_bytes` 可设为 65536–104857600，`backup_count` 为 1–10。

```text
2026-11-25 08:10:01 INFO [执行] blink => {"type":"mouse","button":"left","cooldown_ms":250}
2026-11-25 08:10:03 INFO [执行] frown => {"type":"scroll","steps":1,"cooldown_ms":400}
2026-11-25 08:10:05 DEBUG [跳过] blink: cooldown
```

### 4.6 配置热更新和命令行

修改映射、冷却时间、密钥、动作开关或白名单后，保存文件即可生效。修改 `listen`、`port`、`logging` 后需要重启服务。配置出现错误时，服务暂停处理请求，修正后自动恢复。

在项目目录执行以下命令。`--check` 可在服务运行时使用，其余启动命令请先停止当前服务。

```powershell
# 检查已有配置
.\.venv\Scripts\python.exe .\facekeys_server.py --check

# 调试日志级别
.\.venv\Scripts\python.exe .\facekeys_server.py --loglevel DEBUG

# 模拟模式
.\.venv\Scripts\python.exe .\facekeys_server.py --dry-run

# 使用其他配置文件
.\.venv\Scripts\python.exe .\facekeys_server.py --config .\config.game.json

# 帮助和版本
.\.venv\Scripts\python.exe .\facekeys_server.py --help
.\.venv\Scripts\python.exe .\facekeys_server.py --version
```

`--loglevel` 优先于文件设置（大小写均可）；`--config` 和 `--check` 可组合使用。检查成功退出码为 0，失败为 1。后台计划任务默认使用 `config.json`。暂停和冷却状态在重启时清空。

### 4.7 HTTP 接口速查

所有接口均使用 `X-Api-Key` 请求头。POST 请求可使用空正文或 `{}`。

| 方法 | 路径 | 成功响应 |
| --- | --- | --- |
| GET | `/health` | `200`，`{"status":"ok"}` |
| GET | `/status` | `200`，包含 `paused`、`dry_run`、`busy` |
| POST | `/action/<id>` | `204`；模拟模式为 `200 simulated` |
| POST | `/pause` | `200`，`paused: true` |
| POST | `/resume` | `200`，`paused: false` |
| POST | `/toggle` | `200`，返回切换后的 `paused` |

| 返回码 | 含义 |
| --- | --- |
| `202` | 已跳过：暂停、禁用、冷却、忙碌或白名单限制，见响应 `status` |
| `400` / `413` | 请求格式错误 / 正文超过 4096 字节 |
| `403` | 密钥错误 |
| `404` | 路径或动作不存在 |
| `500` | 动作执行失败 |
| `503` | 配置错误 |

## 5. 注意事项与使用技巧

### 5.1 网络安全

VN FaceKeys 可以操作 Windows 桌面的鼠标和键盘，请妥善保管访问密钥。

- 仅在可信局域网或受控 VPN 中使用，通过防火墙限制访问来源。
- **不要将服务端口暴露到公网，也不要在公共 Wi-Fi 上直接使用未加密的 HTTP。**
- 使用随机生成的 token，避免公开包含密钥的配置文件、捷径或截图。密钥泄露后，可使用以下命令生成新密钥，并同步更新 iPad 捷径：

  ```powershell
  .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
  ```

- 离开 VN 时暂停输入或关闭头部追踪；需要时启用前台进程白名单。
- 建议 VN 与本程序均以普通用户权限运行。Windows 锁屏、安全桌面或更高权限的游戏窗口可能拒绝模拟输入。

### 5.2 串流软件推荐：VoidLink

推荐 [VoidLink（App Store）](https://apps.apple.com/app/voidlink/id6747717070)（[项目主页](https://github.com/waruhachi/VoidLink)），搭配 [Sunshine](https://github.com/LizardByte/Sunshine) 等兼容串流主机软件。VN FaceKeys 可与串流同时使用，也适用于其他支持此快捷指令操作方式的客户端。

### 5.3 一键开关头部追踪

1. 在快捷指令中新建 `VN FaceKeys - Tracking Toggle`。
2. 添加「设置辅助触控（Set AssistiveTouch）」操作，将参数设为「切换（Toggle）」。
3. 将捷径添加到控制中心、主屏幕或小组件。
4. 测试关闭辅助触控时追踪是否停止，重新打开时是否恢复。

此方法的效果随 iPadOS 版本而异，并会影响其他辅助触控功能。也可直接在「设置 → 辅助功能 → 头部追踪」切换，或在「辅助功能快捷键」中选择可用的相关功能，通过连按三次顶部按钮控制。

### 5.4 调整表情灵敏度

进入「设置 → 辅助功能 → 头部追踪 → 操作」，选择具体表情，调整灵敏度（轻微 / 默认 / 夸张，英文 Slight / Default / Exaggerated）。

- 眨眼建议先尝试「轻微」，部分设备仍需刻意眨眼才能触发；自然眨眼的识别取决于 iPadOS。
- 张嘴与吐舌容易混淆时，可调整灵敏度、设置短全局冷却，或禁用其中一个动作。
- 保持面部光照均匀、摄像头无遮挡，尝试约 45 cm 的使用距离。
- 使用 `--dry-run --loglevel DEBUG` 查看实际识别并发送到电脑的动作。

### 5.5 减少指针和悬浮按钮干扰

| 设置路径 | 推荐调整 |
| --- | --- |
| 辅助功能 → 头部追踪 → 吸附到项目（Snap to Item） | 关闭，避免指针自动跳向控件 |
| 辅助功能 → 头部追踪 → 停留控制（Dwell Control） | 关闭，避免停留时自动点击 |
| 辅助功能 → 触控 → 辅助触控 → 始终显示菜单（Always Show Menu） | 尝试关闭悬浮按钮，或降低闲置时不透明度 |
| 辅助功能 → 指针控制 | 如可用，缩小指针并启用自动隐藏 |

跟随头部移动的圆形指针能否完全隐藏，取决于系统版本和设备状态。参考 [Apple：辅助触控](https://support.apple.com/guide/ipad/ipad9a2466d3/ipados)。

### 5.6 常见问题

| 现象 | 解决方法 |
| --- | --- |
| Python 启动失败 | 检查 `.venv` 与基础 Python，运行 `--check` 查看配置错误 |
| 端口已占用 | 停止其他实例或旧计划任务；运行 `Get-NetTCPConnection -LocalPort 8765 -State Listen` |
| 电脑测试成功，iPad 连接失败 | 检查 IP、端口、防火墙、VPN、Wi-Fi 隔离和局域网权限 |
| `403` / `404` | 核对密钥 / URL 路径和动作 ID（当前版本使用 `/action/`） |
| `503` | 查看日志，修正配置文件 |
| `202` / 翻页偶尔被跳过 | 查看响应 `status` 或 DEBUG 日志，检查暂停、冷却、白名单及忙碌状态 |
| 日志显示执行，游戏无反应 | 确认游戏前台、鼠标位置、游戏按键绑定、运行权限；尝试增大 `hold_ms` |
| 手动捷径成功，表情无反应 | 检查头部追踪绑定和灵敏度，用模拟模式测试 |
| 后台启动失败 | 运行 `Get-ScheduledTaskInfo -TaskName 'VN FaceKeys'`，查看 `logs/facekeys.log` 和 `logs/launcher.log` |

### 5.7 从旧版升级

1. 停止旧版前台进程或卸载旧版计划任务，备份 `config.json`。
2. 解压新版，按第 2 节准备环境，复制原有配置以保留密钥及映射。
3. 如曾使用名为 `FaceKeysVN` 的旧任务，先删除该任务（仅在存在时执行）：

   ```powershell
   Stop-ScheduledTask -TaskName 'FaceKeysVN'
   Unregister-ScheduledTask -TaskName 'FaceKeysVN' -Confirm:$false
   ```
4. 运行 `--check` 并完成前台测试，再按需安装后台任务。

旧版滚轮方向保持正上负下。首次生成的新版配置包含五种默认动作，已有配置可按 4.1 节手动更新。

### 5.8 自动化测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

测试使用模拟键鼠接口和本地 HTTP 连接。Windows 实际输入、计划任务及 iPad 串流联动请按安装指南完成设备测试。
