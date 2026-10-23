"""Drive HP's Prime Virtual Calculator from a script (Windows only).

Development aid: launch the emulator, type keys into it and screenshot its
window, so calculator code can be exercised without a person at the keyboard.

    python emudrive.py launch
    python emudrive.py keys "CVTEST()" ENTER
    python emudrive.py shot out.png
    python emudrive.py close

Key tokens: plain text is typed character by character; the upper-case words
in SPECIAL (ENTER, ESC, F1...) press that one key.
"""
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

EXE = r"C:\Program Files\HP\HP Prime Virtual Calculator\HPPrime.exe"
PROCESS = "HPPrime.exe"

user32 = ctypes.WinDLL("user32", use_last_error=True)
# Physical pixels everywhere, so window rectangles, screenshots and click
# coordinates agree on a scaled display.
try:
    ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
except OSError:
    pass

SPECIAL = {
    "ENTER": 0x0D, "ESC": 0x1B, "BACK": 0x08, "TAB": 0x09, "DEL": 0x2E,
    "UP": 0x26, "DOWN": 0x28, "LEFT": 0x25, "RIGHT": 0x27, "HOME": 0x24,
    "END": 0x23, "SHIFT": 0x10, "CTRL": 0x11, "ALT": 0x12,
    "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73, "F5": 0x74, "F6": 0x75,
    "F7": 0x76, "F8": 0x77, "F9": 0x78, "F10": 0x79, "F11": 0x7A, "F12": 0x7B,
    "PGUP": 0x21, "PGDN": 0x22,
}


def find_window():
    """Top-level visible window of the emulator process, or None."""
    pids = running()
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and user32.IsWindowVisible(hwnd):
            r = wt.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            if r.right - r.left > 200:
                found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def focus():
    """The emulator's window handle. Nothing here steals focus: keys and
    clicks are posted to this window directly, so they can never land in
    whatever other window the user has in front."""
    hwnd = find_window()
    if not hwnd:
        raise SystemExit("emulator window not found")
    return hwnd


def running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq " + PROCESS, "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout
    pids = []
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[0].lower() == PROCESS.lower():
            pids.append(int(parts[1]))
    return pids


def launch():
    if not running():
        subprocess.Popen([EXE], cwd=os.path.dirname(EXE))
    for _ in range(60):
        if find_window():
            time.sleep(2.0)
            return
        time.sleep(0.5)
    raise SystemExit("emulator did not open")


def close(timeout=20):
    if not running():
        return
    subprocess.run(["taskkill", "/IM", PROCESS], capture_output=True)
    end = time.time() + timeout
    while time.time() < end and running():
        time.sleep(0.4)


WM_KEYDOWN, WM_KEYUP, WM_CHAR = 0x0100, 0x0101, 0x0102
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0201, 0x0202


def _post(hwnd, msg, wparam, lparam):
    user32.PostMessageW(hwnd, msg, wparam, lparam)


def post_key(hwnd, vk):
    scan = user32.MapVirtualKeyW(vk, 0)
    _post(hwnd, WM_KEYDOWN, vk, 1 | (scan << 16))
    if vk in (0x0D, 0x1B, 0x08, 0x09):
        _post(hwnd, WM_CHAR, {0x0D: 13, 0x1B: 27, 0x08: 8, 0x09: 9}[vk], 1 | (scan << 16))
    _post(hwnd, WM_KEYUP, vk, 1 | (scan << 16) | (0xC0 << 24))
    time.sleep(0.12)


def post_text(hwnd, text):
    # WM_CHAR alone: a WM_KEYDOWN as well makes the emulator read the key twice.
    for ch in text:
        _post(hwnd, WM_CHAR, ord(ch), 1)
        time.sleep(0.06)


def shot(path):
    """Capture the emulator window even when it is behind other windows."""
    from PIL import Image
    hwnd = focus()
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    gdi32 = ctypes.WinDLL("gdi32")
    hdc = user32.GetWindowDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mdc, bmp)
    user32.PrintWindow(hwnd, mdc, 2)

    class BMIH(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                    ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                    ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                    ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]
    bi = BMIH(ctypes.sizeof(BMIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, hdc)
    Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1).save(path)


def click(x, y):
    """Click at a pixel of a `shot` image of the window."""
    hwnd = focus()
    # (x, y) are measured on a `shot` image, which is the whole window;
    # mouse messages want client coordinates.
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    p = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(p))
    x, y = x - (p.x - r.left), y - (p.y - r.top)
    lp = (y << 16) | (x & 0xFFFF)
    _post(hwnd, 0x0200, 0, lp)  # WM_MOUSEMOVE first, or Qt ignores the press
    time.sleep(0.05)
    _post(hwnd, WM_LBUTTONDOWN, 1, lp)
    time.sleep(0.08)
    _post(hwnd, WM_LBUTTONUP, 0, lp)
    time.sleep(0.2)


# Window placement that every coordinate in this file assumes: the skin at
# this size puts the LCD at LCD_BOX of a `shot` image.
PLACE = (900, 60, 525, 1125)
LCD_BOX = (100, 270, 425, 520)


def place():
    hwnd = focus()
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE: restore, keep focus where it is
        time.sleep(0.5)
    user32.MoveWindow(hwnd, *PLACE, True)
    time.sleep(0.5)


def lcd(path):
    """Screenshot of just the calculator's screen."""
    from PIL import Image
    tmp = path + ".full.png"
    shot(tmp)
    Image.open(tmp).crop(LCD_BOX).save(path)
    os.remove(tmp)


def run_tokens(tokens):
    hwnd = focus()
    for tok in tokens:
        if tok.startswith("WAIT:"):
            time.sleep(float(tok[5:]))
        elif tok.startswith("CLICK:"):
            x, y = tok[6:].split(",")
            click(int(x), int(y))
        elif tok.startswith("KB:"):
            for t in kb_taps(tok[3:]):
                x, y = t[6:].split(",")
                click(int(x), int(y))
                time.sleep(0.35)
        elif tok in SPECIAL:
            post_key(hwnd, SPECIAL[tok])
        else:
            post_text(hwnd, tok)


KB0 = list("1234567890qwertyuiopasdfghjkl_") + ["#S"] + list("zxcvbnm,.") + ["#F"] + list("+-*/^()=π")


def kb_taps(text):
    """CLICK tokens that type `text` on CalcVault's on-screen keyboard,
    which must be showing its first page."""
    out, upper = [], False
    for ch in text:
        want_upper = ch.isalpha() and ch.isupper() and ch != "π"
        key = ch.lower() if want_upper else ch
        if key not in KB0:
            raise SystemExit("no key for %r" % ch)
        if want_upper != upper:
            out.append(_kb_click(KB0.index("#S")))
            upper = want_upper
        out.append(_kb_click(KB0.index(key)))
    if upper:
        out.append(_kb_click(KB0.index("#S")))
    return out


def _kb_click(i):
    r, c = divmod(i, 10)
    x, y = c * 32 + 16, 102 + r * 22 + 11
    return "CLICK:%d,%d" % (LCD_BOX[0] + x, LCD_BOX[1] + y)


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "launch":
        launch()
    elif cmd == "close":
        close()
    elif cmd == "keys":
        run_tokens(args)
    elif cmd == "shot":
        shot(args[0])
    elif cmd == "lcd":
        lcd(args[0])
    elif cmd == "place":
        place()
    else:
        raise SystemExit("unknown command " + cmd)
