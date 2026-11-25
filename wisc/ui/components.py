"""Artwork and compact controls shared by the new Qt frontend."""

from functools import lru_cache
from math import ceil
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QEvent, QPoint, QRectF, QSize, Qt
from PyQt6.QtGui import (
    QColor, QIcon, QImageReader, QLinearGradient, QPainter, QPainterPath, QPalette,
    QPen, QPixmap,
)
from PyQt6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QApplication, QComboBox, QFrame, QGraphicsBlurEffect,
    QGraphicsScene, QLabel, QLineEdit, QListView, QMenu, QPushButton, QSizePolicy,
    QStyle, QStyledItemDelegate, QToolButton, QVBoxLayout, QWidget,
)

from wisc.ui import theme as theme
from wisc.ui.theme import GLASS_OPACITY, MUTED, SURFACE, TEXT, ui_font

if TYPE_CHECKING:
    from wisc.ui.images import ContentImages


@lru_cache(maxsize=2)
def artwork_image(path: str) -> QPixmap:
    """Full-size decoded image for the selected profile background."""
    return QPixmap(path)


@lru_cache(maxsize=4)
def frosted_image(path: str) -> QPixmap:
    """Reuse bundled blur; render a cached image-only blur for other artwork."""
    source = Path(path)
    bundled = source.parent / "blurred" / source.name
    if bundled.is_file():
        return artwork_image(str(bundled))
    image = artwork_image(path)
    if image.isNull():
        return image
    image = image.scaledToWidth(min(image.width(), 1200), Qt.TransformationMode.SmoothTransformation)
    scene = QGraphicsScene()
    item = scene.addPixmap(image)
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(theme.ARTWORK_BLUR_RADIUS)
    item.setGraphicsEffect(effect)
    scene.setSceneRect(item.boundingRect())
    blurred = QPixmap(image.size())
    blurred.fill(Qt.GlobalColor.transparent)
    painter = QPainter(blurred)
    scene.render(painter, QRectF(blurred.rect()), scene.sceneRect())
    painter.end()
    return blurred


@lru_cache(maxsize=8)
def card_artwork_thumbnail(path: str) -> QPixmap:
    """Card-sized artwork thumbnail (max 480x270), saving ~14MB RAM per profile."""
    reader = QImageReader(path)
    orig = reader.size()
    if orig.isValid() and orig.width() > 480:
        reader.setScaledSize(orig.scaled(480, 270, Qt.AspectRatioMode.KeepAspectRatio))
    img = reader.read()
    return QPixmap.fromImage(img)


@lru_cache(maxsize=8)
def card_frosted_thumbnail(path: str) -> QPixmap:
    """Card-sized blurred artwork thumbnail for the caption."""
    source = Path(path)
    bundled = source.parent / "blurred" / source.name
    if bundled.is_file():
        return card_artwork_thumbnail(str(bundled))
    return card_artwork_thumbnail(path)


def asset_icon(path: Path, color: str | None = None) -> QIcon:
    return _asset_icon(str(path), color, QApplication.instance().devicePixelRatio())


@lru_cache(maxsize=64)
def _asset_icon(source: str, color: str | None, scale: float) -> QIcon:
    path = Path(source)
    if path.suffix.lower() == ".svg":
        if not color:
            return QIcon(str(path))
        image = QIcon(str(path)).pixmap(QSize(24, 24), scale)
    else:
        image = QPixmap(str(path))
    if color and not image.isNull():
        painter = QPainter(image)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(image.rect(), QColor(color))
        painter.end()
    return QIcon(image)


def draw_cover(painter: QPainter, image: QPixmap, target: QRectF) -> None:
    if image.isNull() or target.width() <= 0 or target.height() <= 0:
        return
    scale = max(target.width() / image.width(), target.height() / image.height())
    width, height = target.width() / scale, target.height() / scale
    source = QRectF((image.width() - width) / 2, (image.height() - height) / 2, width, height)
    painter.drawPixmap(target, image, source)


