"""On-demand Qt presentation of the existing Minecraft software renderer."""

from PyQt6.QtCore import QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QPainter, QPalette, QPen, QPixmap
from PyQt6.QtWidgets import QSizePolicy, QWidget

from wisc.ui import theme as theme
from wisc.ui.tasks import LatestServiceTask, ServiceRunner


class SkinPreview(QWidget):
    rotated = pyqtSignal()
    render_failed = pyqtSignal(str)

    def __init__(self, runner: ServiceRunner, parent: QWidget | None = None):
        super().__init__(parent)
        self._runner = runner
        self._renderer = None
        self._frame = QPixmap()
        self._task = LatestServiceTask(runner)
        self._dirty = False
        self._generation = 0
        self._drag = None
        self.yaw, self.pitch = -25.0, 10.0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._render)
        self.setMinimumSize(240, 260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Skin preview")
        self.setAccessibleDescription("Drag or use arrow keys to rotate. Double-click or press Home to reset.")

    def sizeHint(self) -> QSize:
        return QSize(300, 330)

    def set_renderer(self, renderer) -> None:
        self.suspend()
        self._renderer = renderer
        self._frame = QPixmap()
        self.update()
        self.request_frame()

    def set_view(self, yaw: float, pitch: float) -> None:
        self.yaw, self.pitch = yaw % 360.0, max(-35.0, min(35.0, pitch))
        self.request_frame()

    def request_frame(self) -> None:
        self._dirty = True
        if self.isVisible() and self._renderer is not None:
            if not self._timer.isActive():
                self._timer.start(16)

    def _render(self) -> None:
        if not self.isVisible() or self._renderer is None:
            return
        self._dirty = False
        renderer, yaw, pitch = self._renderer, self.yaw, self.pitch
        generation = self._generation

        def render() -> QImage:
            image = renderer.render(yaw, pitch, width=300, height=400, scale=9.8).convert("RGBA")
            return QImage(image.tobytes(), image.width, image.height,
                          image.width * 4, QImage.Format.Format_RGBA8888).copy()

        def ready(image: QImage) -> None:
            if generation == self._generation and self.isVisible():
                self._frame = QPixmap.fromImage(image)
                self.update()
                if self._dirty:
                    self.request_frame()

        def failed(error: Exception) -> None:
            if generation == self._generation:
                self.render_failed.emit(f"Could not render the skin: {error}")

        self._task.submit(render, ready, failed)

    def suspend(self) -> None:
        self._generation += 1
        self._task.invalidate()
        self._timer.stop()
        self._drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def shutdown(self) -> None:
        self.suspend()
        self._task.close()
        self._renderer = None
        self._frame = QPixmap()

    def hideEvent(self, event) -> None:
        self.suspend()
        super().hideEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.request_frame()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = event.position()
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag is not None:
            delta = event.position() - self._drag
            self._drag = event.position()
            self.set_view(self.yaw + delta.x() * 0.70, self.pitch + delta.y() * 0.45)
            self.rotated.emit()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.set_view(-25.0, 10.0)
            self.rotated.emit()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event) -> None:
        delta = {Qt.Key.Key_Left: (-10, 0), Qt.Key.Key_Right: (10, 0),
                 Qt.Key.Key_Up: (0, -5), Qt.Key.Key_Down: (0, 5)}.get(event.key())
        if delta is not None:
            self.set_view(self.yaw + delta[0], self.pitch + delta[1])
        elif event.key() == Qt.Key.Key_Home:
            self.set_view(-25.0, 10.0)
        else:
            super().keyPressEvent(event)
            return
        self.rotated.emit()
        event.accept()

    def paintEvent(self, event) -> None:
        if self._frame.isNull():
            return
        painter = QPainter(self)
        scale = min(self.width() / self._frame.width(), self.height() / self._frame.height(), 1.5)
        width, height = self._frame.width() * scale, self._frame.height() * scale
        target = QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)
        painter.drawPixmap(target, self._frame, QRectF(self._frame.rect()))
        if self.hasFocus() and self.property("keyboardFocus"):
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(self.palette().color(QPalette.ColorRole.Highlight), theme.STROKE_FOCUS))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), theme.RADIUS_BUTTON, theme.RADIUS_BUTTON)
