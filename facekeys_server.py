"""VN FaceKeys — configurable HTTP to Windows input bridge, standard library only."""
from __future__ import annotations

import argparse
import contextlib
import ipaddress
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import secrets
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from windows_input import VK, MOUSE_FLAGS, WindowsInput

VERSION = "0.2.0"
ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "config.json"
LOG = logging.getLogger("vn-facekeys")
LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
ACTION_ID = re.compile(r"[a-zA-Z0-9_-]{1,40}")
DEFAULT_LOGGING = {"level": "INFO", "max_bytes": 2 * 1024 * 1024, "backup_count": 3}
MAX_CONFIG = 256 * 1024
MAX_BODY = 4096


def starter_config():
    return {
        "listen": "0.0.0.0", "port": 8765, "token": secrets.token_urlsafe(32),
        "default_cooldown_ms": 400, "global_cooldown_ms": 0,
        "restrict_foreground": False, "allowed_processes": [],
        "logging": dict(DEFAULT_LOGGING),
        "mappings": {
            "blink": {"type": "mouse", "button": "left", "cooldown_ms": 250},
            "smile": {"type": "mouse", "button": "right", "cooldown_ms": 500},
            "frown": {"type": "scroll", "steps": 1, "cooldown_ms": 400},
            "mouth": {"type": "scroll", "steps": -1, "cooldown_ms": 500},
            "tongue": {"type": "mouse", "button": "middle", "cooldown_ms": 500},
        },
    }


def fail(path, msg):
    raise ValueError(f"{path}: {msg}")


def integer(v, low, high, path):
    if type(v) is not int or not low <= v <= high:
        fail(path, f"需要 {low}~{high} 的整数")
    return v


def boolean(v, path):
    if type(v) is not bool:
        fail(path, "需要 true 或 false")


def fields(v, allowed, path):
    if not isinstance(v, dict):
        fail(path, "需要 JSON 对象")
    if set(v) - set(allowed):
        fail(path, "包含未知字段（检查拼写）")


def validate_action(spec, path, depth=0):
    """Validate every step before input; return conservative maximum duration (ms)."""
    if depth > 2 or not isinstance(spec, dict):
        fail(path, "动作须为对象；宏最多嵌套两层")
    kind = spec.get("type")
    common = {"type", "enabled", "cooldown_ms"} if depth == 0 else {"type"}
    if depth == 0:
        boolean(spec.get("enabled", True), path + ".enabled")
        integer(spec.get("cooldown_ms", 400), 0, 60000, path + ".cooldown_ms")
    if kind in ("key", "hotkey"):
        fields(spec, common | {"key" if kind == "key" else "keys", "hold_ms"}, path)
        keys = [spec.get("key")] if kind == "key" else spec.get("keys")
        if not isinstance(keys, list) or not 1 <= len(keys) <= 5:
            fail(path, "需要 1~5 个按键")
        if any(not isinstance(k, str) or k.upper() not in VK for k in keys):
            fail(path, "包含不支持的按键")
        if len({VK[k.upper()] for k in keys}) != len(keys):
            fail(path, "组合键不能重复")
        duration = integer(spec.get("hold_ms", 45), 0, 2000, path + ".hold_ms")
    elif kind == "mouse":
        fields(spec, common | {"button", "count", "hold_ms"}, path)
        if spec.get("button", "left") not in ("left", "right", "middle"):
            fail(path + ".button", "仅支持 left/right/middle")
        count = integer(spec.get("count", 1), 1, 3, path + ".count")
        hold = integer(spec.get("hold_ms", 45), 0, 2000, path + ".hold_ms")
        duration = count * hold + (count - 1) * 80
    elif kind == "scroll":
        fields(spec, common | {"steps"}, path)
        if integer(spec.get("steps"), -10, 10, path + ".steps") == 0:
            fail(path + ".steps", "不能为 0")
        duration = 0
    elif kind == "wait":
        fields(spec, common | {"ms"}, path)
        duration = integer(spec.get("ms", 100), 0, 2000, path + ".ms")
    elif kind == "sequence":
        fields(spec, common | {"steps"}, path)
        steps = spec.get("steps")
        if not isinstance(steps, list) or not 1 <= len(steps) <= 16:
            fail(path + ".steps", "需要 1~16 个动作")
        duration = sum(validate_action(s, f"{path}.steps[{i}]", depth + 1) for i, s in enumerate(steps))
        if duration > 10000:
            fail(path, "宏的总等待与按住时间不能超过 10000ms")
    else:
        fail(path + ".type", "未知动作类型")
    return duration