def text_label(text: str, size: int, *, bold: bool = False, muted: bool = False,
               pixel: bool = False) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setFont(ui_font(size, bold=bold, pixel=pixel))
    label.setProperty("muted", muted)
    return label


class ArtworkBackground(QWidget):
    """Shared artwork with strong Home shading and gentle fades on feature pages."""

    def __init__(self, artwork: Path, parent: QWidget | None = None, *,
                 images: "ContentImages | None" = None):
        super().__init__(parent)
        self._artwork = str(artwork)
        self._softened_artwork = self._find_softened_artwork()
        self._frosted = False
        self._home_shading = True
        self._frame_key: tuple[str, int, int, float, bool] | None = None
        self._frames: dict[bool, QPixmap] = {}
        self._images = images
        self._last_images: dict[bool, QPixmap] = {}
        if images is not None:
            images.ready.connect(self._image_ready)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

    def _image_ready(self, key: str) -> None:
        if key in self._image_keys():
            self._frames.clear()
            self.update()
            for child in self.findChildren(QWidget):
                if child.isVisible():
                    child.update()

    def _image_sources(self) -> tuple[str, int, str, int, bool]:
        limit = min(2560, max(480, ceil(max(self.width(), self.height()) * self.devicePixelRatioF() / 128) * 128))
        return self._artwork, limit, self._softened_artwork or self._artwork, min(limit, 1200), self._softened_artwork is None

    def _find_softened_artwork(self) -> str | None:
        source = Path(self._artwork)
        bundled = source.parent / "blurred" / source.name
        return str(bundled) if bundled.is_file() else None

    def _image_keys(self) -> set[str]:
        crisp, limit, frosted, blur_limit, blur = self._image_sources()
        return {self._images.key(crisp, limit), self._images.key(frosted, blur_limit, blur=blur)}

    def set_frosted(self, frosted: bool) -> None:
        if self._frosted != frosted:
            self._frosted = frosted
            self.update()

    def set_home_shading(self, enabled: bool) -> None:
        if self._home_shading != enabled:
            self._home_shading = enabled
            self._frames.clear()
            self.update()
            for child in self.findChildren(QWidget):
                if child.isVisible():
                    child.update()

    def set_artwork(self, artwork: Path) -> None:
        if str(artwork) != self._artwork:
            self._artwork = str(artwork)
            self._softened_artwork = self._find_softened_artwork()
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        self.paint_artwork(painter, frosted=self._frosted)

    def paint_artwork(self, painter: QPainter, *, frosted: bool = False) -> None:
        """Reuse one opaque frame per size/DPR for the backdrop and glass controls."""
        key = (self._artwork, self.width(), self.height(), self.devicePixelRatioF(), self._home_shading)
        if key != self._frame_key:
            self._frame_key = key
            self._frames.clear()
        frame = self._frames.get(frosted)
        if frame is None:
            scale = self.devicePixelRatioF()
            frame = QPixmap(ceil(self.width() * scale), ceil(self.height() * scale))
            frame.setDevicePixelRatio(scale)
            frame.fill(QColor(SURFACE))
            if not frame.isNull():
                composition = QPainter(frame)
                composition.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                self._compose_artwork(composition, frosted=frosted)
                composition.end()
            self._frames[frosted] = frame
        painter.drawPixmap(0, 0, frame)

    def _compose_artwork(self, painter: QPainter, *, frosted: bool) -> None:
        bounds = QRectF(self.rect())
        if self._images is None:
            image = frosted_image(self._artwork) if frosted else artwork_image(self._artwork)
        else:
            crisp, limit, softened, blur_limit, blur = self._image_sources()
            image = (self._images.get(softened, blur_limit, blur=blur) if frosted
                     else self._images.get(crisp, limit))
            if image is not None:
                self._last_images[frosted] = image
            else:
                image = self._last_images.get(frosted, QPixmap())
        draw_cover(painter, image, bounds)
        strength = 1.0 if self._home_shading else theme.FEATURE_VIGNETTE_STRENGTH
        horizontal = QLinearGradient(0, 0, self.width(), 0)
        for stop, alpha in theme.VIGNETTE_HORIZONTAL:
            horizontal.setColorAt(stop, theme.with_alpha(SURFACE, round(alpha * strength)))
        painter.fillRect(bounds, horizontal)
        vertical = QLinearGradient(0, 0, 0, self.height())
        for stop, alpha in theme.VIGNETTE_VERTICAL:
            vertical.setColorAt(stop, theme.with_alpha(SURFACE, round(alpha * strength)))
        painter.fillRect(bounds, vertical)


