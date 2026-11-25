"""Qt Settings / Options dashboard and subpages."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QByteArray, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QAbstractButton,
    QColorDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
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
    DEFAULT_CUSTOM_ACCENT,
    DEFAULT_THEME,
    get_theme_names,
    normalize_accent,
)
from wisc.ui import theme as theme
from wisc.ui.components import (
    ElidedLabel,
    GlassButton,
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
    """Vector illustration from .assets/settings/<name>.svg tinted with the active accent."""

    def __init__(self, name: str, accent: str, size: int = 56, parent: QWidget | None = None):
        super().__init__(parent)
        self._name = name
        self._accent = normalize_accent(accent) or theme.DEFAULT_ACCENT
        self._renderer: QSvgRenderer | None = None
        self.setFixedSize(size, size)
        self._reload()

    def set_accent(self, accent: str) -> None:
        normalized = normalize_accent(accent) or theme.DEFAULT_ACCENT
        if normalized != self._accent:
            self._accent = normalized
            self._reload()
            self.update()

    def _reload(self) -> None:
        svg_path = ASSETS_DIR / "settings" / f"{self._name}.svg"
        if not svg_path.is_file():
            self._renderer = None
            return
        raw = svg_path.read_text(encoding="utf-8").replace("#46BA34", self._accent)
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

    def __init__(self, category_id: str, title: str, description: str, art_name: str,
                 accent: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.category_id = category_id
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(112)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)

        self.art = SettingsArt(art_name, accent, size=48, parent=self)
        layout.addWidget(self.art, 0, Qt.AlignmentFlag.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)
        text_col.addWidget(text_label(title, theme.FONT_SUBHEADING, bold=True))
        desc = text_label(description, theme.FONT_DETAIL, muted=True)
        desc.setWordWrap(True)
        text_col.addWidget(desc)
        text_col.addStretch(1)
        layout.addLayout(text_col, 1)

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

    def __init__(self, runner: ServiceRunner, colors: dict[str, str], parent: QWidget | None = None):
        super().__init__(parent)
        self.runner = runner
        self._colors = colors
        self._settings = load_settings()
        self._max_ram = _system_memory_mb()
        self._cards: list[OptionCard] = []
        self._switches: list[GlassSwitch] = []
        self._theme_dot: QWidget | None = None
        self._theme_badge_label: QLabel | None = None
        self._update_check_token: int | None = None
        self._reveal = StaggeredReveal(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(*theme.PAGE_MARGINS)
        root.setSpacing(theme.PAGE_SPACING)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        self._subpages: dict[str, QWidget] = {}
        self._build_dashboard()
        self._build_appearance_page()
        self._build_java_page()
        self._build_game_page()
        self._build_accounts_page()
        self._build_launcher_page()
        self._build_updates_page()
        self._build_about_page()
        self.show_subpage("options", animate=False)

    def show_subpage(self, key: str, *, animate: bool = True) -> None:
        widget = self._subpages.get(key) or self._subpages["options"]
        if key == "options_accounts":
            self._refresh_accounts_list()
        self.stack.setCurrentWidget(widget)
        if animate and self.isVisible():
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

        header = QHBoxLayout()
        header.setSpacing(12)
        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        title_col.addWidget(text_label("Settings", theme.FONT_PAGE_TITLE, bold=True))
        title_col.addWidget(text_label("Make Wisc feel at home.", theme.FONT_BODY, muted=True))
        header.addLayout(title_col, 1)

        badge = GlassPanel(radius=theme.RADIUS_BUTTON)
        badge_row = QHBoxLayout(badge)
        badge_row.setContentsMargins(12, 8, 12, 8)
        badge_row.setSpacing(8)
        self._theme_dot = QWidget()
        self._theme_dot.setFixedSize(8, 8)
        self._update_theme_dot()
        badge_row.addWidget(self._theme_dot)
        current_theme = load_theme_choice(get_theme_names())
        self._theme_badge_label = text_label(current_theme, theme.FONT_DETAIL, muted=True)
        badge_row.addWidget(self._theme_badge_label)
        header.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)
        content.addLayout(header)

        hero = GlassPanel(radius=theme.RADIUS_CARD)
        hero_row = QHBoxLayout(hero)
        hero_row.setContentsMargins(22, 18, 22, 18)
        hero_row.setSpacing(18)
        hero_col = QVBoxLayout()
        hero_col.setSpacing(8)
        hero_col.addWidget(text_label("Color studio", theme.FONT_DIALOG_TITLE, bold=True))
        hero_col.addWidget(
            text_label("Dial in your own accent and switch Minecraft palettes anytime.", theme.FONT_BODY, muted=True)
        )
        customize_btn = GlassButton("Customize your colors", accented=True)
        customize_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
        customize_btn.clicked.connect(lambda: self.show_subpage("options_ui"))
        hero_col.addWidget(customize_btn, 0, Qt.AlignmentFlag.AlignLeft)
        hero_row.addLayout(hero_col, 1)
        hero_art = SettingsArt("appearance", self._colors["btn_primary"], size=68, parent=hero)
        self._hero_art = hero_art
        hero_row.addWidget(hero_art, 0, Qt.AlignmentFlag.AlignVCenter)
        content.addWidget(hero)

        categories = [
            ("options_ui", "Appearance", "Your colors, your atmosphere", "appearance"),
            ("options_java", "Java & Memory", "Java executable and allocated RAM", "java"),
            ("options_game", "Game", "Window size, fullscreen and skins", "game"),
            ("options_accounts", "Accounts", "Manage players, sign-ins and skins", "accounts"),
            ("options_launcher", "Launcher", "Launch behavior, Discord and logs", "launcher"),
            ("options_updates", "Updates", "Check for the latest Wisc release", "updates"),
        ]
        grid = QGridLayout()
        grid.setSpacing(12)
        for index, (cat_id, title, desc, art) in enumerate(categories):
            card = OptionCard(cat_id, title, desc, art, self._colors["btn_primary"])
            card.clicked.connect(lambda checked=False, target=cat_id: self.show_subpage(target))
            self._cards.append(card)
            grid.addWidget(card, index // 3, index % 3)
        for col in range(3):
            grid.setColumnStretch(col, 1)
        content.addLayout(grid)

        footer = GlassPanel(radius=theme.RADIUS_CARD)
        footer_row = QHBoxLayout(footer)
        footer_row.setContentsMargins(18, 12, 18, 12)
        footer_row.setSpacing(12)
        brand_col = QVBoxLayout()
        brand_col.setSpacing(2)
        brand = text_label("Wisc", theme.FONT_SUBHEADING, pixel=True)
        brand_col.addWidget(brand)
        brand_col.addWidget(text_label("A little help for your next adventure.", theme.FONT_DETAIL, muted=True))
        footer_row.addLayout(brand_col, 1)
        about_btn = GlassButton("About Wisc")
        about_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
        about_btn.clicked.connect(lambda: self.show_subpage("options_about"))
        footer_row.addWidget(about_btn)
        content.addWidget(footer)
        content.addStretch(1)

    def _update_theme_dot(self) -> None:
        if self._theme_dot is not None:
            self._theme_dot.setStyleSheet(
                f"background: {self._colors['btn_primary']}; border-radius: 4px;"
            )

    # ── Appearance ──────────────────────────────────────────────────────────
    def _build_appearance_page(self) -> None:
        content = self._build_subpage_shell("options_ui", "Appearance", self._reset_appearance)

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
                "Start with a favorite palette, or return to your saved Custom color.",
                control=self._theme_combo,
            )
        )

        custom_row = QWidget()
        custom_layout = QHBoxLayout(custom_row)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        custom_layout.setSpacing(8)
        self._accent_input = GlassLineEdit()
        self._accent_input.setFixedWidth(120)
        self._accent_input.setText(str(self._settings.get("custom_accent", DEFAULT_CUSTOM_ACCENT)))
        pick_btn = GlassButton("Pick color")
        pick_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
        pick_btn.clicked.connect(self._pick_custom_color)
        apply_btn = GlassButton("Apply", accented=True)
        apply_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
        apply_btn.clicked.connect(self._apply_custom_accent)
        custom_layout.addWidget(self._accent_input)
        custom_layout.addWidget(pick_btn)
        custom_layout.addWidget(apply_btn)
        content.addWidget(
            _setting_row(
                "Custom color",
                "Choose a hex accent for buttons, selections, and focus.",
                control=custom_row,
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
        if self._theme_badge_label is not None:
            self._theme_badge_label.setText(name)
        self.theme_requested.emit(name)

    def _pick_custom_color(self) -> None:
        initial = QColor(normalize_accent(self._accent_input.text()) or self._colors["btn_primary"])
        chosen = QColorDialog.getColor(initial, self, "Choose Custom Accent")
        if chosen.isValid():
            self._accent_input.setText(chosen.name().upper())
            self._apply_custom_accent()

    def _apply_custom_accent(self) -> None:
        normalized = normalize_accent(self._accent_input.text())
        if not normalized:
            return
        self._accent_input.setText(normalized)
        self._persist("custom_accent", normalized)
        save_theme_choice("Custom")
        idx = self._theme_combo.findData("Custom")
        if idx >= 0:
            self._theme_combo.blockSignals(True)
            self._theme_combo.setCurrentIndex(idx)
            self._theme_combo.blockSignals(False)
        if self._theme_badge_label is not None:
            self._theme_badge_label.setText("Custom")
        self.theme_requested.emit("Custom")

    def _reset_appearance(self) -> None:
        self._persist("enable_orbs", DEFAULT_SETTINGS["enable_orbs"])
        self._persist("custom_accent", DEFAULT_SETTINGS["custom_accent"])
        self._orbs_switch.setChecked(bool(DEFAULT_SETTINGS["enable_orbs"]))
        self._accent_input.setText(str(DEFAULT_SETTINGS["custom_accent"]))
        save_theme_choice(DEFAULT_THEME)
        idx = self._theme_combo.findData(DEFAULT_THEME)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)

    # ── Java & Memory ───────────────────────────────────────────────────────
    def _build_java_page(self) -> None:
        content = self._build_subpage_shell(
            "options_java",
            "Java & Memory",
            lambda: self._reset_fields(("ram_mb", "java_path"), self._sync_java_fields),
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
        self._java_input.setMinimumWidth(260)
        self._java_input.setPlaceholderText("System Java (automatic)")
        self._java_input.textChanged.connect(lambda text: self._persist("java_path", text.strip()))
        browse_btn = GlassButton("Browse")
        browse_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
        browse_btn.clicked.connect(self._browse_java)
        java_layout.addWidget(self._java_input, 1)
        java_layout.addWidget(browse_btn)

        content.addWidget(
            _setting_row(
                "Java Executable",
                "Leave empty to use system Java, or select your java.exe.",
                control=java_row,
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
        content.addStretch(1)
        self._sync_game_fields()

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

        add_btn = GlassButton("Add Offline Account", accented=True)
        add_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
        add_btn.clicked.connect(self._add_offline_account)
        content.addWidget(
            _setting_row(
                "Player Accounts",
                "Switch active accounts, rename offline players, or remove saved accounts.",
                control=add_btn,
            )
        )

        self._accounts_box = QVBoxLayout()
        self._accounts_box.setSpacing(10)
        content.addLayout(self._accounts_box)
        content.addStretch(1)
        self._refresh_accounts_list()

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
            acc_type = "Ely.by" if account.get("type") == "ely" else "Offline"
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

            if account.get("type") == "offline":
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

    def _add_offline_account(self) -> None:
        name, ok = QInputDialog.getText(self, "Add Offline Account", "Player username:")
        if ok and name.strip():
            add_or_update_account(
                {"id": uuid.uuid4().hex, "type": "offline", "username": name.strip()},
                set_as_active=True,
            )
            self._refresh_accounts_list()

    def _select_account(self, account_id: str) -> None:
        set_active_account(account_id)
        self._refresh_accounts_list()

    def _rename_offline(self, account_id: str, current: str) -> None:
        name, ok = QInputDialog.getText(self, "Rename Offline Account", "New username:", text=current)
        if ok and name.strip():
            update_offline_username(account_id, name.strip())
            self._refresh_accounts_list()

    def _delete_account(self, account_id: str) -> None:
        remove_account(account_id)
        self._refresh_accounts_list()

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

    # ── Updates ─────────────────────────────────────────────────────────────
    def _build_updates_page(self) -> None:
        from wisc.services import updates as launcher_updates

        content = self._build_subpage_shell("options_updates", "Updates")

        self._update_status_label = text_label("Check for the latest launcher release.", theme.FONT_BODY, muted=True)
        self._check_updates_btn = GlassButton("Check for Updates", accented=True)
        self._check_updates_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
        self._check_updates_btn.clicked.connect(self._check_updates)
        content.addWidget(
            _setting_row(
                f"Wisc {launcher_updates.version_label()}",
                "Current launcher version and release status.",
                control=self._check_updates_btn,
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
        content.addStretch(1)

    def _check_updates(self) -> None:
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

    # ── About ───────────────────────────────────────────────────────────────
    def _build_about_page(self) -> None:
        from wisc.services import updates as launcher_updates

        content = self._build_subpage_shell("options_about", "About Wisc")

        content.addWidget(
            _setting_row(
                f"Wisc Launcher ({launcher_updates.version_label()})",
                "A clean, fast Minecraft launcher with themed glass surfaces and mod management.",
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
        content.addStretch(1)

    def apply_theme(self, colors: dict[str, str]) -> None:
        self._colors = colors
        accent = colors["btn_primary"]
        self._update_theme_dot()
        self._hero_art.set_accent(accent)
        for card in self._cards:
            card.apply_accent(accent)
        for switch in self._switches:
            switch.set_accent(accent)
        self.update()

    def shutdown(self) -> None:
        if self._update_check_token is not None:
            self.runner.cancel(self._update_check_token)
            self._update_check_token = None
