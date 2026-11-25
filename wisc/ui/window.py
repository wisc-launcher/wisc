"""Cross-platform Wisc title bar with isolated native Windows enhancements."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from PyQt6.QtCore import QAbstractAnimation, QEasingCurve, QEvent, QPoint, QRectF, QSize, Qt, QTimer, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
    QAbstractButton, QApplication, QHBoxLayout, QLabel, QMainWindow,
    QPushButton, QWidget,
)

from wisc.core.paths import ASSETS_DIR
from wisc.ui import theme as theme
from wisc.ui.components import GlassPanel, artwork_image, asset_icon, text_label
from wisc.ui.geometry import WindowGeometry
from wisc.ui.theme import MUTED, TEXT, install_focus_cues

if TYPE_CHECKING:
    from wisc.ui.native import NativeWindow


TITLE_BAR_HEIGHT = 52


def navigation_icon(page: str, color: str) -> QIcon:
    names = {"home": "home.svg", "installations": "library.svg", "mods": "mods.svg",
             "skins": "skins.svg", "options": "settings.svg"}
    return asset_icon(ASSETS_DIR / "tab-icons" / names.get(page, "settings.svg"), color)


class WindowButton(QAbstractButton):
    def __init__(self, action: str, window: QMainWindow):
        super().__init__()
        self.action, self._window = action, window
        self._accent = theme.DEFAULT_ACCENT
        self.native_hover = False
        self.setFixedSize(40, 40)
        self.setToolTip(action.capitalize())
        self.setAccessibleName(action.capitalize())
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(lambda: window.request_window_action(self.action))

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if (self.native_hover or self.underMouse() or self.isDown()
                or (self.hasFocus() and self.property("keyboardFocus"))):
            tint = QColor(self._accent) if self.action == "close" else QColor(TEXT)
            tint.setAlpha(theme.WINDOW_PRESSED_ALPHA if self.isDown() else theme.WINDOW_HOVER_ALPHA)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(tint)
            painter.drawRoundedRect(QRectF(self.rect()), theme.RADIUS_BUTTON, theme.RADIUS_BUTTON)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(self._accent if self.action == "close" else TEXT), theme.STROKE_ICON))
        if self.action == "minimize":
            painter.drawLine(15, 20, 25, 20)
        elif self.action == "close":
            painter.drawLine(15, 15, 25, 25)
            painter.drawLine(25, 15, 15, 25)
        elif self._window.window_maximized:
            rear = QPainterPath()
            rear.moveTo(17, 16)
            rear.lineTo(17, 14)
            rear.lineTo(26, 14)
            rear.lineTo(26, 23)
            rear.lineTo(24, 23)
            painter.drawPath(rear)
            painter.drawRect(QRectF(14, 17, 9, 9))
        else:
            painter.drawRect(QRectF(15, 15, 10, 10))


class _NavTabButton(QPushButton):
    """Top navigation button with hover fade and smooth icon tint crossfade."""

    def __init__(self, page: str, label: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._page = page
        self._accent = theme.DEFAULT_ACCENT
        self._hover_progress = 0.0
        self._active_progress = 0.0
        self._pixmaps: dict[tuple[str, float], QPixmap] = {}

        self.setObjectName("nav")
        self.setFixedSize(58, 38)
        self.setIconSize(QSize(23, 23))
        self.setToolTip(label)
        self.setAccessibleName(label)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(140)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_anim.valueChanged.connect(self._on_hover_step)

        self._active_anim = QVariantAnimation(self)
        self._active_anim.setDuration(220)
        self._active_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._active_anim.valueChanged.connect(self._on_active_step)

    def _on_hover_step(self, value: object) -> None:
        self._hover_progress = float(value)
        self.update()

    def _on_active_step(self, value: object) -> None:
        self._active_progress = float(value)
        self.update()

    def set_accent(self, accent: str) -> None:
        if self._accent != accent:
            self._accent = accent
            self._pixmaps.clear()
            self.update()

    def set_active(self, active: bool, *, animate: bool = True) -> None:
        self.setChecked(active)
        target = 1.0 if active else 0.0
        if not animate or not self.isVisible():
            self._active_anim.stop()
            self._active_progress = target
            self.update()
            return
        if abs(target - self._active_progress) < 0.01 and self._active_anim.state() != QAbstractAnimation.State.Running:
            return
        self._active_anim.stop()
        self._active_anim.setStartValue(self._active_progress)
        self._active_anim.setEndValue(target)
        self._active_anim.start()

    def _pixmap_for(self, color: str, dpr: float) -> QPixmap:
        key = (color, dpr)
        cached = self._pixmaps.get(key)
        if cached is not None:
            return cached
        pixmap = navigation_icon(self._page, color).pixmap(self.iconSize())
        self._pixmaps[key] = pixmap
        return pixmap

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        focus_active = self.hasFocus() and bool(self.property("keyboardFocus"))
        if self._hover_progress > 0.005 or focus_active:
            alpha = max(round(10 * self._hover_progress), 14 if focus_active else 0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, alpha))
            painter.drawRoundedRect(QRectF(self.rect()), theme.RADIUS_BUTTON, theme.RADIUS_BUTTON)

        dpr = self.devicePixelRatioF()
        muted_px = self._pixmap_for(MUTED, dpr)
        accent_px = self._pixmap_for(self._accent, dpr)
        size = self.iconSize()
        target_rect = QRectF(
            (self.width() - size.width()) / 2.0,
            (self.height() - size.height()) / 2.0,
            size.width(),
            size.height(),
        )

        if self._active_progress < 0.995:
            painter.setOpacity(1.0 - self._active_progress)
            painter.drawPixmap(target_rect, muted_px, QRectF(muted_px.rect()))
        if self._active_progress > 0.005:
            painter.setOpacity(self._active_progress)
            painter.drawPixmap(target_rect, accent_px, QRectF(accent_px.rect()))


class _NavTabsBar(QWidget):
    """Tab container painting the sliding active selection pill behind nav icons."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("tabs")
        self.setFixedHeight(44)
        self._accent = theme.DEFAULT_ACCENT
        self._active_button: _NavTabButton | None = None
        self._pill_x = 3.0
        self._pill_width = 58.0
        self._pill_initialized = False

        self._pill_anim = QVariantAnimation(self)
        self._pill_anim.setDuration(220)
        self._pill_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._pill_anim.valueChanged.connect(self._on_pill_step)

    def _on_pill_step(self, value: object) -> None:
        self._pill_x = float(value)
        self.update()

    def set_accent(self, accent: str) -> None:
        if self._accent != accent:
            self._accent = accent
            self.update()

    def set_active_button(self, button: _NavTabButton, *, animate: bool = True) -> None:
        self._active_button = button
        target_x = float(button.x())
        target_w = float(button.width() or 58)
        if not animate or not self.isVisible() or not self._pill_initialized or button.width() <= 0:
            self._pill_anim.stop()
            self._pill_x = target_x
            self._pill_width = target_w
            self._pill_initialized = button.width() > 0
            self.update()
            return
        if abs(target_x - self._pill_x) < 0.5 and self._pill_anim.state() != QAbstractAnimation.State.Running:
            self._pill_x = target_x
            self._pill_width = target_w
            self.update()
            return
        self._pill_anim.stop()
        self._pill_anim.setStartValue(self._pill_x)
        self._pill_anim.setEndValue(target_x)
        self._pill_width = target_w
        self._pill_anim.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._active_button is not None and not self._pill_initialized:
            self.set_active_button(self._active_button, animate=False)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._active_button is not None and self._pill_anim.state() != QAbstractAnimation.State.Running:
            self._pill_x = float(self._active_button.x())
            self._pill_width = float(self._active_button.width() or 58)
            self._pill_initialized = self._active_button.width() > 0

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 4))
        painter.drawRoundedRect(QRectF(self.rect()), 11.0, 11.0)
        if self._active_button is not None:
            pill = QColor(self._accent)
            pill.setAlpha(46)
            painter.setBrush(pill)
            painter.drawRoundedRect(
                QRectF(self._pill_x, 3.0, self._pill_width, 38.0),
                float(theme.RADIUS_BUTTON),
                float(theme.RADIUS_BUTTON),
            )


