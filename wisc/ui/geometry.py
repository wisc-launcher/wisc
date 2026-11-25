"""Qt system move/resize with geometry fallback for undecorated desktop windows."""

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, QPoint, QRect, Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication, QWidget


def resize_edges(point: QPoint, size) -> Qt.Edge:
    """Use wider corners without taking input from controls inside the window."""
    x, y = point.x(), point.y()
    width, height = size.width(), size.height()
    edges = Qt.Edge(0)
    horizontal = 12 if y < 12 or y >= height - 12 else 6
    vertical = 12 if x < 12 or x >= width - 12 else 6
    if x < horizontal:
        edges |= Qt.Edge.LeftEdge
    elif x >= width - horizontal:
        edges |= Qt.Edge.RightEdge
    if y < vertical:
        edges |= Qt.Edge.TopEdge
    elif y >= height - vertical:
        edges |= Qt.Edge.BottomEdge
    return edges


class WindowGeometry(QObject):
    def __init__(self, window: QWidget):
        super().__init__(window)
        self._window = window
        self._edges = Qt.Edge(0)
        self._moving = False
        self._anchor = QPoint()
        self._initial = QRect()
        self._cursor_widget: QWidget | None = None
        self._cursor = QCursor()
        self._had_cursor = False
        window.setMouseTracking(True)
        QApplication.instance().installEventFilter(self)

    def start_move(self, position: QPoint) -> bool:
        handle = self._window.windowHandle()
        if handle is not None and handle.startSystemMove():
            return True
        if self._window.window_maximized or self._window.isFullScreen():
            return False
        self._begin(position, moving=True)
        return True

    def start_resize(self, edges: Qt.Edge, position: QPoint) -> bool:
        handle = self._window.windowHandle()
        if handle is not None and handle.startSystemResize(edges):
            return True
        self._edges = edges
        self._begin(position, moving=False)
        return True

    def _begin(self, position: QPoint, *, moving: bool) -> None:
        self._moving = moving
        self._anchor = position
        self._initial = self._window.geometry()
        if QApplication.platformName() not in ("offscreen", "minimal"):
            self._window.grabMouse()

    def cancel(self) -> None:
        self._moving = False
        self._edges = Qt.Edge(0)
        if QWidget.mouseGrabber() is self._window:
            self._window.releaseMouse()
        self._reset_cursor()

    def _update_geometry(self, position: QPoint) -> None:
        delta = position - self._anchor
        if self._moving:
            self._window.move(self._initial.topLeft() + delta)
            return
        left, top = self._initial.x(), self._initial.y()
        right, bottom = left + self._initial.width(), top + self._initial.height()
        minimum, maximum = self._window.minimumSize(), self._window.maximumSize()
        if self._edges & Qt.Edge.LeftEdge:
            left = min(right - minimum.width(), max(right - maximum.width(), left + delta.x()))
        elif self._edges & Qt.Edge.RightEdge:
            right = max(left + minimum.width(), min(left + maximum.width(), right + delta.x()))
        if self._edges & Qt.Edge.TopEdge:
            top = min(bottom - minimum.height(), max(bottom - maximum.height(), top + delta.y()))
        elif self._edges & Qt.Edge.BottomEdge:
            bottom = max(top + minimum.height(), min(top + maximum.height(), bottom + delta.y()))
        self._window.setGeometry(left, top, right - left, bottom - top)

    def _reset_cursor(self) -> None:
        widget, self._cursor_widget = self._cursor_widget, None
        if widget is not None and not sip.isdeleted(widget):
            widget.setCursor(self._cursor) if self._had_cursor else widget.unsetCursor()

    def _set_cursor(self, widget: QWidget, edges: Qt.Edge) -> None:
        if not edges:
            self._reset_cursor()
            return
        if widget is not self._cursor_widget:
            self._reset_cursor()
            self._cursor_widget = widget
            self._cursor = QCursor(widget.cursor())
            self._had_cursor = widget.testAttribute(Qt.WidgetAttribute.WA_SetCursor)
        horizontal = bool(edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge))
        vertical = bool(edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge))
        if horizontal and vertical:
            same = bool(edges & Qt.Edge.LeftEdge) == bool(edges & Qt.Edge.TopEdge)
            shape = Qt.CursorShape.SizeFDiagCursor if same else Qt.CursorShape.SizeBDiagCursor
        else:
            shape = Qt.CursorShape.SizeHorCursor if horizontal else Qt.CursorShape.SizeVerCursor
        widget.setCursor(shape)

    def eventFilter(self, watched, event) -> bool:
        kind = event.type()
        if watched is self._window and kind in (QEvent.Type.Hide, QEvent.Type.Close,
                                                QEvent.Type.WindowDeactivate, QEvent.Type.UngrabMouse):
            self.cancel()
        if not isinstance(watched, QWidget) or watched.window() is not self._window:
            return False
        if kind == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape and (self._moving or self._edges):
            self.cancel()
            return True
        if kind == QEvent.Type.Leave and watched is self._cursor_widget and not (self._moving or self._edges):
            self._reset_cursor()
        if self._window.native_geometry_available:
            return False
        if self._window.window_maximized or self._window.isFullScreen() or self._window.isMinimized():
            self.cancel()
            return False
        if kind not in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove,
                        QEvent.Type.MouseButtonRelease, QEvent.Type.HoverMove):
            return False
        if kind == QEvent.Type.HoverMove:
            position = watched.mapToGlobal(event.position().toPoint())
        else:
            position = event.globalPosition().toPoint()
        if self._moving or self._edges:
            if kind == QEvent.Type.MouseButtonRelease:
                self.cancel()
            elif kind == QEvent.Type.MouseMove:
                self._update_geometry(position)
            return True
        point = self._window.mapFromGlobal(position)
        edges = resize_edges(point, self._window.size())
        if kind in (QEvent.Type.MouseMove, QEvent.Type.HoverMove):
            self._set_cursor(watched, edges)
        elif kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton and edges:
            return self.start_resize(edges, position)
        return False