def validate_config(raw):
    fields(raw, {"listen", "port", "token", "default_cooldown_ms", "global_cooldown_ms", "restrict_foreground", "allowed_processes", "logging", "mappings"}, "config")
    cfg = dict(raw)
    for name, value in {"listen": "0.0.0.0", "port": 8765, "default_cooldown_ms": 400, "global_cooldown_ms": 0, "restrict_foreground": False, "allowed_processes": []}.items():
        cfg.setdefault(name, value)
    try:
        ipaddress.IPv4Address(cfg["listen"])
        if not isinstance(cfg["listen"], str):
            raise ValueError
    except (ValueError, TypeError):
        fail("listen", "需要 IPv4 地址（如 0.0.0.0 或 127.0.0.1）")
    integer(cfg["port"], 1, 65535, "port")
    token = cfg.get("token")
    if not isinstance(token, str) or not re.fullmatch(r"[!-~]{16,256}", token):
        fail("token", "需要 16~256 位可打印 ASCII 字符，不含空格")
    for k in ("default_cooldown_ms", "global_cooldown_ms"):
        integer(cfg[k], 0, 60000, k)
    boolean(cfg["restrict_foreground"], "restrict_foreground")
    processes = cfg["allowed_processes"]
    if not isinstance(processes, list) or len(processes) > 256 or any(not isinstance(p, str) or not p.lower().endswith(".exe") or not p.strip() == p or any(c in p for c in '\\/:*?"<>|') or any(ord(c)<32 for c in p) for p in processes):
        fail("allowed_processes", "需要可执行文件名列表，如 game.exe（不是路径）")
    log_cfg = cfg.get("logging", {})
    fields(log_cfg, DEFAULT_LOGGING, "logging")
    cfg["logging"] = {**DEFAULT_LOGGING, **log_cfg}
    if cfg["logging"]["level"] not in LEVELS:
        fail("logging.level", "需要 DEBUG/INFO/WARNING/ERROR/CRITICAL")
    integer(cfg["logging"]["max_bytes"], 65536, 100*1024*1024, "logging.max_bytes")
    integer(cfg["logging"]["backup_count"], 1, 10, "logging.backup_count")
    mappings = cfg.get("mappings")
    if not isinstance(mappings, dict) or len(mappings) > 128:
        fail("mappings", "需要 JSON 对象，最多 128 个动作")
    for name, spec in mappings.items():
        if not ACTION_ID.fullmatch(name):
            fail("mappings", "动作 ID 只能包含 1~40 位英文字母、数字、下划线或连字符")
        validate_action(spec, "mappings." + name)
    return cfg


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("JSON 包含重复字段")
        obj[key] = value
    return obj


def read_config_bytes(path):
    with path.open("rb") as f:
        data = f.read(MAX_CONFIG + 1)
    if len(data) > MAX_CONFIG:
        raise ValueError("配置文件超过 256 KiB")
    return data


def parse_config(data):
    return validate_config(json.loads(data.decode("utf-8-sig"), object_pairs_hook=unique_object))


def ensure_config(path):
    try:
        with path.open("x", encoding="utf-8") as f:
            json.dump(starter_config(), f, ensure_ascii=False, indent=2)
            f.write("\n")
    except FileExistsError:
        pass


class ConfigStore:
    def __init__(self, path):
        self.path = path
        self.raw = read_config_bytes(path)
        self.data = parse_config(self.raw)
        self.error = None
        self.startup = (self.data["listen"], self.data["port"], self.data["logging"])

    def get(self):
        try:
            raw = read_config_bytes(self.path)
            if raw != self.raw:
                cfg = parse_config(raw)
                self.raw, self.data = raw, cfg
                LOG.info("[配置更新] 已重新载入")
                if (cfg["listen"], cfg["port"], cfg["logging"]) != self.startup:
                    LOG.warning("监听地址、端口或日志设置变化；重启后生效")
            if self.error is not None:
                LOG.info("[配置恢复] 已恢复处理请求")
            self.error = None
            return self.data
        except (OSError, ValueError, RecursionError, TypeError) as exc:
            # Never fall back to an old credential or mapping while config is invalid.
            error = str(exc)
            if error != self.error:
                LOG.error("[配置错误] %s", error)
            self.error = error
            raise ValueError("configuration error") from None


def setup_logging(background=False, cfg=None, override=None):
    cfg = cfg or DEFAULT_LOGGING
    for handler in list(LOG.handlers):
        LOG.removeHandler(handler)
        handler.close()
    LOG.propagate = False
    LOG.setLevel(override or cfg["level"])
    if background:
        folder = ROOT / "logs"
        folder.mkdir(exist_ok=True)
        handler = RotatingFileHandler(folder / "facekeys.log", maxBytes=cfg["max_bytes"], backupCount=cfg["backup_count"], encoding="utf-8", delay=True)
    else:
        handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    LOG.addHandler(handler)


