"""Windows APIs scoped to the launcher's own native window."""

import ctypes
from ctypes import wintypes

from wisc.ui import theme as theme


WM_SYSCOMMAND = 0x0112
SYSTEM_COMMANDS = {"minimize": 0xF020, "maximize": 0xF030, "restore": 0xF120, "close": 0xF060}


class _Margins(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int) for name in ("left", "right", "top", "bottom")]


class _TrackMouse(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("window", wintypes.HWND), ("hover_time", wintypes.DWORD)]


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                ("work", wintypes.RECT), ("flags", wintypes.DWORD)]


class NativeWindow:
    def __init__(self, handle: int):
        self.handle = wintypes.HWND(handle)
        self._user = ctypes.WinDLL("user32", use_last_error=True)
        self._dwm = ctypes.WinDLL("dwmapi", use_last_error=True)
        self._gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        pointer = ctypes.sizeof(ctypes.c_void_p) == 8
        self._get_style = getattr(self._user, "GetWindowLongPtrW" if pointer else "GetWindowLongW")
        self._set_style = getattr(self._user, "SetWindowLongPtrW" if pointer else "SetWindowLongW")
        self._set_class = getattr(self._user, "SetClassLongPtrW" if pointer else "SetClassLongW")
        self._get_style.argtypes = [wintypes.HWND, ctypes.c_int]
        self._get_style.restype = ctypes.c_ssize_t
        self._set_style.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        self._set_style.restype = ctypes.c_ssize_t
        self._set_class.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        self._set_class.restype = ctypes.c_ssize_t
        self._brush: int | None = None
        self._user.IsWindow.argtypes = [wintypes.HWND]
        self._user.IsWindow.restype = wintypes.BOOL
        self._user.IsIconic.argtypes = [wintypes.HWND]
        self._user.IsIconic.restype = wintypes.BOOL
        self._user.IsZoomed.argtypes = [wintypes.HWND]
        self._user.IsZoomed.restype = wintypes.BOOL
        self._user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self._user.PostMessageW.restype = wintypes.BOOL
        self._user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        self._user.SetWindowPos.restype = wintypes.BOOL
        self._user.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        self._user.ScreenToClient.restype = wintypes.BOOL
        self._user.SetCapture.argtypes = [wintypes.HWND]
        self._user.SetCapture.restype = wintypes.HWND
        self._user.ReleaseCapture.argtypes = []
        self._user.ReleaseCapture.restype = wintypes.BOOL
        self._user.TrackMouseEvent.argtypes = [ctypes.POINTER(_TrackMouse)]
        self._user.TrackMouseEvent.restype = wintypes.BOOL
        self._user.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        self._user.MonitorFromWindow.restype = wintypes.HANDLE
        self._user.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MonitorInfo)]
        self._user.GetMonitorInfoW.restype = wintypes.BOOL
        self._dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD,
                                                  ctypes.c_void_p, wintypes.DWORD]
        self._dwm.DwmSetWindowAttribute.restype = ctypes.c_long
        self._dwm.DwmExtendFrameIntoClientArea.argtypes = [wintypes.HWND, ctypes.POINTER(_Margins)]
        self._dwm.DwmExtendFrameIntoClientArea.restype = ctypes.c_long

    @property
    def valid(self) -> bool:
        return bool(self._user.IsWindow(self.handle))

    @property
    def minimized(self) -> bool:
        return bool(self._user.IsIconic(self.handle))

    @property
    def maximized(self) -> bool:
        return bool(self._user.IsZoomed(self.handle))

    def configure(self) -> None:
        # Retain a real overlapped window for DWM transitions; the client paints its caption.
        style = self._get_style(self.handle, -16) & 0xFFFFFFFF
        desired = (style & ~0x80000000) | 0x00CF0000  # WS_OVERLAPPEDWINDOW, without WS_POPUP.
        if style != desired:
            ctypes.set_last_error(0)
            previous = self._set_style(self.handle, -16, desired)
            if not previous and ctypes.get_last_error():
                raise ctypes.WinError(ctypes.get_last_error())
            self._user.SetWindowPos(self.handle, None, 0, 0, 0, 0, 0x0037)
        policy = ctypes.c_int(2)  # DWMNCRP_ENABLED.
        self._dwm.DwmSetWindowAttribute(self.handle, 2, ctypes.byref(policy), ctypes.sizeof(policy))
        disabled = wintypes.BOOL(False)
        self._dwm.DwmSetWindowAttribute(self.handle, 3, ctypes.byref(disabled), ctypes.sizeof(disabled))
        margins = _Margins(1, 1, 1, 1)
        self._dwm.DwmExtendFrameIntoClientArea(self.handle, ctypes.byref(margins))

        # Dark mode for DWM composition prevents white flashes and white strips during live sizing.
        dark = wintypes.BOOL(True)
        if self._dwm.DwmSetWindowAttribute(self.handle, 20, ctypes.byref(dark), ctypes.sizeof(dark)) != 0:
            self._dwm.DwmSetWindowAttribute(self.handle, 19, ctypes.byref(dark), ctypes.sizeof(dark))
        surface_color = wintypes.DWORD(theme.SURFACE_COLORREF)
        self._dwm.DwmSetWindowAttribute(self.handle, 35, ctypes.byref(surface_color), ctypes.sizeof(surface_color))
        self._dwm.DwmSetWindowAttribute(self.handle, 34, ctypes.byref(surface_color), ctypes.sizeof(surface_color))

        # Set the window class background brush to match launcher surface so GDI fallback is dark.
        if self._brush is None:
            self._brush = self._gdi.CreateSolidBrush(theme.SURFACE_COLORREF)
        if self._brush:
            self._set_class(self.handle, -10, self._brush)

    def release(self) -> None:
        if self._brush:
            self._gdi.DeleteObject(self._brush)
            self._brush = None

    def command(self, action: str) -> bool:
        return self.valid and bool(self._user.PostMessageW(
            self.handle, WM_SYSCOMMAND, SYSTEM_COMMANDS[action], 0,
        ))

    def client_point(self, lparam: int, *, screen: bool) -> tuple[int, int]:
        point = wintypes.POINT(ctypes.c_short(lparam & 0xFFFF).value,
                               ctypes.c_short((lparam >> 16) & 0xFFFF).value)
        if screen:
            self._user.ScreenToClient(self.handle, ctypes.byref(point))
        return point.x, point.y

    def capture(self) -> None:
        self._user.SetCapture(self.handle)

    def release_capture(self) -> None:
        self._user.ReleaseCapture()

    def track_leave(self) -> None:
        tracking = _TrackMouse(ctypes.sizeof(_TrackMouse), 0x0012, self.handle, 0)
        self._user.TrackMouseEvent(ctypes.byref(tracking))

    def calculate_client_bounds(self, lparam: int) -> None:
        if not self.maximized or self.minimized:
            return
        monitor = self._user.MonitorFromWindow(self.handle, 2)
        info = _MonitorInfo()
        info.size = ctypes.sizeof(info)
        if not monitor or not self._user.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return
        client = wintypes.RECT.from_address(lparam)
        client.left, client.top = info.work.left, info.work.top
        client.right, client.bottom = info.work.right, info.work.bottom