def paint_glass(widget: QWidget, painter: QPainter, *, radius: float = theme.RADIUS_BUTTON,
                opacity: float = GLASS_OPACITY, bounds: QRectF | None = None) -> None:
    """Sample the shared backdrop in window coordinates; keep children sharp."""
    source = widget.parentWidget()
    while source is not None and not isinstance(source, ArtworkBackground):
        central_widget = getattr(source, "centralWidget", None)
        if callable(central_widget) and isinstance(central_widget(), ArtworkBackground):
            source = central_widget()
            break
        source = source.parentWidget()
    bounds = QRectF(widget.rect()) if bounds is None else bounds
    clip = QPainterPath()
    clip.addRoundedRect(bounds, radius, radius)
    painter.save()
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
    painter.setClipPath(clip)
    painter.fillRect(bounds, QColor(SURFACE))
    if source is not None:
        origin = source.mapFromGlobal(widget.mapToGlobal(QPoint(0, 0)))
        painter.translate(-origin.x(), -origin.y())
        source.paint_artwork(painter, frosted=True)
        painter.translate(origin.x(), origin.y())
    tint = QColor(SURFACE)
    tint.setAlphaF(opacity)
    painter.fillRect(bounds, tint)
    painter.restore()


class GlassPanel(QWidget):
    def __init__(self, parent: QWidget | None = None, *, radius: float = theme.RADIUS_PANEL,
                 opacity: float = GLASS_OPACITY):
        super().__init__(parent)
        self._radius, self._opacity = radius, opacity

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        paint_glass(self, painter, radius=self._radius, opacity=self._opacity)


class GlassButton(QPushButton):
    """Standard button interaction over a shared, frosted background."""

    def __init__(self, text: str = "", parent: QWidget | None = None, *, radius: float = theme.RADIUS_BUTTON,
                 opacity: float = GLASS_OPACITY, accented: bool = False):
        super().__init__(text, parent)
        self._radius, self._opacity, self._accented = radius, opacity, accented
        self.setProperty("glass", True)
        self.setProperty("primary", accented)

    def paintEvent(self, event) -> None:
        if self._accented or self.isChecked():
            super().paintEvent(event)
            return
        painter = QPainter(self)
        enabled = self.isEnabled()
        focused = enabled and self.hasFocus() and bool(self.property("keyboardFocus"))
        interaction = (theme.GLASS_PRESSED_OPACITY if self.isDown()
                       else theme.GLASS_HOVER_OPACITY if self.underMouse() and enabled
                       else theme.GLASS_FOCUS_OPACITY if focused else 0.0)
        paint_glass(self, painter, radius=self._radius,
                    opacity=min(1.0, self._opacity + interaction))
        if focused:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(*theme.BUTTON_FOCUS_FILL))
            painter.drawRoundedRect(QRectF(self.rect()), self._radius, self._radius)
        painter.end()
        super().paintEvent(event)


