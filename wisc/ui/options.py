"""Qt Settings / Options dashboard and subpages."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QByteArray, QRectF, QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QPainter
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from wisc.core.paths import ASSETS_DIR
from wisc.core.storage import (
    DATA_DIR,
    DEFAULT_SETTINGS,
    add_or_update_account,
    get_active_account,
    load_accounts,
    load_settings,
    load_theme_choice,
    remove_account,
    save_settings,
    save_theme_choice,
    set_active_account,
    update_offline_username,
)
from wisc.core.themes import (
    DEFAULT_THEME,
    get_theme_names,
)
from wisc.services import java as java_runtimes
from wisc.ui import theme as theme
from wisc.ui.theme import ui_font
from wisc.ui.components import (
    ElidedLabel,
    GlassButton,
    enable_smooth_scroll,
    GlassLineEdit,
    GlassPanel,
    LauncherComboBox,
    StaggeredReveal,
    paint_glass,
    paint_switch,
    text_label,
)
from wisc.ui.tasks import ServiceRunner


def _open_folder(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
        if hasattr(os, "startfile"):
            os.startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.Popen(
                ["open", str(path)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.Popen(
                ["xdg-open", str(path)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except Exception:
        pass


def _system_memory_mb() -> int:
    try:
        import psutil  # type: ignore

        total = int(psutil.virtual_memory().total // (1024 * 1024))
        if total >= 1024:
            return total
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            import ctypes

            class _MemStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = _MemStatus()
            stat.dwLength = ctypes.sizeof(_MemStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return max(2048, int(stat.ullTotalPhys // (1024 * 1024)))
        except Exception:
            pass
    return 16384


def _minecraft_dir() -> Path:
    import minecraft_launcher_lib

    return Path(minecraft_launcher_lib.utils.get_minecraft_directory())


class SettingsArt(QWidget):
    """Vector icon from .assets/settings/<name>.svg tinted with the active accent."""

    def __init__(self, name: str, accent: str, size: int = 34, parent: QWidget | None = None):
        super().__init__(parent)
        self._name = name
        self._accent = QColor(accent).name() if QColor(accent).isValid() else theme.DEFAULT_ACCENT
        self._renderer: QSvgRenderer | None = None
        self.setFixedSize(size, size)
        self._reload()

    def set_accent(self, accent: str) -> None:
        normalized = QColor(accent).name() if QColor(accent).isValid() else theme.DEFAULT_ACCENT
        if normalized != self._accent:
            self._accent = normalized
            self._reload()
            self.update()

    def _reload(self) -> None:
        svg_path = ASSETS_DIR / "settings" / f"{self._name}.svg"
        if not svg_path.is_file():
            self._renderer = None
            return
        raw = svg_path.read_text(encoding="utf-8")
        for token in ("#FFFFFF", "#ffffff", "#46BA34"):
            raw = raw.replace(token, self._accent)
        self._renderer = QSvgRenderer(QByteArray(raw.encode("utf-8")), self)

    def paintEvent(self, event) -> None:
        if self._renderer is None or not self._renderer.isValid():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._renderer.render(painter, QRectF(self.rect()))


class GlassSwitch(QAbstractButton):
    """Borderless pill switch with optional label, matching ModList switches."""

    def __init__(self, label: str = "", checked: bool = False, accent: str = theme.DEFAULT_ACCENT,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self._accent = accent
        self.setText(label)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(32)
        self._track_width = 44
        self._track_height = 24

    def set_accent(self, accent: str) -> None:
        self._accent = accent
        self.update()

    def sizeHint(self) -> QSize:
        if not self.text():
            return QSize(self._track_width, self._track_height + 6)
        fm = self.fontMetrics()
        return QSize(self._track_width + 12 + fm.horizontalAdvance(self.text()), 32)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cy = (self.height() - self._track_height) / 2.0
        track = QRectF(0, cy, self._track_width, self._track_height)
        paint_switch(painter, track, self.isChecked(), QColor(self._accent), enabled=self.isEnabled())
        if self.text():
            painter.setPen(QColor(theme.TEXT if self.isEnabled() else theme.DISABLED_TEXT))
            painter.setFont(theme.ui_font(theme.FONT_BODY))
            text_rect = QRectF(self._track_width + 12, 0, self.width() - self._track_width - 12, self.height())
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())


class OptionCard(QAbstractButton):
    """Clickable frosted category card on the Settings dashboard."""

    def __init__(self, category_id: str, title: str, art_name: str,
                 accent: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.category_id = category_id
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(196, 146)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 22, 20, 22)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.art = SettingsArt(art_name, accent, size=34, parent=self)
        layout.addWidget(self.art, 0, Qt.AlignmentFlag.AlignHCenter)

        title_lbl = text_label(title, theme.FONT_SUBHEADING, bold=True)
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_lbl, 0, Qt.AlignmentFlag.AlignHCenter)

    def apply_accent(self, accent: str) -> None:
        self.art.set_accent(accent)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        focused = self.hasFocus() and bool(self.property("keyboardFocus"))
        interaction = (
            theme.GLASS_PRESSED_OPACITY if self.isDown()
            else theme.GLASS_HOVER_OPACITY if self.underMouse()
            else theme.GLASS_FOCUS_OPACITY if focused else 0.0
        )
        paint_glass(
            self,
            painter,
            radius=theme.RADIUS_CARD,
            opacity=min(1.0, theme.GLASS_OPACITY + interaction),
        )


class _GlassInputDialog(QDialog):
    """Frameless frosted-glass text prompt matching the launcher theme."""

    def __init__(self, title: str, prompt: str, text: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(360)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        panel = GlassPanel(radius=theme.RADIUS_PANEL)
        outer.addWidget(panel)

        body = QVBoxLayout(panel)
        body.setContentsMargins(22, 20, 22, 20)
        body.setSpacing(12)
        body.addWidget(text_label(title, theme.FONT_DIALOG_TITLE, bold=True))
        body.addWidget(text_label(prompt, theme.FONT_BODY, muted=True))

        self._input = GlassLineEdit()
        self._input.setText(text)
        self._input.selectAll()
        self._input.returnPressed.connect(self.accept)
        body.addWidget(self._input)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)
        cancel_btn = GlassButton("Cancel")
        cancel_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
        cancel_btn.clicked.connect(self.reject)
        ok_btn = GlassButton("Save", accented=True)
        ok_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
        ok_btn.clicked.connect(self.accept)
        actions.addWidget(cancel_btn)
        actions.addWidget(ok_btn)
        body.addLayout(actions)

    def value(self) -> str:
        return self._input.text().strip()

    @classmethod
    def get_text(cls, parent: QWidget | None, title: str, prompt: str, text: str = "") -> tuple[str, bool]:
        dialog = cls(title, prompt, text, parent=parent)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        return dialog.value(), accepted


class _ElyLoginDialog(QDialog):
    """Frameless frosted-glass Ely.by sign-in dialog with 2FA support."""

    def __init__(
        self,
        runner: ServiceRunner,
        *,
        login_hint: str = "",
        title: str = "Sign in with Ely.by",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._runner = runner
        self._token: int | None = None
        self._result: dict | None = None
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(400)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        panel = GlassPanel(radius=theme.RADIUS_PANEL)
        outer.addWidget(panel)

        body = QVBoxLayout(panel)
        body.setContentsMargins(24, 22, 24, 22)
        body.setSpacing(12)
        body.addWidget(text_label(title, theme.FONT_DIALOG_TITLE, bold=True))
        body.addWidget(
            text_label(
                "Sign in with your Ely.by username or email to sync skins and play online.",
                theme.FONT_BODY,
                muted=True,
            )
        )

        self._login_input = GlassLineEdit()
        self._login_input.setPlaceholderText("Username or email")
        if login_hint:
            self._login_input.setText(login_hint)
        body.addWidget(self._login_input)

        self._password_input = GlassLineEdit()
        self._password_input.setPlaceholderText("Password")
        self._password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_input.returnPressed.connect(self._submit)
        body.addWidget(self._password_input)

        self._totp_input = GlassLineEdit()
        self._totp_input.setPlaceholderText("2FA code (6 digits)")
        self._totp_input.returnPressed.connect(self._submit)
        self._totp_input.hide()
        body.addWidget(self._totp_input)

        self._error_label = text_label("", theme.FONT_DETAIL)
        self._error_label.setStyleSheet("color: #fc8181;")
        self._error_label.setWordWrap(True)
        self._error_label.hide()
        body.addWidget(self._error_label)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        register_btn = GlassButton("Register")
        register_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
        register_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://account.ely.by/register"))
        )
        actions.addWidget(register_btn)
        actions.addStretch(1)

        self._cancel_btn = GlassButton("Cancel")
        self._cancel_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
        self._cancel_btn.clicked.connect(self._cancel)
        actions.addWidget(self._cancel_btn)

        self._sign_in_btn = GlassButton("Sign In", accented=True)
        self._sign_in_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
        self._sign_in_btn.clicked.connect(self._submit)
        actions.addWidget(self._sign_in_btn)
        body.addLayout(actions)

    @property
    def auth_result(self) -> dict | None:
        return self._result

    def _set_busy(self, busy: bool) -> None:
        self._login_input.setEnabled(not busy)
        self._password_input.setEnabled(not busy)
        self._totp_input.setEnabled(not busy)
        self._sign_in_btn.setEnabled(not busy)
        self._sign_in_btn.setText("Signing in..." if busy else "Sign In")

    def _submit(self) -> None:
        if self._token is not None:
            return
        login = self._login_input.text().strip()
        password = self._password_input.text()
        totp = self._totp_input.text().strip() or None
        if not login or not password:
            self._error_label.setText("Enter your Ely.by username/email and password.")
            self._error_label.show()
            return
        self._error_label.hide()
        self._set_busy(True)

        from wisc.services import auth as ely_auth

        def run_auth():
            return ely_auth.authenticate(login, password, totp_code=totp)

        def on_done(result: dict) -> None:
            self._token = None
            self._set_busy(False)
            self._result = {**result, "email": login}
            self.accept()

        def on_fail(error: Exception) -> None:
            self._token = None
            self._set_busy(False)
            if isinstance(error, ely_auth.Ely2FARequiredError):
                self._totp_input.show()
                self._totp_input.setFocus()
            self._error_label.setText(str(error) or "Sign-in failed.")
            self._error_label.show()

        self._token = self._runner.submit(run_auth, on_done, on_fail)

    def _cancel(self) -> None:
        if self._token is not None:
            self._runner.cancel(self._token)
            self._token = None
        self.reject()


def _setting_row(
    title: str,
    description: str,
    control: QWidget | None = None,
    extra: QWidget | None = None,
) -> GlassPanel:
    panel = GlassPanel(radius=theme.RADIUS_CARD)
    outer = QVBoxLayout(panel)
    outer.setContentsMargins(18, 14, 18, 14)
    outer.setSpacing(12)

    top = QHBoxLayout()
    top.setSpacing(16)

    info = QVBoxLayout()
    info.setSpacing(3)
    info.addWidget(text_label(title, theme.FONT_ROW_TITLE, bold=True))
    desc = text_label(description, theme.FONT_DETAIL, muted=True)
    desc.setWordWrap(True)
    info.addWidget(desc)
    top.addLayout(info, 1)

    if control is not None:
        top.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
    outer.addLayout(top)

    if extra is not None:
        outer.addWidget(extra)
    return panel


def _make_scroll_area() -> tuple[QScrollArea, QVBoxLayout]:
    scroll = QScrollArea()
    scroll.setObjectName("optionsScroll")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.viewport().setAutoFillBackground(False)
    enable_smooth_scroll(scroll)

    body = QWidget()
    body.setObjectName("optionsContent")
    layout = QVBoxLayout(body)
    layout.setContentsMargins(0, 0, 8, 12)
    layout.setSpacing(12)
    scroll.setWidget(body)
    return scroll, layout


class OptionsPage(QWidget):
    """Settings dashboard and subpages for the PyQt6 launcher."""

    theme_requested = pyqtSignal(str)
    settings_changed = pyqtSignal(dict)
    accounts_changed = pyqtSignal()
    java_progress = pyqtSignal(str)

    def __init__(
        self,
        runner: ServiceRunner,
        colors: dict[str, str],
        parent: QWidget | None = None,
        *,
        updater=None,
        progress: Callable[[str | None, int | None], None] | None = None,
    ):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.runner = runner
        self._colors = colors
        self._updater = updater
        self._progress_callback = progress
        self._settings = load_settings()
        self._cards: list[OptionCard] = []
        self._switches: list[GlassSwitch] = []
        self._update_check_token: int | None = None
        self._reveal = StaggeredReveal(self)
        if self._updater is not None:
            self._updater.state_changed.connect(self._on_updater_state_changed)

        root = QVBoxLayout(self)
        root.setContentsMargins(*theme.PAGE_MARGINS)
        root.setSpacing(theme.PAGE_SPACING)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        self._subpages: dict[str, QWidget] = {}
        self._build_dashboard()
        self.show_subpage("options", animate=False)

    def show_subpage(self, key: str, *, animate: bool = True) -> None:
        if key == "options_updates":
            key = "options_about"
        first_build = key not in self._subpages
        if first_build:
            build_page = {
                "options_ui": self._build_appearance_page,
                "options_java": self._build_java_page,
                "options_game": self._build_game_page,
                "options_accounts": self._build_accounts_page,
                "options_launcher": self._build_launcher_page,
                "options_about": self._build_about_page,
            }.get(key)
            if build_page is not None:
                build_page()
        widget = self._subpages.get(key) or self._subpages["options"]
        if key == "options_accounts":
            self._refresh_accounts_list()
        if key == "options_java" and hasattr(self, "_sync_java_fields"):
            self._sync_java_fields()
        self.stack.setCurrentWidget(widget)
        if animate and not first_build and self.isVisible():
            self._reveal.reveal(widget, targets=self._cards if key == "options" else None)

    def _persist(self, key: str, value: object) -> None:
        self._settings[key] = value
        save_settings(self._settings)
        self.settings_changed.emit(dict(self._settings))

    def _reset_fields(self, keys: tuple[str, ...], refresh_fn: Callable[[], None]) -> None:
        for key in keys:
            self._settings[key] = DEFAULT_SETTINGS[key]
        save_settings(self._settings)
        refresh_fn()
        self.settings_changed.emit(dict(self._settings))

    def _build_subpage_shell(
        self,
        key: str,
        title: str,
        on_reset: Callable[[], None] | None = None,
    ) -> QVBoxLayout:
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(12)
        back = GlassButton("Back")
        back.setFixedHeight(theme.COMPACT_HEIGHT)
        back.clicked.connect(lambda: self.show_subpage("options"))
        header.addWidget(back)
        header.addWidget(text_label(title, theme.FONT_PAGE_TITLE, bold=True))
        header.addStretch(1)
        if on_reset is not None:
            reset_btn = GlassButton("Reset to defaults")
            reset_btn.setFixedHeight(theme.COMPACT_HEIGHT)
            reset_btn.clicked.connect(on_reset)
            header.addWidget(reset_btn)
        outer.addLayout(header)

        scroll, content = _make_scroll_area()
        outer.addWidget(scroll, 1)
        self._subpages[key] = container
        self.stack.addWidget(container)
        return content

    def _build_dashboard(self) -> None:
        scroll, content = _make_scroll_area()
        self._subpages["options"] = scroll
        self.stack.addWidget(scroll)

        content.addStretch(1)

        center_row = QHBoxLayout()
        center_row.addStretch(1)

        center_box = QWidget()
        center_box.setMaximumWidth(740)
        center_col = QVBoxLayout(center_box)
        center_col.setContentsMargins(0, 0, 0, 0)
        center_col.setSpacing(24)

        categories = [
            ("options_ui", "UI", "palette"),
            ("options_java", "Java", "core"),
            ("options_game", "Game", "game"),
            ("options_accounts", "Accounts", "account"),
            ("options_launcher", "Launcher", "sliders"),
            ("options_about", "About", "info"),
        ]
        grid = QGridLayout()
        grid.setSpacing(16)
        for index, (cat_id, title, art) in enumerate(categories):
            card = OptionCard(cat_id, title, art, self._colors["btn_primary"])
            card.clicked.connect(lambda checked=False, target=cat_id: self.show_subpage(target))
            self._cards.append(card)
            grid.addWidget(card, index // 3, index % 3)
        for col in range(3):
            grid.setColumnStretch(col, 1)
        center_col.addLayout(grid)

        quote = text_label(
            '"Keep a water bucket for the fall, and keep trusted people close when life gets steep."',
            theme.FONT_DETAIL,
            muted=True,
        )
        quote_font = quote.font()
        quote_font.setItalic(True)
        quote.setFont(quote_font)
        quote.setAlignment(Qt.AlignmentFlag.AlignCenter)
        quote.setWordWrap(True)
        center_col.addWidget(quote)

        center_row.addWidget(center_box, 1)
        center_row.addStretch(1)
        content.addLayout(center_row)
        content.addStretch(1)

    # ── UI / Appearance ─────────────────────────────────────────────────────
    def _build_appearance_page(self) -> None:
        content = self._build_subpage_shell("options_ui", "UI", self._reset_appearance)

        self._theme_combo = LauncherComboBox()
        self._theme_combo.setMinimumWidth(220)
        for name in get_theme_names():
            self._theme_combo.addItem(name, name)
        current_theme = load_theme_choice(get_theme_names())
        idx = self._theme_combo.findData(current_theme)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)
        self._theme_combo.currentIndexChanged.connect(self._on_theme_selected)
        content.addWidget(
            _setting_row(
                "Minecraft palettes",
                "Choose a Minecraft palette for accents, selections, and focus.",
                control=self._theme_combo,
            )
        )

        self._orbs_switch = GlassSwitch(
            "Enable background orbs",
            bool(self._settings.get("enable_orbs", True)),
            self._colors["btn_primary"],
        )
        self._orbs_switch.toggled.connect(lambda v: self._persist("enable_orbs", v))
        self._switches.append(self._orbs_switch)
        content.addWidget(
            _setting_row(
                "Ambient Background Orbs",
                "Display subtle animated gradient orbs in the background of screens.",
                control=self._orbs_switch,
            )
        )
        content.addStretch(1)

    def _on_theme_selected(self) -> None:
        name = self._theme_combo.currentData()
        if not isinstance(name, str) or not name:
            return
        save_theme_choice(name)
        self.theme_requested.emit(name)

    def _reset_appearance(self) -> None:
        self._persist("enable_orbs", DEFAULT_SETTINGS["enable_orbs"])
        self._orbs_switch.setChecked(bool(DEFAULT_SETTINGS["enable_orbs"]))
        save_theme_choice(DEFAULT_THEME)
        idx = self._theme_combo.findData(DEFAULT_THEME)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)

    # ── Java & Memory ───────────────────────────────────────────────────────
    def _build_java_page(self) -> None:
        from wisc.services.launcher import JVM_OPTIMIZATION_PRESETS

        self._max_ram = _system_memory_mb()
        content = self._build_subpage_shell(
            "options_java",
            "Java & Memory",
            lambda: self._reset_fields(
                ("ram_mb", "java_path", "jvm_preset", "jvm_arguments"),
                self._sync_java_fields,
            ),
        )

        ram_row = QWidget()
        ram_layout = QHBoxLayout(ram_row)
        ram_layout.setContentsMargins(0, 0, 0, 0)
        ram_layout.setSpacing(12)
        self._ram_slider = QSlider(Qt.Orientation.Horizontal)
        self._ram_slider.setMinimum(256)
        self._ram_slider.setMaximum(self._max_ram)
        self._ram_slider.setSingleStep(256)
        self._ram_slider.setPageStep(512)
        self._ram_slider.setFixedWidth(220)
        self._ram_input = GlassLineEdit()
        self._ram_input.setFixedWidth(96)
        self._ram_slider.valueChanged.connect(self._on_ram_slider_changed)
        self._ram_input.editingFinished.connect(self._on_ram_input_committed)
        ram_layout.addWidget(self._ram_slider)
        ram_layout.addWidget(self._ram_input)
        ram_layout.addWidget(text_label("MB", theme.FONT_DETAIL, muted=True))

        content.addWidget(
            _setting_row(
                "Allocated Memory (RAM)",
                f"Allocate between 256 MB and {self._max_ram:,} MB of detected system memory.",
                control=ram_row,
            )
        )

        java_row = QWidget()
        java_layout = QHBoxLayout(java_row)
        java_layout.setContentsMargins(0, 0, 0, 0)
        java_layout.setSpacing(8)
        self._java_input = GlassLineEdit()
        self._java_input.setMinimumWidth(220)
        self._java_input.setPlaceholderText("System Java (automatic)")
        self._java_input.textChanged.connect(lambda text: self._persist("java_path", text.strip()))
        self._detect_java_btn = GlassButton("Auto-Detect")
        self._detect_java_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
        self._detect_java_btn.clicked.connect(self._auto_detect_java)
        browse_btn = GlassButton("Browse")
        browse_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
        browse_btn.clicked.connect(self._browse_java)
        java_layout.addWidget(self._java_input, 1)
        java_layout.addWidget(self._detect_java_btn)
        java_layout.addWidget(browse_btn)

        content.addWidget(
            _setting_row(
                "Java Executable",
                "Leave empty to use Automatic Java, which installs the runtime each version needs. "
                "Select or detect an installation only to override it.",
                control=java_row,
            )
        )

        runtime_controls = QWidget()
        runtime_layout = QHBoxLayout(runtime_controls)
        runtime_layout.setContentsMargins(0, 0, 0, 0)
        runtime_layout.setSpacing(8)
        self._java_runtime_download_btn = GlassButton("Download Java", accented=True)
        self._java_runtime_download_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
        self._java_runtime_download_btn.clicked.connect(self._download_java_runtime)
        self._java_use_auto_btn = GlassButton("Use Automatic")
        self._java_use_auto_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
        self._java_use_auto_btn.clicked.connect(lambda: self._java_input.setText(""))
        runtime_layout.addWidget(self._java_runtime_download_btn)
        runtime_layout.addWidget(self._java_use_auto_btn)

        self._java_runtime_status = ElidedLabel()
        self._java_runtime_status.setFont(ui_font(theme.FONT_DETAIL))
        self._java_runtime_status.setProperty("muted", True)
        self._java_runtime_status.setMinimumWidth(240)
        self.java_progress.connect(self._java_runtime_status.setText)

        content.addWidget(
            _setting_row(
                "Java Runtime",
                "Version-matched Java managed by the launcher. It downloads before the first launch that needs it.",
                control=runtime_controls,
                extra=self._java_runtime_status,
            )
        )

        self._jvm_preset_combo = LauncherComboBox()
        self._jvm_preset_combo.setMinimumWidth(220)
        for preset_name in JVM_OPTIMIZATION_PRESETS:
            self._jvm_preset_combo.addItem(preset_name, preset_name)
        self._jvm_preset_combo.currentIndexChanged.connect(
            lambda: self._persist("jvm_preset", str(self._jvm_preset_combo.currentData() or "Default"))
        )
        content.addWidget(
            _setting_row(
                "Game Optimization Preset",
                "Apply tuned garbage collector flags (G1GC / ZGC / Shenandoah) for smoother frame times.",
                control=self._jvm_preset_combo,
            )
        )

        self._jvm_args_input = GlassLineEdit()
        self._jvm_args_input.setMinimumWidth(260)
        self._jvm_args_input.setPlaceholderText("e.g. -XX:+UseG1GC -XX:+ParallelRefProcEnabled")
        self._jvm_args_input.textChanged.connect(lambda text: self._persist("jvm_arguments", text.strip()))
        content.addWidget(
            _setting_row(
                "Global JVM Arguments",
                "Extra JVM flags applied to all profiles before per-profile arguments.",
                control=self._jvm_args_input,
            )
        )
        content.addStretch(1)
        self._sync_java_fields()

    def _sync_java_fields(self) -> None:
        ram = int(self._settings.get("ram_mb", DEFAULT_SETTINGS["ram_mb"]))
        ram = min(self._max_ram, max(256, ram))
        self._ram_slider.blockSignals(True)
        self._ram_slider.setValue(ram)
        self._ram_slider.blockSignals(False)
        self._ram_input.setText(str(ram))
        self._java_input.blockSignals(True)
        self._java_input.setText(str(self._settings.get("java_path", "")))
        self._java_input.blockSignals(False)
        preset = str(self._settings.get("jvm_preset", DEFAULT_SETTINGS["jvm_preset"]))
        idx = self._jvm_preset_combo.findData(preset)
        if idx >= 0:
            self._jvm_preset_combo.blockSignals(True)
            self._jvm_preset_combo.setCurrentIndex(idx)
            self._jvm_preset_combo.blockSignals(False)
        self._jvm_args_input.blockSignals(True)
        self._jvm_args_input.setText(str(self._settings.get("jvm_arguments", "")))
        self._jvm_args_input.blockSignals(False)
        self._refresh_java_runtime()

    def _auto_detect_java(self) -> None:
        from wisc.services.launcher import detect_java_installations
        from wisc.ui.components import GlassMenu

        found = detect_java_installations(_minecraft_dir())
        if not found:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Auto-Detect Java", "No Java installations were found automatically.")
            return
        if len(found) == 1:
            self._java_input.setText(found[0])
            return
        menu = GlassMenu(self._detect_java_btn)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        for path in found:
            menu.addAction(path, lambda checked=False, p=path: self._java_input.setText(p))
        menu.exec(self._detect_java_btn.mapToGlobal(self._detect_java_btn.rect().bottomLeft()))

    def _on_ram_slider_changed(self, value: int) -> None:
        snapped = max(256, min(self._max_ram, round(value / 128) * 128))
        self._ram_input.setText(str(snapped))
        self._persist("ram_mb", snapped)

    def _on_ram_input_committed(self) -> None:
        try:
            value = int(self._ram_input.text().strip())
        except ValueError:
            self._sync_java_fields()
            return
        clamped = max(256, min(self._max_ram, value))
        self._ram_input.setText(str(clamped))
        self._ram_slider.blockSignals(True)
        self._ram_slider.setValue(clamped)
        self._ram_slider.blockSignals(False)
        self._persist("ram_mb", clamped)

    def _browse_java(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Java Executable",
            str(Path(self._java_input.text()).parent) if self._java_input.text() else "",
            "Java Executable (java.exe javaw.exe);;All Files (*)",
        )
        if path:
            self._java_input.setText(path)

    def _java_requirement(self) -> tuple[str, str, str | None, int | None]:
        """Resolve the Java runtime the saved profile selection needs."""
        from wisc.core.storage import load_installations
        from wisc.services import launcher

        selected = str(self._settings.get("last_selected_profile") or "")
        profile = next(
            (item for item in load_installations() if str(item.get("id", "")) == selected),
            None,
        )
        if profile is None:
            return "", "", None, None
        name = str(profile.get("name") or profile.get("id") or "Selected profile")
        version_id = launcher.get_profile_version_id(profile) or ""
        root = _minecraft_dir()
        component: str | None = None
        major: int | None = None
        if version_id:
            component, major = java_runtimes.runtime_for_version(version_id, root)
        if not major:
            minecraft_version = str(profile.get("minecraft_version") or "")
            if minecraft_version:
                component, major = java_runtimes.runtime_for_version(minecraft_version, root)
        return name, version_id, component, major

    def _refresh_java_runtime(self) -> None:
        if not hasattr(self, "_java_runtime_status"):
            return
        name, version_id, component, major = self._java_requirement()
        if not major:
            self._java_runtime_status.setText(
                "Automatic: the launcher installs the Java runtime each version needs."
            )
            self._java_runtime_download_btn.setEnabled(False)
            return
        installed = java_runtimes.runtime_executable(component, _minecraft_dir())
        detail = f"Java {major} ({component})" if component else f"Java {major}"
        if installed:
            text = f"{name}: {detail} is installed."
        else:
            text = f"{name}: {detail} is not installed yet; it downloads before the first launch."
        manual = str(self._settings.get("java_path", "")).strip()
        if manual:
            selected_major = java_runtimes.java_major(manual)
            if selected_major and selected_major != major:
                text += f" The selected Java is {selected_major} and cannot run this version."
        self._java_runtime_status.setText(text)
        self._java_runtime_download_btn.setEnabled(not installed)

    def _report_java(self, message: str | None, percent: int | None = None) -> None:
        """Publish Java progress to the page label and the shared progress host."""
        if message:
            self.java_progress.emit(message)
        if self._progress_callback is not None:
            self._progress_callback(message, percent)

    def _download_java_runtime(self) -> None:
        name, version_id, component, major = self._java_requirement()
        if not component:
            return
        self._java_runtime_download_btn.setEnabled(False)
        self.java_progress.emit(f"Downloading Java {major}...")
        state = {"max": 100}

        def report_status(text: str) -> None:
            self._report_java(f"Java {major}: {text}")

        def report_max(value: int) -> None:
            state["max"] = max(1, int(value) or 100)

        def report_progress(value: int) -> None:
            done = max(0, min(int(value), state["max"]))
            percent = done * 100 // state["max"]
            self._report_java(f"Downloading Java {major}... {percent}%", percent)

        def work() -> str | None:
            return java_runtimes.ensure_runtime(
                component,
                _minecraft_dir(),
                callback={
                    "setStatus": report_status,
                    "setMax": report_max,
                    "setProgress": report_progress,
                },
            )

        def on_done(path: str | None) -> None:
            message = f"Java {major} is ready." if path else f"Java {major} could not be installed."
            self._report_java(message)
            self._report_java(None)
            self._refresh_java_runtime()

        def on_fail(error: Exception) -> None:
            self._report_java(f"Could not download Java {major}: {error}")
            self._report_java(None)
            self._refresh_java_runtime()

        self.runner.submit(work, on_done, on_fail)

    # ── Game ────────────────────────────────────────────────────────────────
    def _build_game_page(self) -> None:
        content = self._build_subpage_shell(
            "options_game",
            "Game",
            lambda: self._reset_fields(
                ("window_width", "window_height", "fullscreen", "enable_custom_skins"),
                self._sync_game_fields,
            ),
        )

        res_row = QWidget()
        res_layout = QHBoxLayout(res_row)
        res_layout.setContentsMargins(0, 0, 0, 0)
        res_layout.setSpacing(8)
        self._width_input = GlassLineEdit()
        self._width_input.setFixedWidth(90)
        self._width_input.editingFinished.connect(
            lambda: self._commit_positive_int(self._width_input, "window_width")
        )
        self._height_input = GlassLineEdit()
        self._height_input.setFixedWidth(90)
        self._height_input.editingFinished.connect(
            lambda: self._commit_positive_int(self._height_input, "window_height")
        )
        res_layout.addWidget(text_label("W:", theme.FONT_DETAIL, muted=True))
        res_layout.addWidget(self._width_input)
        res_layout.addWidget(text_label("H:", theme.FONT_DETAIL, muted=True))
        res_layout.addWidget(self._height_input)
        content.addWidget(
            _setting_row(
                "Default Window Resolution",
                "The window resolution applied when Minecraft starts up.",
                control=res_row,
            )
        )

        self._fullscreen_switch = GlassSwitch(
            "Start in fullscreen",
            bool(self._settings.get("fullscreen", False)),
            self._colors["btn_primary"],
        )
        self._fullscreen_switch.toggled.connect(lambda v: self._persist("fullscreen", v))
        self._switches.append(self._fullscreen_switch)
        content.addWidget(
            _setting_row(
                "Fullscreen",
                "Launch Minecraft directly in fullscreen mode.",
                control=self._fullscreen_switch,
            )
        )

        self._skins_switch = GlassSwitch(
            "Enable in-game skins and capes",
            bool(self._settings.get("enable_custom_skins", True)),
            self._colors["btn_primary"],
        )
        self._skins_switch.toggled.connect(lambda v: self._persist("enable_custom_skins", v))
        self._switches.append(self._skins_switch)
        content.addWidget(
            _setting_row(
                "Custom Skins",
                "Show Ely.by skins or your offline account's local skin and cape in-game.",
                control=self._skins_switch,
            )
        )

        self._prune_status = text_label("", theme.FONT_DETAIL, muted=True)
        self._prune_btn = GlassButton("Prune Cache")
        self._prune_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
        self._prune_btn.clicked.connect(self._prune_skin_cache)
        content.addWidget(
            _setting_row(
                "Skin Cache",
                "Remove old or excess cached Ely.by skin textures from disk.",
                control=self._prune_btn,
                extra=self._prune_status,
            )
        )
        content.addStretch(1)
        self._sync_game_fields()

    def _prune_skin_cache(self) -> None:
        from wisc.services import skins

        self._prune_btn.setEnabled(False)
        self._prune_status.setText("Pruning skin cache...")

        def on_done(count: int) -> None:
            self._prune_btn.setEnabled(True)
            self._prune_status.setText(
                f"Removed {count} old cached file{'s' if count != 1 else ''}."
                if count
                else "Skin cache is already clean."
            )

        def on_fail(err: Exception) -> None:
            self._prune_btn.setEnabled(True)
            self._prune_status.setText(f"Could not prune cache: {err}")

        self.runner.submit(skins.prune_skin_cache, on_done, on_fail)

    def _sync_game_fields(self) -> None:
        self._width_input.setText(str(self._settings.get("window_width", DEFAULT_SETTINGS["window_width"])))
        self._height_input.setText(str(self._settings.get("window_height", DEFAULT_SETTINGS["window_height"])))
        self._fullscreen_switch.setChecked(bool(self._settings.get("fullscreen", False)))
        self._skins_switch.setChecked(bool(self._settings.get("enable_custom_skins", True)))

    def _commit_positive_int(self, field: GlassLineEdit, key: str) -> None:
        try:
            value = int(field.text().strip())
        except ValueError:
            field.setText(str(self._settings.get(key, DEFAULT_SETTINGS[key])))
            return
        if value > 0:
            self._persist(key, value)
        else:
            field.setText(str(self._settings.get(key, DEFAULT_SETTINGS[key])))

    # ── Accounts ────────────────────────────────────────────────────────────
    def _build_accounts_page(self) -> None:
        content = self._build_subpage_shell("options_accounts", "Accounts")

        btn_bar = QWidget()
        btn_row = QHBoxLayout(btn_bar)
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(8)
        ely_btn = GlassButton("Add Ely.by Account", accented=True)
        ely_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
        ely_btn.clicked.connect(self._add_ely_account)
        btn_row.addWidget(ely_btn)
        add_btn = GlassButton("Add Offline Account")
        add_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
        add_btn.clicked.connect(self._add_offline_account)
        btn_row.addWidget(add_btn)

        content.addWidget(
            _setting_row(
                "Player Accounts",
                "Sign in with Ely.by or manage offline accounts.",
                control=btn_bar,
            )
        )

        self._accounts_box = QVBoxLayout()
        self._accounts_box.setSpacing(10)
        content.addLayout(self._accounts_box)
        content.addStretch(1)

    def _refresh_accounts_list(self) -> None:
        while self._accounts_box.count():
            item = self._accounts_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        accounts_data = load_accounts()
        accounts = accounts_data.get("accounts", []) if isinstance(accounts_data, dict) else []
        active = get_active_account()
        active_id = active.get("id")
        for account in accounts:
            acc_id = str(account.get("id", ""))
            username = str(account.get("username", "Player"))
            is_ely = account.get("type") == "ely"
            acc_type = "Ely.by" if is_ely else "Offline"
            is_active = acc_id == active_id

            actions = QWidget()
            row = QHBoxLayout(actions)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            if is_active:
                active_btn = GlassButton("Active", accented=True)
                active_btn.setEnabled(False)
                active_btn.setFixedHeight(theme.COMPACT_HEIGHT)
                row.addWidget(active_btn)
            else:
                use_btn = GlassButton("Use")
                use_btn.setFixedHeight(theme.COMPACT_HEIGHT)
                use_btn.clicked.connect(lambda checked=False, aid=acc_id: self._select_account(aid))
                row.addWidget(use_btn)

            if is_ely:
                relogin_btn = GlassButton("Re-login")
                relogin_btn.setFixedHeight(theme.COMPACT_HEIGHT)
                hint = str(account.get("email") or username)
                relogin_btn.clicked.connect(
                    lambda checked=False, h=hint: self._relogin_ely_account(h)
                )
                row.addWidget(relogin_btn)
            else:
                rename_btn = GlassButton("Rename")
                rename_btn.setFixedHeight(theme.COMPACT_HEIGHT)
                rename_btn.clicked.connect(
                    lambda checked=False, aid=acc_id, cur=username: self._rename_offline(aid, cur)
                )
                row.addWidget(rename_btn)

            if len(accounts) > 1:
                remove_btn = GlassButton("Remove")
                remove_btn.setFixedHeight(theme.COMPACT_HEIGHT)
                remove_btn.clicked.connect(lambda checked=False, aid=acc_id: self._delete_account(aid))
                row.addWidget(remove_btn)

            self._accounts_box.addWidget(
                _setting_row(username, f"{acc_type} account", control=actions)
            )

    def _add_ely_account(self) -> None:
        dialog = _ElyLoginDialog(self.runner, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.auth_result:
            res = dialog.auth_result
            add_or_update_account(
                {
                    "id": res["uuid"],
                    "type": "ely",
                    "username": res["username"],
                    "email": res.get("email", ""),
                    "uuid": res["uuid"],
                    "access_token": res["access_token"],
                    "client_token": res["client_token"],
                    "user_id": res.get("user_id"),
                },
                set_as_active=True,
            )
            self._refresh_accounts_list()
            self.accounts_changed.emit()

    def _relogin_ely_account(self, login_hint: str) -> None:
        dialog = _ElyLoginDialog(
            self.runner,
            login_hint=login_hint,
            title="Re-login with Ely.by",
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.auth_result:
            res = dialog.auth_result
            add_or_update_account(
                {
                    "id": res["uuid"],
                    "type": "ely",
                    "username": res["username"],
                    "email": res.get("email", ""),
                    "uuid": res["uuid"],
                    "access_token": res["access_token"],
                    "client_token": res["client_token"],
                    "user_id": res.get("user_id"),
                },
                set_as_active=True,
            )
            self._refresh_accounts_list()
            self.accounts_changed.emit()

    def _add_offline_account(self) -> None:
        name, ok = _GlassInputDialog.get_text(self, "Add Offline Account", "Player username:")
        if ok and name:
            add_or_update_account(
                {"id": uuid.uuid4().hex, "type": "offline", "username": name},
                set_as_active=True,
            )
            self._refresh_accounts_list()
            self.accounts_changed.emit()

    def _select_account(self, account_id: str) -> None:
        set_active_account(account_id)
        self._refresh_accounts_list()
        self.accounts_changed.emit()

    def _rename_offline(self, account_id: str, current: str) -> None:
        name, ok = _GlassInputDialog.get_text(self, "Rename Offline Account", "New username:", text=current)
        if ok and name:
            update_offline_username(account_id, name)
            self._refresh_accounts_list()
            self.accounts_changed.emit()

    def _delete_account(self, account_id: str) -> None:
        remove_account(account_id)
        self._refresh_accounts_list()
        self.accounts_changed.emit()

    # ── Launcher ────────────────────────────────────────────────────────────
    def _build_launcher_page(self) -> None:
        content = self._build_subpage_shell(
            "options_launcher",
            "Launcher",
            lambda: self._reset_fields(
                ("launch_action", "capture_logs", "discord_rpc"),
                self._sync_launcher_fields,
            ),
        )

        self._discord_switch = GlassSwitch(
            "Share activity",
            bool(self._settings.get("discord_rpc", True)),
            self._colors["btn_primary"],
        )
        self._discord_switch.toggled.connect(lambda v: self._persist("discord_rpc", v))
        self._switches.append(self._discord_switch)
        content.addWidget(
            _setting_row(
                "Discord Presence",
                "Show your launcher and Minecraft activity in Discord.",
                control=self._discord_switch,
            )
        )

        self._launch_combo = LauncherComboBox()
        self._launch_combo.setMinimumWidth(220)
        for key, text in (
            ("Hide launcher", "Hide launcher (Default)"),
            ("Keep launcher open", "Keep launcher open"),
            ("Close launcher", "Close launcher"),
        ):
            self._launch_combo.addItem(text, key)
        self._launch_combo.currentIndexChanged.connect(
            lambda: self._persist("launch_action", str(self._launch_combo.currentData()))
        )
        content.addWidget(
            _setting_row(
                "Action on Launch",
                "Choose what Wisc does when Minecraft starts.",
                control=self._launch_combo,
            )
        )

        self._logs_switch = GlassSwitch(
            "Record logs to disk",
            bool(self._settings.get("capture_logs", True)),
            self._colors["btn_primary"],
        )
        self._logs_switch.toggled.connect(lambda v: self._persist("capture_logs", v))
        self._switches.append(self._logs_switch)
        content.addWidget(
            _setting_row(
                "Log Capture",
                "Capture standard output to log files for crash inspection.",
                control=self._logs_switch,
            )
        )
        content.addStretch(1)
        self._sync_launcher_fields()

    def _sync_launcher_fields(self) -> None:
        self._discord_switch.setChecked(bool(self._settings.get("discord_rpc", True)))
        self._logs_switch.setChecked(bool(self._settings.get("capture_logs", True)))
        action = str(self._settings.get("launch_action", DEFAULT_SETTINGS["launch_action"]))
        idx = self._launch_combo.findData(action)
        if idx >= 0:
            self._launch_combo.blockSignals(True)
            self._launch_combo.setCurrentIndex(idx)
            self._launch_combo.blockSignals(False)

    # ── About & Updates ─────────────────────────────────────────────────────
    def _build_about_page(self) -> None:
        from wisc.services import updates as launcher_updates

        content = self._build_subpage_shell("options_about", "About")

        self._update_status_label = ElidedLabel(
            self._updater.status_message if self._updater else "Check for the latest launcher release."
        )
        self._update_status_label.setFont(ui_font(theme.FONT_BODY))
        self._update_status_label.setProperty("muted", True)
        self._update_status_label.setMinimumWidth(240)
        update_btns = QWidget()
        update_row = QHBoxLayout(update_btns)
        update_row.setContentsMargins(0, 0, 0, 0)
        update_row.setSpacing(8)

        self._check_updates_btn = GlassButton("Check for Updates", accented=True)
        self._check_updates_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
        self._check_updates_btn.clicked.connect(self._check_updates)
        update_row.addWidget(self._check_updates_btn)

        self._notes_btn = GlassButton("What's New")
        self._notes_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
        self._notes_btn.clicked.connect(self._show_release_notes)
        update_row.addWidget(self._notes_btn)

        self._view_update_btn = GlassButton("View Update", accented=True)
        self._view_update_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
        self._view_update_btn.clicked.connect(
            lambda: self._updater.show_dialog() if self._updater else None
        )
        self._view_update_btn.hide()
        update_row.addWidget(self._view_update_btn)

        self._cancel_update_btn = GlassButton("Cancel Download")
        self._cancel_update_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
        self._cancel_update_btn.clicked.connect(
            lambda: self._updater.cancel_download() if self._updater else None
        )
        self._cancel_update_btn.hide()
        update_row.addWidget(self._cancel_update_btn)

        # Reserve the update buttons' space so the row never reflows when they appear.
        for button in (self._view_update_btn, self._cancel_update_btn):
            policy = button.sizePolicy()
            policy.setRetainSizeWhenHidden(True)
            button.setSizePolicy(policy)

        content.addWidget(
            _setting_row(
                f"Wisc Launcher ({launcher_updates.version_label()})",
                "A clean, fast Minecraft launcher with themed glass surfaces and mod management.",
                control=update_btns,
                extra=self._update_status_label,
            )
        )

        self._auto_check_switch = GlassSwitch(
            "Check automatically",
            bool(self._settings.get("check_updates_automatically", True)),
            self._colors["btn_primary"],
        )
        self._auto_check_switch.toggled.connect(lambda v: self._persist("check_updates_automatically", v))
        self._switches.append(self._auto_check_switch)
        content.addWidget(
            _setting_row(
                "Automatic Update Checks",
                "Check for new Wisc releases in the background.",
                control=self._auto_check_switch,
            )
        )

        self._auto_dl_switch = GlassSwitch(
            "Download automatically",
            bool(self._settings.get("download_updates_automatically", False)),
            self._colors["btn_primary"],
        )
        self._auto_dl_switch.toggled.connect(lambda v: self._persist("download_updates_automatically", v))
        self._switches.append(self._auto_dl_switch)
        content.addWidget(
            _setting_row(
                "Automatic Downloads",
                "Download available updates automatically in the background.",
                control=self._auto_dl_switch,
            )
        )

        links_widget = QWidget()
        links_row = QHBoxLayout(links_widget)
        links_row.setContentsMargins(0, 0, 0, 0)
        links_row.setSpacing(8)
        for label, url in (
            ("GitHub", f"https://github.com/{launcher_updates.REPOSITORY}"),
            ("Discord", "https://discord.gg/wisc"),
            ("Support", "https://buymeacoffee.com/jaydeeeep"),
        ):
            btn = GlassButton(label)
            btn.setFixedHeight(theme.SEGMENT_HEIGHT)
            btn.clicked.connect(lambda checked=False, target=url: QDesktopServices.openUrl(QUrl(target)))
            links_row.addWidget(btn)
        content.addWidget(
            _setting_row(
                "Community & Links",
                "Source code, community support, and project links.",
                control=links_widget,
            )
        )

        mc_dir = _minecraft_dir()
        open_mc = GlassButton("Open Folder")
        open_mc.setFixedHeight(theme.SEGMENT_HEIGHT)
        open_mc.clicked.connect(lambda: _open_folder(mc_dir))
        content.addWidget(
            _setting_row(
                "Game Directory",
                str(mc_dir),
                control=open_mc,
            )
        )

        self._diagnostics_btn = GlassButton("Copy Info")
        self._diagnostics_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
        self._diagnostics_btn.clicked.connect(self._copy_diagnostics)
        content.addWidget(
            _setting_row(
                "Diagnostics",
                "Copy the launcher version, system, and Java details for a bug report.",
                control=self._diagnostics_btn,
            )
        )

        open_data = GlassButton("Open Folder")
        open_data.setFixedHeight(theme.SEGMENT_HEIGHT)
        open_data.clicked.connect(lambda: _open_folder(DATA_DIR))
        content.addWidget(
            _setting_row(
                "Launcher Data",
                str(DATA_DIR),
                control=open_data,
            )
        )

        reset_all_btn = GlassButton("Reset All Settings")
        reset_all_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
        reset_all_btn.clicked.connect(self._reset_all_settings)
        content.addWidget(
            _setting_row(
                "Reset Settings",
                "Restore all launcher settings and preferences to their default values.",
                control=reset_all_btn,
            )
        )
        content.addStretch(1)
        if self._updater is not None:
            self._on_updater_state_changed(self._updater.phase, self._updater.status_message)

    def _on_updater_state_changed(self, phase: str, message: str) -> None:
        if "options_about" not in self._subpages:
            return
        self._update_status_label.setText(message)
        self._check_updates_btn.setEnabled(phase not in ("checking", "downloading", "handing_off"))
        has_release = self._updater is not None and self._updater.release is not None
        self._view_update_btn.setVisible(has_release and phase != "checking")
        self._view_update_btn.setText("Restart Now" if phase == "ready" else "View Update")
        self._cancel_update_btn.setVisible(phase == "downloading")

    def _diagnostics_text(self) -> str:
        """Plain-text environment summary that is safe to paste into an issue."""
        import platform
        import sys as _sys

        from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR

        from wisc.core.paths import application_root
        from wisc.core.storage import get_data_dir

        version = "unknown"
        try:
            version = (application_root() / "VERSION").read_text(encoding="utf-8").strip() or "unknown"
        except OSError:
            pass
        _, _, component, major = self._java_requirement()
        java_path = str(self._settings.get("java_path", "")).strip()
        if java_path:
            selected_major = java_runtimes.java_major(java_path)
            selected = f"{java_path} (Java {selected_major or 'unknown'})"
        else:
            selected = "automatic"
        managed = java_runtimes.runtime_executable(component, _minecraft_dir())
        managed_text = managed or f"not installed (Java {major or 'unknown'} needed)"
        return "\n".join((
            f"Wisc {version}",
            f"System: {platform.platform()}",
            f"Python: {_sys.version.split()[0]}",
            f"Qt: {QT_VERSION_STR} (PyQt {PYQT_VERSION_STR})",
            f"Selected Java: {selected}",
            f"Managed Java: {managed_text}",
            f"Data: {get_data_dir()}",
        ))

    def _copy_diagnostics(self) -> None:
        try:
            text = self._diagnostics_text()
        except Exception as error:
            text = f"Wisc diagnostics unavailable: {error}"
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)
        self._diagnostics_btn.setText("Copied")
        QTimer.singleShot(1600, self._reset_diagnostics_button)

    def _reset_diagnostics_button(self) -> None:
        if hasattr(self, "_diagnostics_btn"):
            self._diagnostics_btn.setText("Copy Info")

    def keyPressEvent(self, event) -> None:
        dashboard = self._subpages.get("options")
        if event.key() == Qt.Key.Key_Escape and self.stack.currentWidget() is not dashboard:
            self.show_subpage("options")
            event.accept()
            return
        super().keyPressEvent(event)

    def _show_release_notes(self) -> None:
        if self._updater is not None:
            self._updater.show_release_notes()
            return
        from wisc.ui.updates import UpdateController
        controller = UpdateController(
            self.runner,
            parent_widget=lambda: self,
            notify=lambda *_: None,
            busy=lambda: False,
            close_window=lambda: None,
            accent=self._colors["btn_primary"],
        )
        controller.show_release_notes()

    def _reset_all_settings(self) -> None:
        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self,
            "Reset All Settings",
            "Restore all launcher settings to their defaults? Accounts and profiles will be kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._settings = DEFAULT_SETTINGS.copy()
        save_settings(self._settings)
        if "options_ui" in self._subpages:
            self._reset_appearance()
        if "options_java" in self._subpages:
            self._sync_java_fields()
        if "options_game" in self._subpages:
            self._sync_game_fields()
        if "options_launcher" in self._subpages:
            self._sync_launcher_fields()
        self.settings_changed.emit(dict(self._settings))

    def _check_updates(self) -> None:
        if self._updater is not None:
            self._updater.check(manual=True)
            return
        from wisc.services import updates as launcher_updates

        self._check_updates_btn.setEnabled(False)
        self._update_status_label.setText("Checking for updates...")

        def run_check():
            return launcher_updates.UpdateService().check(manual=True)

        def on_done(release) -> None:
            self._update_check_token = None
            self._check_updates_btn.setEnabled(True)
            if release is None:
                self._update_status_label.setText("You're up to date.")
            else:
                self._update_status_label.setText(f"Update available: {release.version}")

        def on_fail(error: Exception) -> None:
            self._update_check_token = None
            self._check_updates_btn.setEnabled(True)
            self._update_status_label.setText(f"Could not check for updates: {error}")

        self._update_check_token = self.runner.submit(run_check, on_done, on_fail)

    def apply_theme(self, colors: dict[str, str]) -> None:
        self._colors = colors
        accent = colors["btn_primary"]
        for card in self._cards:
            card.apply_accent(accent)
        for switch in self._switches:
            switch.set_accent(accent)
        self.update()

    def shutdown(self) -> None:
        if self._update_check_token is not None:
            self.runner.cancel(self._update_check_token)
            self._update_check_token = None
