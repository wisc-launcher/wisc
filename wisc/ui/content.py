"""Shared, virtualized Qt content lists, bounded artwork, and readable documents."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections import OrderedDict
from pathlib import Path
from typing import Any

from PyQt6.QtCore import (
    QAbstractListModel, QModelIndex, QPoint, QRect, QRectF, QSize,
    QSortFilterProxyModel, Qt, QTimer, QUrl, pyqtSignal, QObject,
)
from PyQt6.QtGui import (
    QColor, QImage, QPainter, QPainterPath, QPalette, QPen, QPixmap,
    QTextCharFormat, QTextCursor, QTextDocument,
)
from PyQt6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QListView, QPushButton, QSizePolicy,
    QStyle, QStyledItemDelegate, QStyleOptionButton, QTextBrowser, QWidget,
)

from wisc.mods.markdown import normalize_mod_markdown
from wisc.ui import theme as theme
from wisc.ui.components import (
    GlassButton, GlassMenu, compose_profile_surface, paint_glass,
    paint_profile_actions, paint_profile_caption, paint_switch, text_label,
)
from wisc.ui.images import ContentImages
from wisc.ui.theme import GLASS_OPACITY, MUTED, TEXT, ui_font


def format_size(value: int | None) -> str:
    if value is None:
        return "Size unavailable"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return ""


def format_downloads(value: int) -> str:
    for divisor, unit in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if value >= divisor:
            return f"{value / divisor:.1f}".rstrip("0").rstrip(".") + unit
    return str(value)


@dataclass(frozen=True)
class ContentAction:
    key: str
    label: str
    enabled: bool = True
    primary: bool = False
    switch: bool = False


@dataclass(frozen=True)
class ContentItem:
    key: str
    title: str
    description: str = ""
    details: str = ""
    icon: str | bytes | None = None
    actions: tuple[ContentAction, ...] = ()
    checked: bool | None = None
    payload: Any = field(default=None, compare=False)
    search_text: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "search_text", " ".join(
            (self.title, self.description, self.details, self.search_text)
        ).casefold())


ITEM_ROLE = int(Qt.ItemDataRole.UserRole) + 1
KEY_ROLE = ITEM_ROLE + 1


class ContentListModel(QAbstractListModel):
    action_requested = pyqtSignal(object, str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.items: list[ContentItem] = []

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.items):
            return None
        item = self.items[index.row()]
        if role == ITEM_ROLE:
            return item
        if role == KEY_ROLE:
            return item.key
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.AccessibleTextRole):
            return " · ".join(filter(None, (item.title, item.description, item.details)))
        if role == Qt.ItemDataRole.ToolTipRole:
            return item.title + ("\n" + item.description if item.description else "")
        if role == Qt.ItemDataRole.CheckStateRole and item.checked is not None:
            return Qt.CheckState.Checked if item.checked else Qt.CheckState.Unchecked
        return None

    def flags(self, index):
        flags = super().flags(index)
        item = index.data(ITEM_ROLE)
        if item is not None and item.checked is not None:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole) -> bool:
        item = index.data(ITEM_ROLE)
        if role == Qt.ItemDataRole.CheckStateRole and item is not None and item.checked is not None:
            self.action_requested.emit(item, "toggle")
            return True
        return False

    def set_items(self, items: list[ContentItem]) -> None:
        if len({item.key for item in items}) != len(items):
            raise ValueError("Content row keys must be unique.")
        if [item.key for item in items] == [item.key for item in self.items]:
            changed = [row for row, item in enumerate(items) if item != self.items[row]]
            self.items = items
            for row in changed:
                self.dataChanged.emit(self.index(row), self.index(row))
        else:
            self.beginResetModel()
            self.items = items
            self.endResetModel()


class ContentFilterModel(QSortFilterProxyModel):
    def __init__(self, parent: QObject):
        super().__init__(parent)
        self.query = ""
        self.state = "all"

    def set_filter(self, query: str, state: str = "all") -> None:
        query = query.strip().casefold()
        if (query, state) != (self.query, self.state):
            self.query, self.state = query, state
            self.beginFilterChange()
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def filterAcceptsRow(self, row: int, parent) -> bool:
        item = self.sourceModel().index(row, 0, parent).data(ITEM_ROLE)
        return (not self.query or self.query in item.search_text) and (
            self.state == "all" or item.checked == (self.state == "enabled")
        )




class ContentItemDelegate(QStyledItemDelegate):
    HEIGHT = 96

    def __init__(self, view: "ContentList", images: ContentImages):
        super().__init__(view)
        self.view, self.images = view, images
        self.title_font = ui_font(theme.FONT_ROW_TITLE, bold=True)
        self.body_font = ui_font(theme.FONT_BODY)
        self.detail_font = ui_font(theme.FONT_DETAIL)
        self.action_font = ui_font(theme.FONT_DETAIL, bold=True)

    def sizeHint(self, option, index) -> QSize:
        return QSize(300, self.HEIGHT)

    def editorEvent(self, event, model, option, index) -> bool:
        # The view owns the painted actions. Qt's default check hitbox would
        # otherwise treat a click on our artwork as a second checkbox action.
        return False

    def action_rects(self, rect: QRect, item: ContentItem) -> list[tuple[ContentAction, QRect]]:
        right = rect.right() - 16
        result = []
        metrics = self.view.fontMetrics()
        for action in reversed(item.actions):
            if action.key == "install" and action.label == "Install":
                width = 38
                bounds = QRect(right - width, rect.y() + 25, width, 38)
            else:
                width = 56 if action.switch else max(68, metrics.horizontalAdvance(action.label) + 24
                                                      + (22 if action.key == "toggle" and item.checked is not None else 0))
                bounds = QRect(right - width, rect.y() + 22, width, 44)
            result.append((action, bounds))
            right -= width + 8
        return list(reversed(result))

    def paint(self, painter: QPainter, option, index) -> None:
        item = index.data(ITEM_ROLE)
        if item is None:
            return
        bounds = QRectF(option.rect.adjusted(0, 0, -1, -8))
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_glass(self.view.viewport(), painter, radius=theme.RADIUS_CARD,
                    opacity=GLASS_OPACITY + (theme.ROW_HOVER_OPACITY if hovered else 0), bounds=bounds)
        accent = self.view.accent
        image = self.images.get(item.icon) or self.images.fallback
        icon_rect = QRect(option.rect.x() + 16, option.rect.y() + 20, 48, 48)
        if not image.isNull():
            fitted = image.size().scaled(icon_rect.size(), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRect(QPoint(0, 0), fitted)
            target.moveCenter(icon_rect.center())
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawPixmap(target, image)
        actions = self.action_rects(option.rect, item)
        right = actions[0][1].left() - 16 if actions else option.rect.right() - 16
        left = icon_rect.right() + 16
        for text, font, color, top in (
            (item.title, self.title_font, TEXT, 12),
            (item.description, self.body_font, MUTED, 36),
            (item.details, self.detail_font, MUTED, 60),
        ):
            painter.setFont(font)
            painter.setPen(QColor(color))
            value = painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, max(0, right - left))
            painter.drawText(QRect(left, option.rect.y() + top, max(0, right - left), 20),
                             Qt.AlignmentFlag.AlignVCenter, value)
        for action, rect in actions:
            enabled = action.enabled and self.view.actions_enabled
            if action.switch:
                track = QRectF(rect.x() + 6, rect.y() + 10, 44, 24)
                paint_switch(painter, track, bool(item.checked), accent, enabled=enabled)
                continue
            painter.setPen(Qt.PenStyle.NoPen)
            if action.primary and enabled:
                painter.setBrush(accent)
                painter.drawRoundedRect(QRectF(rect), theme.RADIUS_BUTTON, theme.RADIUS_BUTTON)
            else:
                paint_glass(self.view.viewport(), painter, radius=theme.RADIUS_BUTTON, bounds=QRectF(rect))
            if action.key == "install" and action.label == "Install":
                ink = self.view.on_accent if action.primary and enabled else QColor(TEXT if enabled else MUTED)
                painter.setPen(QPen(ink, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                cx, cy = rect.center().x(), rect.center().y()
                arrow = QPainterPath()
                arrow.moveTo(cx, cy - 6)
                arrow.lineTo(cx, cy + 2)
                arrow.moveTo(cx - 4, cy - 2)
                arrow.lineTo(cx, cy + 2)
                arrow.lineTo(cx + 4, cy - 2)
                arrow.moveTo(cx - 6, cy + 5)
                arrow.lineTo(cx - 6, cy + 7)
                arrow.lineTo(cx + 6, cy + 7)
                arrow.lineTo(cx + 6, cy + 5)
                painter.drawPath(arrow)
                continue
            painter.setFont(self.action_font)
            if action.key == "toggle" and item.checked is not None:
                check = QStyleOptionButton()
                palette = self.view.palette()
                palette.setColor(QPalette.ColorRole.Highlight, accent)
                check.palette = palette
                check.rect = QRect(rect.x() + 10, rect.y() + 14, 16, 16)
                check.state = (QStyle.StateFlag.State_Enabled if enabled else QStyle.StateFlag.State_None) | (
                    QStyle.StateFlag.State_On if item.checked else QStyle.StateFlag.State_Off
                )
                self.view.style().drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorCheckBox,
                                                check, painter, self.view)
                text_rect = rect.adjusted(30, 0, -6, 0)
            else:
                text_rect = rect
            painter.setPen(self.view.on_accent if action.primary and enabled
                           else QColor(TEXT if enabled else MUTED))
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, action.label)
        painter.restore()


class ContentList(QListView):
    """Native model/view scrolling; no widgets or downloads per offscreen row."""

    item_opened = pyqtSignal(object)
    action_requested = pyqtSignal(object, str)

    def __init__(self, images: ContentImages, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("contentList")
        self.setFrameShape(QListView.Shape.NoFrame)
        self.setUniformItemSizes(True)
        self.setLayoutMode(QListView.LayoutMode.Batched)
        self.setBatchSize(100)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setMouseTracking(True)
        self.viewport().setAutoFillBackground(False)
        self.source = ContentListModel(self)
        self.proxy = ContentFilterModel(self)
        self.proxy.setSourceModel(self.source)
        self.setModel(self.proxy)
        self.delegate = ContentItemDelegate(self, images)
        self.setItemDelegate(self.delegate)
        self.source.action_requested.connect(self.action_requested)
        self.accent = self.window().palette().highlight().color()
        self.on_accent = self.window().palette().highlightedText().color()
        self.actions_enabled = True
        self._pressed: tuple[str, str] | None = None
        images.ready.connect(self._image_ready)

    def _image_ready(self, key: str) -> None:
        if self.isVisible():
            self.viewport().update()

    def set_accent(self, accent: str | QColor, foreground: str | QColor) -> None:
        self.accent, self.on_accent = QColor(accent), QColor(foreground)
        self.viewport().update()

    def set_items(self, items: list[ContentItem], *, reset_scroll: bool = False) -> None:
        selected = self.currentIndex().data(KEY_ROLE)
        offset = 0 if reset_scroll else self.verticalScrollBar().value()
        self.source.set_items(items)
        if selected:
            matches = self.proxy.match(self.proxy.index(0, 0), KEY_ROLE, selected, 1,
                                       Qt.MatchFlag.MatchExactly)
            if matches:
                self.setCurrentIndex(matches[0])
        self.doItemsLayout()
        self.verticalScrollBar().setValue(offset)

    def set_filter(self, query: str, state: str = "all") -> None:
        self.proxy.set_filter(query, state)

    def _action_at(self, point: QPoint) -> tuple[ContentItem | None, str]:
        index = self.indexAt(point)
        item = index.data(ITEM_ROLE)
        if item is None:
            return None, ""
        for action, rect in self.delegate.action_rects(self.visualRect(index), item):
            if rect.contains(point):
                return item, action.key if action.enabled and self.actions_enabled else "blocked"
        return item, "open"

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        item, action = self._action_at(event.position().toPoint())
        self._pressed = (item.key, action) if item and event.button() == Qt.MouseButton.LeftButton else None
        if action == "open":
            super().mousePressEvent(event)
        else:
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        item, action = self._action_at(event.position().toPoint())
        pressed, self._pressed = self._pressed, None
        if event.button() == Qt.MouseButton.LeftButton and item and pressed == (item.key, action):
            if action == "open":
                self.item_opened.emit(item)
            elif action != "blocked":
                self.action_requested.emit(item, action)
        if action == "open":
            super().mouseReleaseEvent(event)
        else:
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        item, action = self._action_at(event.position().toPoint())
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if item and action != "blocked"
                                  else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def keyPressEvent(self, event) -> None:
        item = self.currentIndex().data(ITEM_ROLE)
        if item is not None and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.item_opened.emit(item)
            event.accept()
        elif item is not None and item.checked is not None and self.actions_enabled and event.key() == Qt.Key.Key_Space:
            self.action_requested.emit(item, "toggle")
            event.accept()
        else:
            super().keyPressEvent(event)

    def contextMenuEvent(self, event) -> None:
        index = self.indexAt(event.pos()) if event.pos().x() >= 0 else self.currentIndex()
        item = index.data(ITEM_ROLE)
        if item is None:
            return
        menu = GlassMenu(self)
        menu.addAction("View details", lambda: self.item_opened.emit(item))
        for action in item.actions:
            entry = menu.addAction(action.label, lambda checked=False, key=action.key:
                                   self.action_requested.emit(item, key))
            entry.setEnabled(action.enabled and self.actions_enabled)
        menu.exec(event.globalPos())
        menu.deleteLater()


class ProfileCardDelegate(ContentItemDelegate):
    """Paint the shared profile card, with a small cache for visible surfaces."""

    def __init__(self, view: "ProfileGrid", images: ContentImages):
        super().__init__(view, images)
        self.surfaces: OrderedDict[tuple, QPixmap] = OrderedDict()
        self._bytes = 0

    def clear(self) -> None:
        self.surfaces.clear()
        self._bytes = 0

    def sizeHint(self, option, index) -> QSize:
        return QSize(max(160, self.view.gridSize().width() - 12), 170)

    def action_rects(self, rect, item):
        return [(ContentAction("menu", "Profile actions"), QRect(rect.right() - 41, rect.top() + 10, 30, 30))]

    def paint(self, painter, option, index) -> None:
        item = index.data(ITEM_ROLE)
        if item is None:
            return
        profile = item.payload
        w, h = option.rect.width(), option.rect.height()
        scale = painter.device().devicePixelRatioF()
        key = (item.key, w, h, scale)
        surface = self.surfaces.get(key)
        if surface is None:
            surface = compose_profile_surface(str(profile.artwork), str(profile.icon), w, h, scale, self.images)
            self.surfaces[key] = surface
            self._bytes += surface.width() * surface.height() * 4
            while self._bytes > 4 * 1024 * 1024 or len(self.surfaces) > 24:
                _, old = self.surfaces.popitem(last=False)
                self._bytes -= old.width() * old.height() * 4
        else:
            self.surfaces.move_to_end(key)
        painter.save()
        painter.translate(option.rect.topLeft())
        painter.drawPixmap(0, 0, surface)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_profile_caption(painter, item.title, item.details, w, h, self.view.accent.name(),
                              selected=item.key == self.view.selected_id, has_actions=True,
                              highlighted=bool(option.state & (QStyle.StateFlag.State_MouseOver | QStyle.StateFlag.State_HasFocus)))
        painter.setPen(QColor(theme.TEXT))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.with_alpha(theme.SURFACE, 170))
        painter.drawRoundedRect(QRectF(w - 42, 10, 30, 30), theme.RADIUS_FIELD, theme.RADIUS_FIELD)
        paint_profile_actions(painter, QPoint(w - 27, 25))
        painter.restore()


class ProfileGrid(ContentList):
    """Library grid using the existing stable content model and interactions."""

    def __init__(self, images: ContentImages, parent: QWidget | None = None):
        super().__init__(images, parent)
        self.selected_id: str | None = None
        previous = self.delegate
        self.delegate = ProfileCardDelegate(self, images)
        self.setItemDelegate(self.delegate)
        previous.deleteLater()
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setMovement(QListView.Movement.Static)
        self.setWrapping(True)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setUniformItemSizes(True)
        self.setSpacing(0)
        self._resize_grid()
        self.action_requested.connect(self._profile_action)

    def _resize_grid(self) -> None:
        margin = self.style().pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin, None, self)
        reserve = (0 if self.verticalScrollBar().isVisible()
                   else self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent, None, self))
        # Icon-mode layout reserves the native scrollbar extent before deciding
        # whether a scrollbar is needed, even when the styled bar is narrower.
        width = max(1, self.viewport().width() - 2 * margin - reserve)
        columns = max(1, (width + 12) // 312)
        size = QSize(max(172, width // columns), 182)
        if size != self.gridSize():
            self.setGridSize(size)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._resize_grid()

    def _image_ready(self, key: str) -> None:
        if isinstance(self.delegate, ProfileCardDelegate):
            self.delegate.clear()
        super()._image_ready(key)

    def hideEvent(self, event) -> None:
        self.delegate.clear()
        super().hideEvent(event)

    def _profile_action(self, item: ContentItem, action: str) -> None:
        if action == "menu":
            index = self.currentIndex()
            matches = self.proxy.match(self.proxy.index(0, 0), KEY_ROLE, item.key, 1, Qt.MatchFlag.MatchExactly)
            if matches:
                index = matches[0]
            self._show_actions(item, self.viewport().mapToGlobal(self.visualRect(index).topRight() + QPoint(-10, 40)))

    def _show_actions(self, item: ContentItem, position: QPoint) -> None:
        menu = GlassMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        for key, label in (("home", "Open on Home"), ("play", "Play" if item.payload.installed else "Install && Play"),
                           ("edit", "Edit"), ("folder", "Folder"), ("mods", "Mods")):
            menu.addAction(label, lambda checked=False, action=key: self.action_requested.emit(item, action))
        menu.popup(position)

    def contextMenuEvent(self, event) -> None:
        index = self.indexAt(event.pos()) if event.pos().x() >= 0 else self.currentIndex()
        item = index.data(ITEM_ROLE)
        if item is not None:
            self._show_actions(item, event.globalPos())

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space:
            item = self.currentIndex().data(ITEM_ROLE)
            if item is not None:
                self.item_opened.emit(item)
            event.accept()
        else:
            super().keyPressEvent(event)


class _PageArrowButton(QPushButton):
    def __init__(self, direction: int, parent: QWidget | None = None):
        super().__init__(parent)
        self._direction = direction
        self.setObjectName("quiet")
        self.setFixedSize(28, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(TEXT if self.isEnabled() else theme.DISABLED_TEXT)
        painter.setPen(QPen(color, 1.7, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        cx, cy = self.width() / 2, self.height() / 2
        chevron = QPainterPath()
        chevron.moveTo(cx - self._direction * 2.5, cy - 4.5)
        chevron.lineTo(cx + self._direction * 2.5, cy)
        chevron.lineTo(cx - self._direction * 2.5, cy + 4.5)
        painter.drawPath(chevron)


class SkeletonList(QWidget):
    """Lightweight placeholder rows shown while content or pages are loading."""

    def __init__(self, parent: QWidget | None = None, *, rows: int = 5):
        super().__init__(parent)
        self._rows = rows
        self._phase = 0
        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._tick)

    def _tick(self) -> None:
        self._phase = (self._phase + 1) % 20
        self.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pulse = abs(self._phase - 10) / 10.0
        base_alpha = round(14 + 12 * pulse)
        muted_alpha = round(9 + 8 * pulse)
        row_h = ContentItemDelegate.HEIGHT
        available = max(1, (self.height() + 8) // row_h)
        count = min(self._rows, available)
        w = self.width()
        for i in range(count):
            y = i * row_h
            bounds = QRectF(0, y, w - 1, row_h - 8)
            paint_glass(self, painter, radius=theme.RADIUS_CARD, opacity=GLASS_OPACITY, bounds=bounds)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, base_alpha))
            painter.drawRoundedRect(QRectF(16, y + 20, 48, 48), theme.RADIUS_BUTTON, theme.RADIUS_BUTTON)
            left = 80
            max_bar = max(120, w - left - 76)
            title_w = min(220, max_bar * 0.42)
            desc_w = min(460, max_bar * 0.85)
            meta_w = min(170, max_bar * 0.30)
            painter.drawRoundedRect(QRectF(left, y + 16, title_w, 13), 4, 4)
            painter.setBrush(QColor(255, 255, 255, muted_alpha))
            painter.drawRoundedRect(QRectF(left, y + 39, desc_w, 11), 4, 4)
            painter.drawRoundedRect(QRectF(left, y + 61, meta_w, 10), 4, 4)


class ContentPagination(QWidget):
    requested = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(28)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.previous = _PageArrowButton(-1)
        self.previous.setAccessibleName("Previous page")
        self.previous.setToolTip("Previous page")
        self.previous.clicked.connect(lambda: self.requested.emit(-1))
        self.label = text_label("", theme.FONT_DETAIL, muted=True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setMinimumWidth(64)
        self.next = _PageArrowButton(1)
        self.next.setAccessibleName("Next page")
        self.next.setToolTip("Next page")
        self.next.clicked.connect(lambda: self.requested.emit(1))
        for widget in (self.previous, self.label, self.next):
            layout.addWidget(widget)

    def display(self, offset: int, total: int, page_size: int = 20, *, busy: bool = False) -> None:
        self.setVisible(total > page_size)
        self.previous.setEnabled(offset > 0 and not busy)
        self.next.setEnabled(offset + page_size < total and not busy)
        self.label.setText(f"{offset // page_size + 1} / {max(1, (total + page_size - 1) // page_size)}")


class ContentImage(QWidget):
    def __init__(self, images: ContentImages, source: str | bytes | None = None,
                 parent: QWidget | None = None, *, limit: int = 128):
        super().__init__(parent)
        self.images, self.source, self.limit = images, source, limit
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        images.ready.connect(self._ready)

    def _ready(self, key: str) -> None:
        if self.isVisible() and self.source and key == self.images.key(self.source, self.limit):
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        image = self.images.get(self.source, self.limit)
        if image is None:
            image = self.images.fallback
        if not image.isNull():
            size = image.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRect(QPoint(0, 0), size)
            target.moveCenter(self.rect().center())
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawPixmap(target, image)


class ContentMarkdown(QTextBrowser):
    """Qt Markdown with asynchronous images and explicit HTTP(S) links."""

    link_requested = pyqtSignal(str)

    def __init__(self, images: ContentImages, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("contentMarkdown")
        self.setFrameShape(QTextBrowser.Shape.NoFrame)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.viewport().setAutoFillBackground(False)
        self.images = images
        self._accent: QColor | None = None
        self._resources: dict[str, QUrl] = {}
        self.anchorClicked.connect(lambda url: self.link_requested.emit(url.toString()))
        images.ready.connect(self._image_ready)
        self.document().setDefaultFont(ui_font(theme.FONT_LABEL))

    def display(self, value: str, base_url: str = "https://modrinth.com/") -> None:
        self._resources.clear()
        self.document().setBaseUrl(QUrl(base_url))
        self.document().setMarkdown(normalize_mod_markdown(value, base_url),
                                    QTextDocument.MarkdownFeature.MarkdownDialectGitHub)
        self._style_links()
        self.verticalScrollBar().setValue(0)

    def set_accent(self, accent: str | QColor) -> None:
        self._accent = QColor(accent)
        self._style_links()

    def _style_links(self) -> None:
        if self._accent is None:
            return
        spans = []
        block = self.document().begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid() and fragment.charFormat().isAnchor():
                    spans.append((fragment.position(), fragment.length()))
                iterator += 1
            block = block.next()
        formatting = QTextCharFormat()
        formatting.setForeground(self._accent)
        cursor = QTextCursor(self.document())
        for start, length in spans:
            cursor.setPosition(start)
            cursor.setPosition(start + length, QTextCursor.MoveMode.KeepAnchor)
            cursor.mergeCharFormat(formatting)

    def loadResource(self, kind: int, url: QUrl):
        resolved = self.document().baseUrl().resolved(url)
        if kind != QTextDocument.ResourceType.ImageResource or resolved.scheme() not in {"http", "https"}:
            return None
        source = resolved.toString()
        key = self.images.key(source, 768)
        self._resources[key] = url
        image = self.images.get(source, 768)
        if image is not None:
            return image.toImage()
        placeholder = QImage(1, 1, QImage.Format.Format_RGBA8888)
        placeholder.fill(Qt.GlobalColor.transparent)
        return placeholder

    def _image_ready(self, key: str) -> None:
        url = self._resources.get(key)
        if url is not None and self.isVisible():
            source = self.document().baseUrl().resolved(url).toString()
            image = self.images.get(source, 768)
            if image is not None:
                self.document().addResource(QTextDocument.ResourceType.ImageResource, url, image.toImage())
                self.document().markContentsDirty(0, self.document().characterCount())
                self.viewport().update()