def paint_switch(painter: QPainter, bounds: QRectF, checked: bool, accent: QColor, *, enabled: bool = True) -> None:
    """A borderless pill switch shared by painted Qt controls."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    track = QColor(accent) if checked else QColor(theme.SWITCH_TRACK)
    track.setAlpha(theme.SWITCH_ON_ALPHA if enabled and checked
                   else theme.SWITCH_OFF_ALPHA if enabled else theme.SWITCH_DISABLED_ALPHA)
    painter.setBrush(track)
    radius = bounds.height() * theme.PILL_RADIUS_RATIO
    painter.drawRoundedRect(bounds, radius, radius)
    thumb = QColor(accent) if checked else QColor(MUTED)
    if not enabled:
        thumb.setAlpha(theme.SWITCH_DISABLED_THUMB_ALPHA)
    painter.setBrush(thumb)
    diameter = bounds.height() - 6
    left = bounds.right() - diameter - 3 if checked else bounds.left() + 3
    painter.drawEllipse(QRectF(left, bounds.top() + 3, diameter, diameter))
    painter.restore()


class GlassLineEdit(QLineEdit):
    def __init__(self, parent: QWidget | None = None, *, search_icon: bool = False):
        super().__init__(parent)
        self._search_icon = search_icon
        if search_icon:
            self.setTextMargins(26, 0, 0, 0)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        paint_glass(self, painter, radius=theme.RADIUS_FIELD)
        if self._search_icon:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor(MUTED), theme.STROKE_ICON, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            cy = self.height() / 2
            cx = 20.0
            painter.drawEllipse(QRectF(cx - 5.5, cy - 5.5, 9.5, 9.5))
            painter.drawLine(QPoint(round(cx + 2.5), round(cy + 2.5)), QPoint(round(cx + 6.5), round(cy + 6.5)))
        painter.end()
        super().paintEvent(event)


class GlassMenu(QMenu):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAutoFillBackground(False)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        paint_glass(self, painter, radius=theme.RADIUS_BUTTON)
        painter.end()
        super().paintEvent(event)


class ElidedLabel(QLabel):
    """A real text label that cannot expand a layout with a long profile name."""

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self._full_text = text
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self.setText(text)

    def setText(self, text: str) -> None:
        self._full_text = text
        self.setToolTip(text)
        self._elide()

    def _elide(self) -> None:
        super().setText(self.fontMetrics().elidedText(
            self._full_text, Qt.TextElideMode.ElideRight, max(0, self.contentsRect().width()),
        ))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()


class _DropdownItemDelegate(QStyledItemDelegate):
    def __init__(self, selector: "LauncherComboBox", parent: QWidget):
        super().__init__(parent)
        self.selector = selector

    def sizeHint(self, option, index) -> QSize:
        return QSize(0, max(34, self.selector.height() - 2))

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = QRectF(option.rect).adjusted(0, 1, 0, -1)
        accent = self.selector.window().palette().color(QPalette.ColorRole.Highlight)
        selected = index.row() == self.selector.currentIndex()
        enabled = bool(index.flags() & Qt.ItemFlag.ItemIsEnabled)
        if option.state & (QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver):
            tint = QColor(accent)
            tint.setAlpha(theme.DROPDOWN_HOVER_ALPHA if enabled else 0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(tint)
            painter.drawRoundedRect(bounds, theme.RADIUS_FIELD, theme.RADIUS_FIELD)
        painter.setFont(self.selector.font())
        painter.setPen(QColor(TEXT if enabled else MUTED))
        text_bounds = option.rect.adjusted(10, 0, -30, 0)
        label = painter.fontMetrics().elidedText(str(index.data() or ""),
                                                Qt.TextElideMode.ElideRight, text_bounds.width())
        painter.drawText(text_bounds, Qt.AlignmentFlag.AlignVCenter, label)
        if selected:
            painter.setPen(QPen(accent, theme.STROKE_ICON, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            x, y = bounds.right() - 16, bounds.center().y()
            check = QPainterPath()
            check.moveTo(x - 4, y)
            check.lineTo(x - 1, y + 3)
            check.lineTo(x + 5, y - 3)
            painter.drawPath(check)
        painter.restore()


class _DropdownListView(QListView):
    def __init__(self, selector: "LauncherComboBox", parent: QWidget):
        super().__init__(parent)
        self.selector = selector
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAutoFillBackground(False)
        self.viewport().setAutoFillBackground(False)
        self.setMouseTracking(True)
        self.setUniformItemSizes(True)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setItemDelegate(_DropdownItemDelegate(selector, self))
        self.setStyleSheet(theme.DROPDOWN_STYLESHEET)
        self.clicked.connect(selector._choose_index)
        self.activated.connect(selector._choose_index)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_F4):
            self.selector.hidePopup()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.selector._choose_index(self.currentIndex())
        elif event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            self.selector.hidePopup()
            self.selector.focusNextPrevChild(event.key() == Qt.Key.Key_Tab)
        else:
            super().keyPressEvent(event)


class _DropdownPopup(QWidget):
    """Own the entire rounded surface, including the area around the list."""

    def __init__(self, selector: "LauncherComboBox"):
        super().__init__(selector, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.selector = selector
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(0)
        self.list = _DropdownListView(selector, self)
        layout.addWidget(self.list)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        paint_glass(self, painter, radius=theme.RADIUS_BUTTON)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        # Outside clicks also close Qt.Popup windows; reset the combo's state.
        if self.selector._popup_owner is not None:
            self.selector._popup_owner.removeEventFilter(self.selector)
            self.selector._popup_owner = None
        QComboBox.hidePopup(self.selector)
        self.selector.update()


class LauncherComboBox(QComboBox):
    """Shared glass selector with content sizing and a field-width popup."""

    def __init__(self, parent: QWidget | None = None, *, height: int = 48,
                 min_width: int = 100, max_width: int = 280, prefix: str = ""):
        super().__init__(parent)
        self._prefix = prefix
        self._popup: _DropdownPopup | None = None
        self._popup_owner: QWidget | None = None
        self.setFixedHeight(height)
        self.setMinimumWidth(min_width)
        self.setMaximumWidth(max_width)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMaxVisibleItems(8)

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        label_width = max((metrics.horizontalAdvance(self.itemText(i))
                           for i in range(self.count())), default=metrics.horizontalAdvance(self.placeholderText()))
        prefix_width = metrics.horizontalAdvance(self._prefix) + 8 if self._prefix else 0
        width = min(self.maximumWidth(), max(self.minimumWidth(), label_width + prefix_width + 44))
        return QSize(width, self.minimumHeight())

    def minimumSizeHint(self) -> QSize:
        return QSize(self.minimumWidth(), self.minimumHeight())

    def view(self) -> QListView:
        if self._popup is None:
            self._popup = _DropdownPopup(self)
        return self._popup.list

    def showPopup(self) -> None:
        if not self.isEnabled() or not self.count() or not self.isVisible():
            return
        view = self.view()
        if self._popup.isVisible():
            self.hidePopup()
            return
        view.setModel(self.model())
        view.setModelColumn(self.modelColumn())
        view.setRootIndex(self.rootModelIndex())
        view.setFont(self.font())
        owner = self.window()
        self._popup.setPalette(owner.palette())
        available = owner.rect().translated(owner.mapToGlobal(QPoint(0, 0)))
        screen = self.screen()
        if screen is not None:
            available = available.intersected(screen.availableGeometry())
        available.adjust(4, 4, -4, -4)
        top = self.mapToGlobal(QPoint(0, 0))
        bottom = self.mapToGlobal(QPoint(0, self.height()))
        below, above = available.bottom() - bottom.y() - 4, top.y() - available.top() - 4
        row_height = max(34, self.height() - 2)
        desired_height = min(self.count(), self.maxVisibleItems()) * row_height + 12
        open_below = desired_height <= below or below >= above
        height = min(desired_height, max(1, below if open_below else above))
        width = min(self.width(), available.width())
        x = max(available.left(), min(top.x(), available.right() - width + 1))
        y = bottom.y() + 4 if open_below else top.y() - height - 4
        self._popup.setGeometry(x, max(available.top(), y), width, height)
        self._popup_owner = owner
        owner.installEventFilter(self)
        self._popup.show()
        index = self.model().index(self.currentIndex(), self.modelColumn(), self.rootModelIndex())
        view.setCurrentIndex(index)
        view.scrollTo(index, QAbstractItemView.ScrollHint.EnsureVisible)
        view.setFocus(Qt.FocusReason.PopupFocusReason)
        self.update()

    def hidePopup(self) -> None:
        if self._popup is not None:
            self._popup.hide()
        if self._popup_owner is not None:
            self._popup_owner.removeEventFilter(self)
            self._popup_owner = None
        super().hidePopup()
        self.update()

    def _choose_index(self, index) -> None:
        if not index.isValid() or not index.flags() & Qt.ItemFlag.ItemIsEnabled:
            return
        row = index.row()
        self.hidePopup()
        self.setCurrentIndex(row)
        self.activated.emit(row)
        self.textActivated.emit(self.itemText(row))

    def eventFilter(self, watched, event) -> bool:
        if watched is self._popup_owner and event.type() in (
            QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Hide, QEvent.Type.WindowDeactivate,
        ):
            self.hidePopup()
        return super().eventFilter(watched, event)

    def hideEvent(self, event) -> None:
        self.hidePopup()
        super().hideEvent(event)

    def resizeEvent(self, event) -> None:
        self.hidePopup()
        super().resizeEvent(event)

    def wheelEvent(self, event) -> None:
        # Scrolling a page must not accidentally change its filters or theme.
        event.ignore()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_F4) or (
            event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down) and event.modifiers() & Qt.KeyboardModifier.AltModifier
        ):
            self.showPopup()
        else:
            super().keyPressEvent(event)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        is_open = self._popup is not None and self._popup.isVisible()
        paint_glass(self, painter, radius=theme.RADIUS_FIELD,
                    opacity=GLASS_OPACITY + (theme.SELECTOR_OPEN_OPACITY if is_open
                                             else theme.SELECTOR_HOVER_OPACITY if self.underMouse() else 0))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent = self.window().palette().color(QPalette.ColorRole.Highlight)
        if self.hasFocus() and self.property("keyboardFocus"):
            painter.setPen(QPen(accent, theme.STROKE_FOCUS))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), theme.RADIUS_FIELD, theme.RADIUS_FIELD)
        painter.setFont(self.font())
        left = 12
        if self._prefix:
            painter.setPen(QColor(MUTED))
            prefix_width = painter.fontMetrics().horizontalAdvance(self._prefix)
            painter.drawText(self.rect().adjusted(left, 0, -32, 0), Qt.AlignmentFlag.AlignVCenter, self._prefix)
            left += prefix_width + 8
        painter.setPen(QColor(TEXT if self.isEnabled() else MUTED))
        label_bounds = self.rect().adjusted(left, 0, -32, 0)
        label = painter.fontMetrics().elidedText(self.currentText() or self.placeholderText(),
                                                Qt.TextElideMode.ElideRight, max(0, label_bounds.width()))
        painter.drawText(label_bounds, Qt.AlignmentFlag.AlignVCenter, label)
        painter.setPen(QPen(accent if is_open else QColor(MUTED), theme.STROKE_CHEVRON, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        x, y = self.width() - 17, self.height() / 2
        direction = -1 if is_open else 1
        arrow = QPainterPath()
        arrow.moveTo(x - 4, y - direction * 2)
        arrow.lineTo(x, y + direction * 2)
        arrow.lineTo(x + 4, y - direction * 2)
        painter.drawPath(arrow)


def compose_profile_surface(artwork_path: str, icon_path: str, w: int, h: int, scale: float,
                            images: "ContentImages | None" = None) -> QPixmap:
    """Artwork/caption surface shared by shelf widgets and virtual library cards."""
    bounds = QRectF(0, 0, w, h).adjusted(1, 1, -1, -1)
    source = Path(artwork_path)
    bundled = source.parent / "blurred" / source.name
    frosted_path = str(bundled) if bundled.is_file() else artwork_path
    surface = QPixmap(ceil(w * scale), ceil(h * scale))
    surface.setDevicePixelRatio(scale)
    surface.fill(Qt.GlobalColor.transparent)
    p = QPainter(surface)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
    clip = QPainterPath()
    clip.addRoundedRect(bounds, theme.RADIUS_CARD, theme.RADIUS_CARD)
    p.setClipPath(clip)
    p.fillRect(bounds, QColor(SURFACE))
    if images is None:
        artwork = card_artwork_thumbnail(artwork_path)
        frosted = card_frosted_thumbnail(artwork_path)
        icon = artwork_image(icon_path)
    else:
        artwork = images.get(artwork_path, 480)
        frosted = images.get(frosted_path, 480)
        icon = images.get(icon_path, 32)
    if artwork is not None:
        draw_cover(p, artwork, bounds)
    caption = QRectF(bounds.left(), h - 60, bounds.width(), 59)
    p.save()
    p.setClipRect(caption, Qt.ClipOperation.IntersectClip)
    if frosted is not None or artwork is not None:
        draw_cover(p, frosted if frosted is not None else artwork, bounds)
    p.fillRect(caption, theme.with_alpha(SURFACE, theme.CARD_CAPTION_ALPHA))
    p.restore()
    shade = QLinearGradient(0, h * 0.32, 0, h)
    shade.setColorAt(0, theme.with_alpha(SURFACE, theme.CARD_SHADE_TOP_ALPHA))
    shade.setColorAt(1, theme.with_alpha(SURFACE, theme.CARD_SHADE_BOTTOM_ALPHA))
    p.fillRect(bounds, shade)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    if icon is not None:
        p.drawPixmap(QRectF(14, 14, 28, 28), icon, QRectF(icon.rect()))
    p.end()
    return surface


def paint_profile_caption(painter: QPainter, title: str, details: str, w: int, h: int,
                          accent: str, *, selected: bool = False, has_actions: bool = False,
                          highlighted: bool = False) -> None:
    """Keep artwork cards identical in native widgets and model/view rendering."""
    bounds = QRectF(0, 0, w, h).adjusted(1, 1, -1, -1)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    painter.setPen(QColor(TEXT))
    painter.setFont(ui_font(theme.FONT_ROW_TITLE, bold=True))
    title = painter.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight, w - 28)
    painter.drawText(14, h - 32, title)
    painter.setPen(QColor(MUTED))
    painter.setFont(ui_font(theme.FONT_SMALL))
    details = painter.fontMetrics().elidedText(details, Qt.TextElideMode.ElideRight, w - 28)
    painter.drawText(14, h - 14, details)
    if selected:
        marker = w - (66 if has_actions else 31)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(accent))
        painter.drawEllipse(QRectF(marker, 13, 18, 18))
        painter.setPen(QPen(QColor(SURFACE), theme.STROKE_SELECTION, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        check = QPainterPath()
        check.moveTo(marker + 5, 22)
        check.lineTo(marker + 8, 25)
        check.lineTo(marker + 13, 19)
        painter.drawPath(check)
    if selected or highlighted:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(accent), theme.STROKE_SELECTION))
        painter.drawRoundedRect(bounds, theme.RADIUS_CARD, theme.RADIUS_CARD)


def paint_profile_actions(painter: QPainter, center: QPoint) -> None:
    """Draw the menu dots without triggering an expensive fallback font lookup."""
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(TEXT))
    for offset in (-5, 0, 5):
        painter.drawEllipse(QRectF(center.x() + offset - 1.5, center.y() - 1.5, 3, 3))


@lru_cache(maxsize=8)
def profile_actions_icon(scale: float) -> QIcon:
    pixmap = QPixmap(ceil(18 * scale), ceil(18 * scale))
    pixmap.setDevicePixelRatio(scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    paint_profile_actions(painter, QPoint(9, 9))
    painter.end()
    return QIcon(pixmap)


class ProfileCard(QAbstractButton):
    """An artwork card with native button, keyboard, and selection semantics."""

    def __init__(self, title: str, details: str, artwork: Path, icon: Path,
                 accent: str, parent: QWidget | None = None, *,
                 images: "ContentImages | None" = None):
        super().__init__(parent)
        self.title, self.details = title, details
        self._artwork, self._icon = str(artwork), str(icon)
        self._images = images
        source = Path(artwork)
        bundled = source.parent / "blurred" / source.name
        self._frosted_artwork = str(bundled) if bundled.is_file() else self._artwork
        if images is not None:
            self._image_keys = {images.key(self._artwork, 480),
                                images.key(self._frosted_artwork, 480),
                                images.key(self._icon, 32)}
            images.ready.connect(self._image_ready)
        self._accent = accent
        self._actions_menu: QMenu | None = None
        self._actions_button: QToolButton | None = None
        self._surface: QPixmap | None = None
        self._surface_size: tuple[int, int, float] | None = None
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(150)
        self.setMinimumWidth(160)
        self.setAccessibleName(title)
        self.setAccessibleDescription(details)
        self.setToolTip(f"{title}\n{details}")

    def sizeHint(self) -> QSize:
        return QSize(280, 150)

    def _image_ready(self, key: str) -> None:
        if key in self._image_keys:
            self._surface = None
            self.update()

    def set_accent(self, accent: str) -> None:
        self._accent = accent
        self.update()

    def hideEvent(self, event) -> None:
        self._surface = None
        super().hideEvent(event)

    def set_actions_menu(self, menu: QMenu) -> None:
        self._actions_menu = menu
        if self._actions_button is None:
            self._actions_button = QToolButton(self)
            self._actions_button.setIcon(profile_actions_icon(self.devicePixelRatioF()))
            self._actions_button.setIconSize(QSize(18, 18))
            self._actions_button.setObjectName("cardActions")
            self._actions_button.setFixedSize(30, 30)
            self._actions_button.setAccessibleName(f"Actions for {self.title}")
            self._actions_button.setToolTip("Profile actions")
            self._actions_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._actions_button.setMenu(menu)
        self._actions_button.move(self.width() - 42, 10)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._surface = None
        if self._actions_button is not None:
            self._actions_button.move(self.width() - 42, 10)

    def contextMenuEvent(self, event) -> None:
        if self._actions_menu is not None:
            self._actions_menu.popup(event.globalPos())
            event.accept()
        else:
            super().contextMenuEvent(event)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.update()

    def _compose_surface(self, bounds: QRectF | None = None) -> QPixmap:
        return compose_profile_surface(self._artwork, self._icon, max(self.width(), 160),
                                       max(self.height(), 150), self.devicePixelRatioF(), self._images)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        if not self.isEnabled():
            painter.setOpacity(theme.DISABLED_CARD_OPACITY)
        bounds = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        key = (self.width(), self.height(), self.devicePixelRatioF())
        if self._surface is None or self._surface_size != key:
            self._surface = self._compose_surface(bounds)
            self._surface_size = key
        painter.drawPixmap(0, 0, self._surface)
        paint_profile_caption(painter, self.title, self.details, self.width(), self.height(), self._accent,
                              selected=self.isChecked(), has_actions=self._actions_button is not None,
                              highlighted=self.underMouse() or bool(self.hasFocus() and self.property("keyboardFocus")))