class TitleBar(GlassPanel):
    navigation_requested = pyqtSignal(str)

    def __init__(self, window: QMainWindow):
        super().__init__(radius=theme.RADIUS_SQUARE)
        self._window = window
        self.setFixedHeight(TITLE_BAR_HEIGHT)
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 0, 20, 0)
        row.setSpacing(0)
        branding = QWidget()
        branding.setFixedWidth(200)
        brand = QHBoxLayout(branding)
        brand.setContentsMargins(15, 0, 0, 0)
        brand.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(artwork_image(str(ASSETS_DIR / "icons" / "wisc_mark.png")).scaled(
            31, 22, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
        ))
        brand.addWidget(logo)
        brand.addWidget(text_label("Wisc", theme.FONT_PAGE_TITLE, bold=True, pixel=True))
        brand.addStretch(1)
        row.addWidget(branding)
        row.addStretch(1)
        self._tabs = _NavTabsBar()
        tab_layout = QHBoxLayout(self._tabs)
        tab_layout.setContentsMargins(3, 3, 3, 3)
        tab_layout.setSpacing(4)
        self.buttons: dict[str, _NavTabButton] = {}
        for page, label in (("home", "Home"), ("installations", "Library"),
                            ("mods", "Mods & Modpacks"), ("skins", "Skins"), ("options", "Options")):
            button = _NavTabButton(page, label)
            button.clicked.connect(lambda checked=False, key=page: self._request_navigation(key))
            self.buttons[page] = button
            tab_layout.addWidget(button)
        row.addWidget(self._tabs)
        row.addStretch(1)
        controls = QWidget()
        controls.setFixedWidth(200)
        control_layout = QHBoxLayout(controls)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(0)
        control_layout.addStretch(1)
        self.window_buttons: dict[str, WindowButton] = {}
        for action in ("minimize", "maximize", "close"):
            button = WindowButton(action, window)
            self.window_buttons[action] = button
            control_layout.addWidget(button)
        row.addWidget(controls)
        self._page = "home"
        self._accent = theme.DEFAULT_ACCENT
        self._icon_colors: dict[str, str] = {}
        self.set_current_page("home")

    def set_current_page(self, page: str) -> None:
        changed = page != self._page
        self._page = page
        for key, button in self.buttons.items():
            button.set_active(key == page, animate=changed)
            color = self._accent if key == page else MUTED
            if self._icon_colors.get(key) != color:
                button.setIcon(navigation_icon(key, color))
                self._icon_colors[key] = color
        active = self.buttons.get(page)
        if active is not None:
            self._tabs.set_active_button(active, animate=changed)

    def apply_theme(self, colors: dict[str, str]) -> None:
        self._accent = colors["btn_primary"]
        self._tabs.set_accent(self._accent)
        for button in self.buttons.values():
            button.set_accent(self._accent)
        self.set_current_page(self._page)
        for button in self.window_buttons.values():
            button._accent = self._accent
            button.update()

    def _request_navigation(self, page: str) -> None:
        self.set_current_page(self._page)
        self.navigation_requested.emit(page)

    def is_drag_area(self, point: QPoint) -> bool:
        widget = self.childAt(point)
        while widget is not None and widget is not self:
            if isinstance(widget, QAbstractButton):
                return False
            widget = widget.parentWidget()
        return True

    def window_button_at(self, point: QPoint) -> WindowButton | None:
        widget = self.childAt(point)
        while widget is not None and widget is not self:
            if isinstance(widget, WindowButton):
                return widget
            widget = widget.parentWidget()
        return None

    def update_window_state(self) -> None:
        button = self.window_buttons["maximize"]
        label = "Restore" if self._window.window_maximized else "Maximize"
        button.setToolTip(label)
        button.setAccessibleName(label)
        for control in self.window_buttons.values():
            control.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._window.start_system_move(event.globalPosition().toPoint()):
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._window.toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class FramelessWindow(QMainWindow):
    """Qt controls on every desktop, with optional native Windows integration."""

    def __init__(self):
        super().__init__()
        self._native: NativeWindow | None = None
        self._native_frame_ready = False
        self._pending_action: str | None = None
        self._pressed_window_button: WindowButton | None = None
        self._hovered_window_button: WindowButton | None = None
        self._in_native_resize = False
        self._resize_repaint = False
        self._frame_setup = QTimer(self)
        self._frame_setup.setSingleShot(True)
        self._frame_setup.timeout.connect(self._install_native_frame)
        self._state_refresh = QTimer(self)
        self._state_refresh.setSingleShot(True)
        self._state_refresh.timeout.connect(self._refresh_window_state)
        self._action_timeout = QTimer(self)
        self._action_timeout.setSingleShot(True)
        self._action_timeout.timeout.connect(self._finish_window_action)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._geometry = WindowGeometry(self)

    @property
    def window_maximized(self) -> bool:
        if self.isFullScreen():
            return True
        if self._native is not None and self._native.valid:
            return self._native.maximized
        return self.isMaximized()

    @property
    def native_geometry_available(self) -> bool:
        return self._native is not None and self._native.valid

    def start_system_move(self, position: QPoint) -> bool:
        return self._geometry.start_move(position)

    def toggle_maximized(self) -> None:
        self.request_window_action("maximize")

    def request_window_action(self, action: str) -> None:
        if action not in ("minimize", "maximize", "restore", "close"):
            raise ValueError(f"Unknown window action: {action}")
        native = self._native
        if native is None or not native.valid:
            if action == "minimize":
                self.showMinimized()
            elif action == "maximize":
                self.showNormal() if self.window_maximized else self.showMaximized()
            elif action == "restore":
                self.showNormal()
            else:
                self.close()
            self._refresh_window_state()
            return
        self._refresh_window_state()
        if self._pending_action is not None and action != "close":
            return
        if action == "minimize" and native.minimized:
            return
        command = "restore" if action == "maximize" and native.maximized else action
        self._pending_action = command
        if not native.command(command):
            self._pending_action = None
            return
        self._action_timeout.start(500)

    def showEvent(self, event) -> None:
        # Configure before the native ShowWindow so DWM sees a normal window on opening.
        self._install_native_frame()
        super().showEvent(event)
        self._frame_setup.start(0)

    def _install_native_frame(self) -> None:
        if not self.isVisible() or sys.platform != "win32" or QApplication.platformName() != "windows":
            return
        from wisc.ui.native import NativeWindow

        handle = int(self.winId())
        if self._native is None or self._native.handle.value != handle:
            self._native = NativeWindow(handle)
        self._native_frame_ready = True
        self._native.configure()
        self._refresh_window_state()

    def _finish_window_action(self) -> None:
        self._pending_action = None
        self._refresh_window_state()

    def _refresh_window_state(self) -> None:
        native = self._native
        if native is not None and native.valid:
            action = self._pending_action
            complete = ((action == "minimize" and native.minimized)
                        or (action == "maximize" and native.maximized and not native.minimized)
                        or (action == "restore" and not native.maximized and not native.minimized))
            if complete:
                self._pending_action = None
                self._action_timeout.stop()
        title_bar = getattr(self, "title_bar", None)
        if title_bar is not None:
            title_bar.update_window_state()

    def _hit_test(self, point: QPoint) -> int:
        native = self._native
        minimized = native is not None and native.valid and native.minimized
        if not self.window_maximized and not minimized and not self.isFullScreen():
            left, right = point.x() < 6, point.x() >= self.width() - 6
            top, bottom = point.y() < 6, point.y() >= self.height() - 6
            if top and left:
                return 13
            if top and right:
                return 14
            if bottom and left:
                return 16
            if bottom and right:
                return 17
            if left or right:
                return 10 if left else 11
            if top or bottom:
                return 12 if top else 15
        title_bar = getattr(self, "title_bar", None)
        if title_bar is not None and title_bar.geometry().contains(point):
            local = title_bar.mapFrom(self, point)
            button = title_bar.window_button_at(local)
            if button is not None:
                return {"minimize": 8, "maximize": 9, "close": 20}[button.action]
            if title_bar.is_drag_area(local):
                return 2
        return 1

    def _message_point(self, lparam: int, *, screen: bool) -> QPoint:
        x, y = self._native.client_point(lparam, screen=screen)
        scale = self.devicePixelRatioF()
        return QPoint(round(x / scale), round(y / scale))

    def _window_button_at(self, point: QPoint) -> WindowButton | None:
        title_bar = getattr(self, "title_bar", None)
        if title_bar is None or not title_bar.geometry().contains(point):
            return None
        return title_bar.window_button_at(title_bar.mapFrom(self, point))

    def _set_native_hover(self, button: WindowButton | None) -> None:
        if button is self._hovered_window_button:
            return
        previous, self._hovered_window_button = self._hovered_window_button, button
        for control in (previous, button):
            if control is not None:
                control.native_hover = control is button
                control.update()

    def _release_window_button(self) -> WindowButton | None:
        button, self._pressed_window_button = self._pressed_window_button, None
        if button is not None:
            button.setDown(False)
            self._native.release_capture()
        return button

    def nativeEvent(self, event_type, message):
        if (getattr(self, "_native_frame_ready", False) and sys.platform == "win32"
                and event_type in (b"windows_generic_MSG", b"windows_dispatcher_MSG")):
            from ctypes import wintypes

            msg = wintypes.MSG.from_address(int(message))
            kind = msg.message
            if kind == 0x0014:  # WM_ERASEBKGND: avoid default GDI white background clearing.
                return True, 1
            if kind == 0x0083:  # WM_NCCALCSIZE: keep the client caption with native window styles.
                self._native.calculate_client_bounds(msg.lParam)
                return True, 0
            if kind == 0x0084:  # WM_NCHITTEST: native edges, caption, and system-button regions.
                return True, self._hit_test(self._message_point(msg.lParam, screen=True))
            if kind == 0x00A0:  # WM_NCMOUSEMOVE; leave unclaimed so Windows can show Snap Layouts.
                self._set_native_hover(self._window_button_at(self._message_point(msg.lParam, screen=True)))
                self._native.track_leave()
            elif kind == 0x02A2:
                self._set_native_hover(None)
            elif kind == 0x00A1:  # WM_NCLBUTTONDOWN on a custom system button.
                button = self._window_button_at(self._message_point(msg.lParam, screen=True))
                if button is not None:
                    install_focus_cues().pointer_input()
                    popup = QApplication.activePopupWidget()
                    if popup is not None:
                        popup.close()
                    self._pressed_window_button = button
                    button.setDown(True)
                    self._native.capture()
                    return True, 0
            elif kind in (0x0200, 0x0202, 0x00A2) and self._pressed_window_button is not None:
                point = self._message_point(msg.lParam, screen=kind == 0x00A2)
                current = self._window_button_at(point)
                if kind == 0x0200:
                    self._pressed_window_button.setDown(current is self._pressed_window_button)
                else:
                    pressed = self._release_window_button()
                    if current is pressed:
                        self.request_window_action(pressed.action)
                return True, 0
            elif kind in (0x001F, 0x0215):  # Cancel/capture loss must not leave a pressed glyph.
                self._release_window_button()
            elif kind == 0x0231:  # WM_ENTERSIZEMOVE: Windows runs its own modal message loop.
                self._in_native_resize = True
            elif kind == 0x0232:  # WM_EXITSIZEMOVE.
                self._in_native_resize = False
                self.update()
            if kind in (0x0005, 0x0047, 0x0006, 0x0018):
                if not self._state_refresh.isActive():
                    self._state_refresh.start(0)
            elif kind == 0x007D:
                self._frame_setup.start(0)
        # Calling QWidget.nativeEvent here recurses through PyQt's protected virtual wrapper.
        return False, 0

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.WinIdChange and hasattr(self, "_frame_setup"):
            self._native_frame_ready = False
            self._native = None
            self._frame_setup.start(0)
        return super().event(event)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "_state_refresh"):
            self._state_refresh.start(0)
            self._frame_setup.start(0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)

    def closeEvent(self, event) -> None:
        super().closeEvent(event)
        if event.isAccepted():
            if self._native is not None:
                self._native.release()
            self._frame_setup.stop()
            self._state_refresh.stop()
            self._action_timeout.stop()
            self._geometry.cancel()
            self._pending_action = None
            self._in_native_resize = False
