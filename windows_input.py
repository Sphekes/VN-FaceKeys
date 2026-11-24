"""Windows input adapter; Win32 DLLs are loaded only on construction."""
import ctypes
import os
from ctypes import wintypes

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



class WindowsInput:
    def __init__(self):
        if os.name != "nt":
            raise OSError("实际键鼠输入需要 Windows；可使用 --dry-run 测试。")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
        self.user32.SendInput.restype = wintypes.UINT
        self.user32.GetForegroundWindow.argtypes = ()
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
        self.user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        self.kernel32.OpenProcess.restype = wintypes.HANDLE
        self.kernel32.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
        self.kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self.kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.kernel32.CloseHandle.restype = wintypes.BOOL

    def send(self, event):
        ctypes.set_last_error(0)
        if self.user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT)) != 1:
            raise OSError(ctypes.get_last_error(), "SendInput 失败；检查桌面会话、权限或 UIPI")

    def key(self, key, up=False):
        name = key.upper()
        extended = 0x0001 if VK[name] in (0x21,0x22,0x23,0x24,0x25,0x26,0x27,0x28,0x2D,0x2E,0x5B) else 0
        self.send(INPUT(type=1, data=INPUT_UNION(ki=KEYBDINPUT(wVk=VK[name], dwFlags=extended | (KEYUP if up else 0)))))

    def mouse(self, button, up=False):
        self.send(INPUT(type=0, data=INPUT_UNION(mi=MOUSEINPUT(dwFlags=MOUSE_FLAGS[button][int(up)]))))

    def scroll(self, steps):
        self.send(INPUT(type=0, data=INPUT_UNION(mi=MOUSEINPUT(dwFlags=0x0800, mouseData=ctypes.c_uint32(steps * 120).value))))

    def foreground(self):
        hwnd = self.user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        if not self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)):
            return None
        handle = self.kernel32.OpenProcess(0x1000, False, pid.value)
        if not handle:
            return None
        try:
            buf = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buf))
            if not self.kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return None
            if self.user32.GetForegroundWindow() != hwnd:
                return None
            return os.path.basename(buf.value)
        finally:
            self.kernel32.CloseHandle(handle)
