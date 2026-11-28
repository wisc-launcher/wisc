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
from wisc.ui.components import GlassButton, GlassLineEdit, GlassPanel, text_label
from wisc.ui.skins import StatusDot
from wisc.ui.theme import MUTED, TEXT

MAX_LOG_LINES = 2000
ERROR_TOKENS = ("error", "exception", "fatal", "crash")


def _is_error(line: str) -> bool:
    low = line.lower()
    return any(token in low for token in ERROR_TOKENS)


def _line_color(line: str) -> str:
    low = line.lower()
    if _is_error(line):
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
        self._error_blocks: list[int] = []
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

        filters = QHBoxLayout()
        filters.setContentsMargins(0, 0, 0, 0)
        filters.setSpacing(8)
        self._filter = GlassLineEdit(search_icon=True)
        self._filter.setPlaceholderText("Filter logs")
        self._filter.setAccessibleName("Filter logs")
        self._filter.setClearButtonEnabled(True)
        self._filter.setFixedHeight(theme.COMPACT_HEIGHT)
        self._filter.textChanged.connect(lambda _text: self._render())
        filters.addWidget(self._filter, 1)
        self._errors_btn = GlassButton("Errors")
        self._errors_btn.setCheckable(True)
        self._errors_btn.setToolTip("Show error lines only")
        self._errors_btn.setFixedHeight(theme.COMPACT_HEIGHT)
        self._errors_btn.toggled.connect(lambda _on: self._render())
        filters.addWidget(self._errors_btn)
        self._jump_btn = GlassButton("First error")
        self._jump_btn.setFixedHeight(theme.COMPACT_HEIGHT)
        self._jump_btn.clicked.connect(self.jump_to_first_error)
        filters.addWidget(self._jump_btn)
        self._count_label = text_label("", theme.FONT_DETAIL, muted=True)
        self._count_label.setMinimumWidth(170)
        filters.addWidget(self._count_label)
        panel_layout.addLayout(filters)

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
        self._update_count()
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

    # ── Filtering ───────────────────────────────────────────────────────────

    def _matches(self, line: str) -> bool:
        if self._errors_btn.isChecked() and not _is_error(line):
            return False
        query = self._filter.text().strip().casefold()
        if not query:
            return True
        return query in line.casefold()

    def _insert_line(self, line: str) -> None:
        cursor = self._editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if self._editor.toPlainText():
            cursor.insertText("\n")
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(_line_color(line)))
        cursor.insertText(line, fmt)

    def _render(self) -> None:
        self._editor.clear()
        self._error_blocks.clear()
        block = -1
        for line in self._buffer:
            if not self._matches(line):
                continue
            self._insert_line(line)
            block += 1
            if _is_error(line):
                self._error_blocks.append(block)
        self._update_count()
        if self._auto_scroll:
            bar = self._editor.verticalScrollBar()
            bar.setValue(bar.maximum())

    def _update_count(self) -> None:
        errors = sum(1 for line in self._buffer if _is_error(line))
        parts = [f"{len(self._buffer)} lines", f"{errors} error{'s' if errors != 1 else ''}"]
        if self._filter.text().strip() or self._errors_btn.isChecked():
            shown = sum(1 for line in self._buffer if self._matches(line))
            parts.append(f"{shown} shown")
        self._count_label.setText(" \u00b7 ".join(parts))

    def jump_to_first_error(self) -> None:
        if not self._error_blocks:
            if self._on_notify:
                self._on_notify("This log has no error lines.", "info", "Logs")
            return
        block = self._editor.document().findBlockByNumber(self._error_blocks[0])
        if not block.isValid():
            return
        cursor = QTextCursor(block)
        self._editor.setTextCursor(cursor)
        self._editor.centerCursor()

    # ── Content ─────────────────────────────────────────────────────────────

    def append_line(self, line: str, sensitive_values: tuple[str, ...] = ()) -> None:
        cleaned = redact_credentials(str(line).rstrip("\r\n"), sensitive_values)
        if not cleaned:
            return
        self._buffer.append(cleaned)
        bar = self._editor.verticalScrollBar()
        at_bottom = self._auto_scroll or bar.value() >= bar.maximum() - 4
        if self._matches(cleaned):
            self._insert_line(cleaned)
            if _is_error(cleaned):
                self._error_blocks.append(self._editor.document().blockCount() - 1)
            if at_bottom:
                bar.setValue(bar.maximum())
        self._update_count()

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
        self._error_blocks.clear()
        self._editor.clear()
        self._update_count()
        if self._on_notify:
            self._on_notify("The log view has been cleared.", "info", "Logs cleared")

    def lines(self) -> list[str]:
        return list(self._buffer)


GameLogsDialog = GameLogsWindow