@contextlib.contextmanager
def instance_lock(path):
    """OS-released per-project lock; no stale PID files. Windows only in production."""
    lock_path = path.with_name(path.name + ".lock")
    with lock_path.open("a+b") as f:
        if os.name == "nt":
            import msvcrt
            f.seek(0, 2)
            if f.tell() == 0:
                f.write(b"0")
                f.flush()
            f.seek(0)
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise RuntimeError("同一项目目录的 VN FaceKeys 已在运行") from None
        else:
            import fcntl
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise RuntimeError("同一项目目录的 VN FaceKeys 已在运行") from None
        yield  # closing releases lock even after exceptions


class Blocked(Exception):
    pass


def execute(spec, backend, guard=lambda: None, sleep=time.sleep):
    """Call only with fully validated spec. Release every successfully held key on failure."""
    kind = spec["type"]
    guard()
    if kind in ("key", "hotkey", "mouse"):
        if kind == "mouse":
            keys = [spec.get("button", "left")]
            emit = backend.mouse
            count = spec.get("count", 1)
        else:
            keys = [spec["key"]] if kind == "key" else spec["keys"]
            emit = backend.key
            count = 1
        for i in range(count):
            pressed = []
            try:
                guard()
                for key in keys:
                    guard()
                    emit(key)
                    pressed.append(key)
                sleep(spec.get("hold_ms", 45) / 1000)
            finally:
                release_error = None
                for key in reversed(pressed):
                    try:
                        emit(key, up=True)
                    except Exception as exc:
                        LOG.error("[释放失败] %s", key)
                        release_error = exc
                if release_error is not None:
                    raise release_error
            if i + 1 < count:
                sleep(0.08)
    elif kind == "scroll":
        backend.scroll(spec["steps"])
    elif kind == "wait":
        sleep(spec.get("ms", 100) / 1000)
    elif kind == "sequence":
        for step in spec["steps"]:
            execute(step, backend, guard, sleep)


