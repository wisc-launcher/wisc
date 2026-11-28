"""Independent live Minecraft process log viewer window for the PyQt6 launcher."""

from __future__ import annotations

from collections import deque
from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QPlainTextEdit, QVBoxLayout, QWidget,
)

from wisc.core.credentials import redact_credentials
from wisc.core.paths import ASSETS_DIR
from wisc.ui import theme as theme
from wisc.ui.components import GlassButton, GlassPanel, text_label
from wisc.ui.skins import StatusDot
from wisc.ui.theme import MUTED, TEXT

MAX_LOG_LINES = 2000


def _line_color(line: str) -> str:
    low = line.lower()
    if any(token in low for token in ("error", "exception", "fatal", "crash")):
        return "#ef5350"
    if "warn" in low:
        return "#ffca28"
    if "info" in low:
        return "#90caf9"
    return "#cfd8dc"


class GameLogsWindow(QWidget):
    """Independent top-level glass log viewer window for live Minecraft output."""

    def __init__(
        self,
        *,
        accent: str = theme.DEFAULT_ACCENT,
        on_notify: Callable[[str, str, str | None], None] | None = None,
    ):
        super().__init__(None)
        self._accent = accent
        self._on_notify = on_notify
        self._buffer: deque[str] = deque(maxlen=MAX_LOG_LINES)
        self._running = False
        self._auto_scroll = True

        self.setWindowTitle("Wisc — Game Logs")
        self.setWindowIcon(QIcon(str(ASSETS_DIR / "icons" / "wisc.ico")))
        self.resize(860, 540)
        self.setMinimumSize(620, 380)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        panel = GlassPanel(radius=theme.RADIUS_PANEL)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(20, 14, 20, 16)
        panel_layout.setSpacing(12)

        self._header = QWidget()
        header = QHBoxLayout(self._header)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        self._status_dot = StatusDot()
        header.addWidget(self._status_dot)
        header.addWidget(text_label("Game Logs", theme.FONT_SECTION_HEADING, bold=True))
        self._status_label = text_label("Idle", theme.FONT_DETAIL, muted=True)
        header.addWidget(self._status_label)
        header.addStretch(1)

        self._auto_btn = GlassButton("Auto-scroll")
        self._auto_btn.setCheckable(True)
        self._auto_btn.setChecked(True)
        self._auto_btn.setFixedHeight(theme.COMPACT_HEIGHT)
        self._auto_btn.toggled.connect(self._set_auto_scroll)
        header.addWidget(self._auto_btn)

        copy_btn = GlassButton("Copy")
        copy_btn.setFixedHeight(theme.COMPACT_HEIGHT)
        copy_btn.clicked.connect(self.copy_logs)
        header.addWidget(copy_btn)

        clear_btn = GlassButton("Clear")
        clear_btn.setFixedHeight(theme.COMPACT_HEIGHT)
        clear_btn.clicked.connect(self.clear_logs)
        header.addWidget(clear_btn)

        min_btn = GlassButton("\u2013")
        min_btn.setFixedSize(theme.COMPACT_HEIGHT, theme.COMPACT_HEIGHT)
        min_btn.setToolTip("Minimize")
        min_btn.clicked.connect(self.showMinimized)
        header.addWidget(min_btn)

        max_btn = GlassButton("\u25a1")
        max_btn.setFixedSize(theme.COMPACT_HEIGHT, theme.COMPACT_HEIGHT)
        max_btn.setToolTip("Maximize / Restore")
        max_btn.clicked.connect(self._toggle_maximized)
        header.addWidget(max_btn)

        close_btn = GlassButton("Close", accented=True)
        close_btn.setFixedHeight(theme.COMPACT_HEIGHT)
        close_btn.clicked.connect(self.hide)
        header.addWidget(close_btn)
        panel_layout.addWidget(self._header)

        self._editor = QPlainTextEdit()
        self._editor.setReadOnly(True)
        self._editor.setMaximumBlockCount(MAX_LOG_LINES)
        self._editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        mono = QFont("Consolas", 10)
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._editor.setFont(mono)
        self._editor.setStyleSheet(
            f"QPlainTextEdit {{"
            f" background-color: rgba(10, 12, 18, 200);"
            f" color: {TEXT};"
            f" border: 1px solid rgba(255, 255, 255, 22);"
            f" border-radius: {theme.RADIUS_BUTTON}px;"
            f" padding: 10px;"
            f"}}"
        )
        panel_layout.addWidget(self._editor, 1)
        root.addWidget(panel)

        self._drag_offset = None
        self.set_running(False)

    def mousePressEvent(self, event) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._header.geometry().contains(event.position().toPoint())
            and not isinstance(self.childAt(event.position().toPoint()), GlassButton)
        ):
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def _toggle_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _set_auto_scroll(self, enabled: bool) -> None:
        self._auto_scroll = bool(enabled)
        if enabled:
            bar = self._editor.verticalScrollBar()
            bar.setValue(bar.maximum())

    def set_accent(self, accent: str) -> None:
        self._accent = accent
        if self._running:
            self._status_dot.set_color(accent)

    def set_running(self, running: bool) -> None:
        self._running = bool(running)
        self._status_dot.set_color(self._accent if running else MUTED)
        self._status_label.setText("Running" if running else "Idle")

    def append_line(self, line: str, sensitive_values: tuple[str, ...] = ()) -> None:
        cleaned = redact_credentials(str(line).rstrip("\r\n"), sensitive_values)
        if not cleaned:
            return
        self._buffer.append(cleaned)
        bar = self._editor.verticalScrollBar()
        at_bottom = self._auto_scroll or bar.value() >= bar.maximum() - 4
        cursor = self._editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(_line_color(cleaned)))
        if self._editor.document().blockCount() > 1 or self._editor.toPlainText():
            cursor.insertText("\n")
        cursor.insertText(cleaned, fmt)
        if at_bottom:
            bar.setValue(bar.maximum())

    def copy_logs(self) -> None:
        if not self._buffer:
            if self._on_notify:
                self._on_notify("There are no logs to copy yet.", "info", "Logs")
            return
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText("\n".join(self._buffer))
            if self._on_notify:
                self._on_notify("Copied logs to clipboard.", "success", "Logs copied")

    def clear_logs(self) -> None:
        self._buffer.clear()
        self._editor.clear()
        if self._on_notify:
            self._on_notify("The log view has been cleared.", "info", "Logs cleared")

    def lines(self) -> list[str]:
        return list(self._buffer)


GameLogsDialog = GameLogsWindow
