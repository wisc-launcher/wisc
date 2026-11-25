"""Window-owned progress shared by Qt pages; updates run on the GUI thread."""

from dataclasses import dataclass

from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QProgressBar, QVBoxLayout, QWidget

from wisc.ui import theme as theme
from wisc.ui.components import ElidedLabel, GlassButton, GlassPanel, text_label
from wisc.ui.theme import ui_font


@dataclass(frozen=True)
class _Operation:
    label: str
    value: int | None
    detail: str
    cancelable: bool | None
    priority: int
    show_text: bool


class ProgressHost(QWidget):
    """Keep one bottom track visible, retaining progress across navigation."""

    cancel_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._operations: dict[str, _Operation] = {}
        self._current_source: str | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.PAGE_MARGINS[0], 4, theme.PAGE_MARGINS[2], 8)
        layout.setSpacing(0)
        self.text_row = GlassPanel(parent, radius=theme.RADIUS_BUTTON, opacity=0.82)
        self.text_row.setFixedHeight(36)
        header = QHBoxLayout(self.text_row)
        header.setContentsMargins(12, 4, 8, 4)
        header.setSpacing(12)
        self.status = ElidedLabel()
        self.status.setFont(ui_font(theme.FONT_BODY))
        self.status.setProperty("progressStatus", True)
        header.addWidget(self.status, 1)
        self.detail = text_label("", theme.FONT_DETAIL)
        self.detail.setStyleSheet("color: #FFFFFF;")
        self.detail.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.detail)
        self.cancel = GlassButton("Cancel")
        self.cancel.setFixedHeight(28)
        self.cancel.clicked.connect(self._cancel)
        header.addWidget(self.cancel)
        if parent is None:
            layout.addWidget(self.text_row)
        else:
            parent.installEventFilter(self)
        self.bar = QProgressBar()
        self.bar.setAccessibleName("Launcher progress")
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        layout.addWidget(self.bar)
        self._render()

    def _position_overlay(self) -> None:
        parent = self.parentWidget()
        if parent is None or self.text_row.parentWidget() is not parent:
            return
        left, _, right, _ = theme.PAGE_MARGINS
        width = max(0, parent.width() - left - right)
        height = self.text_row.height()
        y = max(0, self.y() - height - 4)
        self.text_row.setGeometry(left, y, width, height)
        if self.text_row.isVisible():
            self.text_row.raise_()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self._position_overlay()
        return super().eventFilter(watched, event)

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._position_overlay()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_overlay()

    def set_operation(self, source: str, label: str | None, value: int | None = None, *,
                      detail: str = "", cancelable: bool | None = None,
                      priority: int = 40, show_text: bool = True) -> None:
        """Update a source's 0–1000 progress, or remove it with an empty label."""
        if label:
            value = None if value is None else max(0, min(1000, value))
            self._operations[source] = _Operation(label, value, detail, cancelable, priority, show_text)
        else:
            self._operations.pop(source, None)
        self._render()

    def _cancel(self) -> None:
        if self._current_source is None:
            return
        operation = self._operations.get(self._current_source)
        if operation is not None and operation.cancelable:
            self.cancel_requested.emit(self._current_source)

    def _render(self) -> None:
        if not self._operations:
            self._current_source = None
            self.text_row.hide()
            self.status.setText("")
            self.detail.setText("")
            self.cancel.hide()
            self.bar.setRange(0, 1000)
            self.bar.setValue(0)
            return
        # Later starts win equal priorities; updates keep their original ordering.
        self._current_source = max(reversed(self._operations), key=lambda key: self._operations[key].priority)
        operation = self._operations[self._current_source]
        self.text_row.setVisible(operation.show_text)
        self.status.setText(operation.label)
        details = []
        if operation.value is not None:
            details.append(f"{operation.value / 10:.0f}%")
        if operation.detail:
            details.append(operation.detail)
        if len(self._operations) > 1:
            details.append(f"+{len(self._operations) - 1} more")
        self.detail.setText(" \u00b7 ".join(details))
        self.detail.setVisible(bool(details))
        self.cancel.setVisible(operation.cancelable is not None)
        self.cancel.setEnabled(bool(operation.cancelable))
        self.bar.setRange(0, 0 if operation.value is None else 1000)
        if operation.value is not None:
            self.bar.setValue(operation.value)
        self._position_overlay()
