"""FaceKeys VN: HTTP facial-gesture -> Windows keyboard/mouse mapper.

Requirements: Windows 10/11 + Python 3.10+. No third-party packages.
Start: python facekeys_server.py
Edit config.json to change mappings; changes reload automatically.
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import secrets
import threading
import time
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

if os.name != "nt":
    raise SystemExit("此服务端需要在 Windows 串流主机上运行。")

CONFIG_FILE = Path(__file__).with_name("config.json")
ACTION_RE = re.compile(r"^/press/([a-zA-Z0-9_-]{1,40})$")
STATE_LOCK = threading.RLock()
LAST_FIRE: dict[str, float] = {}

# Windows SendInput data structures (work on both x86 and x64).
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG), ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR),
    ]

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]

class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("data", INPUT_UNION)]

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT

KEYUP = 0x0002
MOUSE_FLAGS = {
    "left": (0x0002, 0x0004),
    "right": (0x0008, 0x0010),
    "middle": (0x0020, 0x0040),
}
VK = {
    "BACKSPACE": 0x08, "TAB": 0x09, "ENTER": 0x0D, "SHIFT": 0x10,
    "CTRL": 0x11, "ALT": 0x12, "PAUSE": 0x13, "CAPSLOCK": 0x14,
    "ESC": 0x1B, "SPACE": 0x20, "PAGEUP": 0x21, "PAGEDOWN": 0x22,
    "END": 0x23, "HOME": 0x24, "LEFT": 0x25, "UP": 0x26,
    "RIGHT": 0x27, "DOWN": 0x28, "INSERT": 0x2D, "DELETE": 0x2E,
    "WIN": 0x5B,
}
VK.update({chr(k): k for k in range(ord("A"), ord("Z") + 1)})
VK.update({str(i): ord("0") + i for i in range(10)})
VK.update({f"F{i}": 0x6F + i for i in range(1, 13)})
VK.update({"RETURN": VK["ENTER"], "ESCAPE": VK["ESC"],
           "CONTROL": VK["CTRL"], "PGUP": VK["PAGEUP"],
           "PGDN": VK["PAGEDOWN"]})


def send_input(event: INPUT) -> None:
    if user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT)) != 1:
        err = ctypes.get_last_error()
        raise OSError(err, "Windows SendInput 未能注入按键（检查游戏是否管理员运行）")


def key_event(key: str, up: bool = False) -> None:
    name = str(key).upper()
    if name not in VK:
        raise ValueError(f"不支持的按键：{key}（可使用 A-Z、0-9、F1-F12、方向键等）")
    event = INPUT(type=1, data=INPUT_UNION(ki=KEYBDINPUT(
        wVk=VK[name], wScan=0, dwFlags=KEYUP if up else 0,
        time=0, dwExtraInfo=0,
    )))
    send_input(event)


def mouse_event(flags: int, wheel_delta: int = 0) -> None:
    event = INPUT(type=0, data=INPUT_UNION(mi=MOUSEINPUT(
        dx=0, dy=0, mouseData=ctypes.c_uint32(wheel_delta).value,
        dwFlags=flags, time=0, dwExtraInfo=0,
    )))
    send_input(event)


def whole_ms(value: object, default: int, low: int, high: int) -> int:
    n = int(default if value is None else value)
    if not low <= n <= high:
        raise ValueError(f"时间必须在 {low}~{high} 毫秒之间")
    return n


def execute(spec: dict, depth: int = 0) -> None:
    if depth > 2 or not isinstance(spec, dict):
        raise ValueError("无效动作或宏嵌套过深")
    kind = spec.get("type")

    if kind in ("key", "hotkey"):
        keys = [spec["key"]] if kind == "key" else spec["keys"]
        if not isinstance(keys, list) or not 1 <= len(keys) <= 5:
            raise ValueError("hotkey 的 keys 需要包含 1 到 5 个按键")
        # Validate *before* pressing to avoid leaving modifiers held down.
        for key in keys:
            if str(key).upper() not in VK:
                raise ValueError(f"不支持的按键：{key}")
        hold = whole_ms(spec.get("hold_ms"), 45, 20, 2000)
        down = []
        try:
            for key in keys:
                key_event(key)
                down.append(key)
            time.sleep(hold / 1000)
        finally:
            for key in reversed(down):
                key_event(key, up=True)

    elif kind == "mouse":
        button = str(spec.get("button", "left")).lower()
        if button not in MOUSE_FLAGS:
            raise ValueError("鼠标按钮仅支持 left/right/middle")
        count = int(spec.get("count", 1))
        if not 1 <= count <= 3:
            raise ValueError("count 必须在 1~3 之间")
        hold = whole_ms(spec.get("hold_ms"), 45, 20, 2000)
        for i in range(count):
            press, release = MOUSE_FLAGS[button]
            mouse_event(press)
            try:
                time.sleep(hold / 1000)
            finally:
                mouse_event(release)
            if i + 1 < count:
                time.sleep(0.08)

    elif kind == "scroll":
        amount = int(spec["steps"])
        if not -10 <= amount <= 10:
            raise ValueError("滚轮 steps 必须在 -10~10 之间")
        mouse_event(0x0800, amount * 120)  # positive=up; negative=down

    elif kind == "wait":
        ms = whole_ms(spec.get("ms"), 100, 0, 2000)
        time.sleep(ms / 1000)

    elif kind == "sequence":
        steps = spec.get("steps")
        if not isinstance(steps, list) or not 1 <= len(steps) <= 16:
            raise ValueError("sequence 最多允许 16 个步骤")
        for step in steps:
            execute(step, depth + 1)

    else:
        raise ValueError(f"未知动作类型：{kind}")


def starter_config() -> dict:
    return {
        "listen": "0.0.0.0", "port": 8765,
        "token": secrets.token_urlsafe(32),
        "default_cooldown_ms": 550,
        "mappings": {
            "blink": {"type": "mouse", "button": "left", "cooldown_ms": 650},
            "smile": {"type": "key", "key": "SPACE", "cooldown_ms": 900},
            "tongue": {"type": "scroll", "steps": 1, "cooldown_ms": 650},
            "brow": {"type": "key", "key": "ENTER", "cooldown_ms": 600},
            "mouth": {"type": "mouse", "button": "right", "cooldown_ms": 700},
            "nose": {"type": "hotkey", "keys": ["CTRL", "S"], "cooldown_ms": 1300},
            "backlog_down": {"type": "scroll", "steps": -1},
            "double_click": {"type": "mouse", "button": "left", "count": 2},
            "sample_macro": {"type": "sequence", "steps": [
                {"type": "key", "key": "ESC"},
                {"type": "wait", "ms": 100},
                {"type": "key", "key": "ENTER"}
            ]}
        }
    }


def load_config() -> dict:
    result = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    if (not isinstance(result, dict) or not isinstance(result.get("token"), str)
            or len(result["token"]) < 16 or not isinstance(result.get("mappings"), dict)):
        raise ValueError("config.json 缺少 token（至少16位）或 mappings")
    return result

class ConfigStore:
    def __init__(self):
        self.data = load_config()
        self.mtime = CONFIG_FILE.stat().st_mtime_ns

    def get(self):
        mtime = CONFIG_FILE.stat().st_mtime_ns
        if mtime != self.mtime:
            new_data = load_config()  # if edit is invalid, keep the old config
            self.data = new_data
            self.mtime = mtime
            print("[配置已更新]", flush=True)
        return self.data

STORE = None

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        match = ACTION_RE.fullmatch(self.path)
        if not match:
            return self.reply(404, "unknown path")
        action_name = match.group(1)
        with STATE_LOCK:
            try:
                config = STORE.get()
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                print(f"[配置错误] {exc}", flush=True)
                return self.reply(500, "configuration error")
            supplied = self.headers.get("X-Api-Key", "")
            if not secrets.compare_digest(supplied, config["token"]):
                return self.reply(403, "invalid token")
            spec = config["mappings"].get(action_name)
            if spec is None:
                return self.reply(404, "unmapped action")
            if not isinstance(spec, dict):
                return self.reply(400, "invalid mapping")
            try:
                cooldown = whole_ms(spec.get("cooldown_ms"),
                                    config.get("default_cooldown_ms", 550), 0, 60000)
                now = time.monotonic()
                if now - LAST_FIRE.get(action_name, float("-inf")) < cooldown / 1000:
                    return self.reply(202, "cooldown")
                execute(spec)
                LAST_FIRE[action_name] = time.monotonic()
                print(f"[执行] {action_name} => {spec.get('type')}", flush=True)
            except (ValueError, KeyError, TypeError, OSError) as exc:
                print(f"[动作错误] {action_name}: {exc}", flush=True)
                return self.reply(400, "action failed - see server log")
        return self.reply(204)

    def do_GET(self):
        self.reply(405, "POST only")

    def reply(self, code, message=""):
        body = message.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, fmt, *args):
        # Only action IDs appear in access log; the API token is in a header.
        print(f"[HTTP] {self.address_string()} {fmt % args}", flush=True)


def main():
    global STORE
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(
            json.dumps(starter_config(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"已生成默认配置：{CONFIG_FILE}")
    STORE = ConfigStore()
    cfg = STORE.data
    host = str(cfg.get("listen", "0.0.0.0"))
    port = int(cfg.get("port", 8765))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"FaceKeys 已启动： http://{host}:{port}/press/blink")
    print(f"配置文件：{CONFIG_FILE}")
    print("编辑 mappings 可以实时更新映射；修改 listen/port 需要重启。")
    print("按 Ctrl+C 停止；仅限可信局域网，切勿向公网开放此端口。")
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("服务已停止。")
    finally:
        server.server_close()

if __name__ == "__main__":
    main()