class State:
    def __init__(self, store, backend, dry_run=False, clock=time.monotonic):
        self.store, self.backend, self.dry_run, self.clock = store, backend, dry_run, clock
        self.lock = threading.Lock()
        self.input_lock = threading.Lock()
        self.paused = False
        self.last_fire = {}
        self.last_global = float("-inf")

    def response(self, method, path, token):
        # Config + state changes are serialized, but never hold the state lock during a macro.
        with self.lock:
            try:
                cfg = self.store.get()
            except ValueError:
                return 503, {"status": "configuration_error"}
            if not secrets.compare_digest(token.encode("utf-8"), cfg["token"].encode("ascii")):
                LOG.warning("[认证失败]")
                return 403, {"status": "forbidden"}
            if method == "GET" and path == "/health":
                return 200, {"status": "ok"}
            if method == "GET" and path == "/status":
                return 200, {"status": "ok", "paused": self.paused, "dry_run": self.dry_run, "busy": self.input_lock.locked()}
            if method == "POST" and path in ("/pause", "/resume", "/toggle"):
                self.paused = not self.paused if path == "/toggle" else path == "/pause"
                LOG.info("[控制] paused=%s", self.paused)
                return 200, {"status": "ok", "paused": self.paused}
            match = re.fullmatch(r"/action/([a-zA-Z0-9_-]{1,40})", path) if method == "POST" else None
            if not match:
                return 404, {"status": "not_found"}
            name = match.group(1)
            spec = cfg["mappings"].get(name)
            if spec is None:
                LOG.warning("[未配置] %s", name)
                return 404, {"status": "unmapped"}
            full = json.dumps(spec, ensure_ascii=False, separators=(",", ":"))
            if self.dry_run:
                LOG.info("[收到/模拟模式] %s => %s", name, full)
            def skip(reason):
                LOG.log(logging.INFO if self.dry_run else logging.DEBUG, "[跳过] %s: %s", name, reason)
                return 202, {"status": reason}
            if self.paused:
                return skip("paused")
            if not spec.get("enabled", True):
                return skip("disabled")
            now = self.clock()
            self.last_fire = {k: v for k, v in self.last_fire.items() if k in cfg["mappings"]}
            if now - self.last_fire.get(name, float("-inf")) < spec.get("cooldown_ms", cfg["default_cooldown_ms"]) / 1000:
                return skip("cooldown")
            if now - self.last_global < cfg["global_cooldown_ms"] / 1000:
                return skip("global_cooldown")
            if not self.input_lock.acquire(blocking=False):
                return skip("busy")  # no stale queued clicks
        def guard():
            with self.lock:
                if self.paused:
                    raise Blocked("paused")
            if cfg["restrict_foreground"]:
                process = self.backend.foreground() if self.backend is not None else None
                if process is None or process.casefold() not in {p.casefold() for p in cfg["allowed_processes"]}:
                    raise Blocked("foreground_blocked")
        try:
            guard()
            if not self.dry_run:
                execute(spec, self.backend, guard)
            with self.lock:
                self.last_fire[name] = self.last_global = self.clock()
            LOG.info("[%s] %s => %s", "模拟" if self.dry_run else "执行", name, full)
            return (200, {"status": "simulated"}) if self.dry_run else (204, None)
        except Blocked as exc:
            return skip(str(exc))
        except Exception:
            LOG.exception("[动作错误] %s", name)
            return 500, {"status": "action_failed"}
        finally:
            self.input_lock.release()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def setup(self):
        self.request.settimeout(3)
        super().setup()

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def dispatch(self, method):
        try:
            if len(self.path) > 128 or self.headers.get("Transfer-Encoding") is not None:
                return self.reply(400, {"status": "invalid_request"})
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) > 1 or (lengths and not re.fullmatch(r"[0-9]{1,8}", lengths[0])):
                return self.reply(400, {"status": "invalid_length"})
            n = int(lengths[0]) if lengths else 0
            if n > MAX_BODY:
                return self.reply(413, {"status": "body_too_large"})
            if n and len(self.rfile.read(n)) != n:
                return self.reply(400, {"status": "incomplete_body"})
            tokens = self.headers.get_all("X-Api-Key", [])
            token = tokens[0] if len(tokens) == 1 else ""
            code, body = self.server.state.response(method, self.path, token)
            self.reply(code, body)
        except (OSError, TimeoutError):
            LOG.debug("[HTTP] 连接中断或超时")

    def reply(self, code, obj):
        body = b"" if obj is None else json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        if body:
            self.wfile.write(body)
        self.close_connection = True
        LOG.debug("[HTTP] %s %s %s", self.client_address[0], self.command, code)

    def log_message(self, fmt, *args):
        # Do not echo raw request paths or headers (may contain secrets).
        pass


class Server(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True
    allow_reuse_address = False
    request_queue_size = 16

    def __init__(self, address, state):
        self.state = state
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(address, Handler)

    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        LOG.exception("[HTTP] 请求处理异常，来源 %s", client_address[0])


def main(argv=None, background=False):
    parser = argparse.ArgumentParser(description="VN FaceKeys — Windows 键鼠映射服务")
    parser.add_argument("--config", type=Path, default=CONFIG_FILE, help="配置文件路径")
    parser.add_argument("--check", action="store_true", help="只校验配置，不监听端口或注入输入")
    parser.add_argument("--dry-run", action="store_true", help="模拟模式，只记录动作")
    parser.add_argument("--loglevel", type=str.upper, choices=LEVELS, help="覆盖本次运行日志级别")
    parser.add_argument("--version", action="version", version=f"VN FaceKeys {VERSION}")
    args = parser.parse_args(argv)
    path = args.config.resolve()
    setup_logging(background, override=args.loglevel)
    try:
        if args.check:
            cfg = parse_config(read_config_bytes(path))
            # Always print check result independently of log level.
            if not background:
                print(f"配置有效：{path}（{len(cfg['mappings'])} 个动作）")
            return 0
        with instance_lock(ROOT / ".vn-facekeys"):
            ensure_config(path)
            store = ConfigStore(path)
            cfg = store.data
            setup_logging(background, cfg["logging"], args.loglevel)
            backend = WindowsInput() if os.name == "nt" or not args.dry_run else None
            state = State(store, backend, args.dry_run)
            with Server((cfg["listen"], cfg["port"]), state) as server:
                LOG.info("VN FaceKeys %s 已启动，监听 %s:%s，dry_run=%s", VERSION, *server.server_address, args.dry_run)
                LOG.info("配置：%s；仅限可信网络", path)
                try:
                    server.serve_forever(poll_interval=0.25)
                except KeyboardInterrupt:
                    pass
                finally:
                    with state.lock:
                        state.paused = True
            LOG.info("VN FaceKeys 已停止")
        return 0
    except Exception:
        # Startup errors must be visible even with --loglevel CRITICAL.
        LOG.critical("启动或配置检查失败", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
