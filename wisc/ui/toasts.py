"""Non-blocking floating toast notifications for the PyQt6 launcher."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QApplication, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from wisc.core.credentials import redact_credentials
from wisc.ui import theme as theme
from wisc.ui.components import GlassButton, GlassPanel, text_label

MAX_VISIBLE_TOASTS = 4
TOAST_WIDTH = 340
TOAST_MARGIN = 18
TOAST_GAP = 10

_KIND_COLORS = {
    "success": "#68d391",
    "warning": "#f6ad55",
    "error": "#fc8181",
}


@dataclass(frozen=True)
class _ToastSpec:
    message: str
    kind: str
    title: str | None
    duration_ms: int


class _ToastCard(GlassPanel):
    dismissed = pyqtSignal(object)

    def __init__(self, spec: _ToastSpec, accent: str, parent: QWidget):
        super().__init__(parent, radius=theme.RADIUS_BUTTON)
        self._accent_color = QColor(_KIND_COLORS.get(spec.kind, accent))
        self.setFixedWidth(TOAST_WIDTH)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(14, 10, 10, 10)
        outer.setSpacing(10)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)
        if spec.title:
            title_lbl = text_label(spec.title, theme.FONT_DETAIL, bold=True)
            title_lbl.setWordWrap(True)
            title_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            text_col.addWidget(title_lbl)
        body_lbl = text_label(spec.message, theme.FONT_DETAIL, muted=bool(spec.title))
        body_lbl.setWordWrap(True)
        body_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        text_col.addWidget(body_lbl)
        outer.addLayout(text_col, 1)

        close_btn = GlassButton("\u00d7", radius=theme.RADIUS_BUTTON)
        close_btn.setFixedSize(22, 22)
        close_btn.clicked.connect(self._close)
        outer.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignTop)

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)

        self._anim = QPropertyAnimation(self._effect, b"opacity", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._close)
        if spec.duration_ms > 0:
            self._timer.start(spec.duration_ms)
        self._closing = False

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._accent_color)
        painter.drawRoundedRect(0, 6, 3, max(8, self.height() - 12), 1.5, 1.5)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._close()
            event.accept()
            return
        super().mousePressEvent(event)

    def _close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._timer.stop()
        self._anim.stop()
        self._anim.setDuration(140)
        self._anim.setStartValue(self._effect.opacity())
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(lambda: self.dismissed.emit(self))
        self._anim.start()


class ToastHost(QWidget):
    """Manages stacked toast notifications anchored to the bottom-right of a parent widget."""

    def __init__(self, parent: QWidget, accent: str = theme.DEFAULT_ACCENT):
        super().__init__(parent)
        self._accent = accent
        self._queue: deque[_ToastSpec] = deque()
        self._active: list[_ToastCard] = []
        self._bottom_offset = 0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()

    def set_accent(self, accent: str) -> None:
        self._accent = accent

    def set_bottom_offset(self, offset: int) -> None:
        self._bottom_offset = max(0, int(offset))
        self.reposition()

    def show_toast(
        self,
        message: str,
        kind: str = "info",
        title: str | None = None,
        *,
        duration_ms: int = 4200,
    ) -> None:
        clean = redact_credentials(str(message or "")).strip()
        if not clean:
            return
        self._queue.append(_ToastSpec(clean, kind, title, duration_ms))
        self._drain()

    def clear(self) -> None:
        self._queue.clear()
        for card in list(self._active):
            card.hide()
            card.deleteLater()
        self._active.clear()
        self.hide()

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None or not self._active:
            return
        right = parent.width() - TOAST_MARGIN
        y = parent.height() - TOAST_MARGIN - self._bottom_offset
        for card in reversed(self._active):
            card.adjustSize()
            h = card.sizeHint().height()
            y -= h
            card.setGeometry(max(TOAST_MARGIN, right - TOAST_WIDTH), max(TOAST_MARGIN, y), TOAST_WIDTH, h)
            card.raise_()
            y -= TOAST_GAP

    def _drain(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        while self._queue and len(self._active) < MAX_VISIBLE_TOASTS:
            spec = self._queue.popleft()
            card = _ToastCard(spec, self._accent, parent)
            card.dismissed.connect(self._on_dismissed)
            card.show()
            self._active.append(card)
        self.reposition()

    def _on_dismissed(self, card: _ToastCard) -> None:
        if card in self._active:
            self._active.remove(card)
        card.hide()
        card.deleteLater()
        self._drain()
        self.reposition()
