"""Artwork and compact controls shared by the new Qt frontend."""

from functools import lru_cache
from math import ceil, exp, hypot
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import (
    QAbstractAnimation, QEasingCurve, QElapsedTimer, QEvent, QObject, QParallelAnimationGroup,
    QPoint, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer, QVariantAnimation,
)
from PyQt6.QtGui import (
    QColor, QIcon, QImageReader, QLinearGradient, QPainter, QPainterPath, QPalette,
    QPen, QPixmap, QRegion,
)
from PyQt6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QAbstractScrollArea, QApplication, QComboBox, QFrame, QGraphicsBlurEffect,
    QGraphicsOpacityEffect, QGraphicsPixmapItem, QGraphicsScene, QLabel, QLineEdit, QListView, QMenu, QPushButton,
    QScrollArea, QScrollBar, QSizePolicy, QStyle, QStyledItemDelegate, QToolButton, QVBoxLayout, QWidget,
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
        self._frost_progress = 0.0
        self._frost_anim = QVariantAnimation(self)
        self._frost_anim.setDuration(220)
        self._frost_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._frost_anim.valueChanged.connect(self._on_frost_step)
        self._artwork_prev_frame: QPixmap | None = None
        self._artwork_progress = 1.0
        self._artwork_anim = QVariantAnimation(self)
        self._artwork_anim.setDuration(240)
        self._artwork_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._artwork_anim.valueChanged.connect(self._on_artwork_step)
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

    def _on_frost_step(self, value: object) -> None:
        self._frost_progress = float(value)
        self.update()

    def set_frosted(self, frosted: bool) -> None:
        if self._frosted != frosted:
            self._frosted = frosted
            self._frost_anim.stop()
            self._frost_anim.setStartValue(self._frost_progress)
            self._frost_anim.setEndValue(1.0 if frosted else 0.0)
            self._frost_anim.start()

    def set_home_shading(self, enabled: bool) -> None:
        if self._home_shading != enabled:
            self._home_shading = enabled
            self._frames.clear()
            self.update()
            for child in self.findChildren(QWidget):
                if child.isVisible():
                    child.update()

    def _on_artwork_step(self, value: object) -> None:
        self._artwork_progress = float(value)
        if self._artwork_progress >= 1.0:
            self._artwork_prev_frame = None
        self.update()

    def set_artwork(self, artwork: Path) -> None:
        if str(artwork) != self._artwork:
            prev = self._frames.get(self._frosted) or self._frames.get(False)
            self._artwork = str(artwork)
            self._softened_artwork = self._find_softened_artwork()
            self._frames.clear()
            self._last_images.clear()
            if prev is not None and not prev.isNull():
                self._artwork_prev_frame = prev
                self._artwork_anim.stop()
                self._artwork_progress = 0.0
                self._artwork_anim.setStartValue(0.0)
                self._artwork_anim.setEndValue(1.0)
                self._artwork_anim.start()
            else:
                self._artwork_prev_frame = None
                self._artwork_progress = 1.0
            self.update()

    def _paint_current_artwork(self, painter: QPainter) -> None:
        if self._frost_progress <= 0.0:
            self.paint_artwork(painter, frosted=False)
        elif self._frost_progress >= 1.0:
            self.paint_artwork(painter, frosted=True)
        else:
            self.paint_artwork(painter, frosted=False)
            painter.save()
            painter.setOpacity(self._frost_progress)
            self.paint_artwork(painter, frosted=True)
            painter.restore()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        if self._artwork_prev_frame is not None and self._artwork_progress < 1.0:
            painter.drawPixmap(0, 0, self._artwork_prev_frame)
            painter.save()
            painter.setOpacity(self._artwork_progress)
            self._paint_current_artwork(painter)
            painter.restore()
        else:
            self._paint_current_artwork(painter)

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
                image = self._last_images.get(frosted)
                if image is None and not frosted and Path(self._artwork).is_file():
                    image = artwork_image(self._artwork)
                elif image is None:
                    image = QPixmap()
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
        enable_smooth_scroll(self)
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


@lru_cache(maxsize=24)
def _cached_blur_pixmap(cache_key: int, width: int, height: int, radius: float, pixmap_ref: QPixmap) -> QPixmap:
    """Blur a QPixmap once using QGraphicsBlurEffect and cache by cacheKey."""
    if pixmap_ref.isNull():
        return pixmap_ref
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(pixmap_ref)
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(radius)
    effect.setBlurHints(QGraphicsBlurEffect.BlurHint.PerformanceHint)
    item.setGraphicsEffect(effect)
    scene.addItem(item)
    out = QPixmap(pixmap_ref.size())
    out.setDevicePixelRatio(pixmap_ref.devicePixelRatioF())
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    scene.render(painter, QRectF(0, 0, width, height), QRectF(0, 0, width, height))
    painter.end()
    return out


def blur_pixmap(pixmap: QPixmap, radius: float = 18.0) -> QPixmap:
    """Return a cached blurred copy of a QPixmap."""
    if pixmap.isNull():
        return pixmap
    return _cached_blur_pixmap(pixmap.cacheKey(), pixmap.width(), pixmap.height(), radius, pixmap)


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
        frosted = images.get(frosted_path, 480) if bundled.is_file() else None
        icon = images.get(icon_path, 32)
    if frosted is None and artwork is not None:
        frosted = blur_pixmap(artwork, 18.0)
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


REVEAL_TOTAL_MS = 500
REVEAL_SPREAD_MS = 100.0
REVEAL_NEAR_MS = 320.0
REVEAL_FAR_DELTA_MS = 80.0
REVEAL_RISE_PX = 16.0


def reveal_wave_window(ratio: float) -> tuple[float, float]:
    """Return (start_t, span_t) in [0, 1] for an element at normalized distance ratio."""
    clamped = max(0.0, min(1.0, ratio))
    start_t = (clamped * REVEAL_SPREAD_MS) / REVEAL_TOTAL_MS
    span_t = (REVEAL_NEAR_MS + clamped * REVEAL_FAR_DELTA_MS) / REVEAL_TOTAL_MS
    return start_t, span_t


def reveal_wave_sample(progress: float, start_t: float, span_t: float) -> tuple[float, float]:
    """Return (opacity, dy_px) using OneClient-style OutCubic Soft Rise & Settle."""
    local = max(0.0, min(1.0, (progress - start_t) / max(span_t, 1e-4)))
    eased = 1.0 - (1.0 - local) ** 3
    return eased, (1.0 - eased) * REVEAL_RISE_PX


class _RevealOverlay(QWidget):
    """Lightweight sub-pixel QPainter overlay for 60fps reveal waves."""

    def __init__(self, parent: QWidget, items: list[tuple[QPixmap, QPointF, float, float]], rise_scale: float):
        super().__init__(parent)
        self._items = items
        self._rise_scale = rise_scale
        self._progress = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setGeometry(parent.rect())
        self.raise_()
        self.show()

    def set_progress(self, progress: float) -> None:
        self._progress = progress
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        for pixmap, origin, start_t, span_t in self._items:
            opacity, dy = reveal_wave_sample(self._progress, start_t, span_t)
            if opacity <= 0.0:
                continue
            painter.setOpacity(opacity)
            painter.drawPixmap(QPointF(origin.x(), origin.y() + dy * self._rise_scale), pixmap)


class StaggeredReveal(QObject):
    """Interruptible, misplace-resistant OutCubic sub-pixel Soft Rise & Settle wave."""

    def __init__(self, parent: QObject | None = None, *, duration_ms: int = REVEAL_TOTAL_MS,
                 offset_y: float = REVEAL_RISE_PX, max_items: int = 24):
        super().__init__(parent)
        self._duration_ms = duration_ms
        self._offset_y = float(offset_y)
        self._max_items = max_items
        self._widgets: list[QWidget] = []
        self._overlay: _RevealOverlay | None = None
        self._container: QWidget | None = None
        self._generation = 0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(self._duration_ms)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.Linear)
        self._anim.valueChanged.connect(self._on_step)
        self._anim.finished.connect(self._on_finished)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._container and event.type() in (QEvent.Type.Resize, QEvent.Type.Hide):
            self.stop()
        return super().eventFilter(watched, event)

    def stop(self) -> None:
        self._generation += 1
        if self._anim.state() != QAbstractAnimation.State.Stopped:
            self._anim.stop()
        if self._container is not None:
            try:
                self._container.removeEventFilter(self)
            except RuntimeError:
                pass
            self._container = None
        if self._overlay is not None:
            try:
                self._overlay.hide()
                self._overlay.deleteLater()
            except RuntimeError:
                pass
            self._overlay = None
        for widget in self._widgets:
            try:
                widget.setGraphicsEffect(None)
            except RuntimeError:
                pass
        self._widgets.clear()

    def reveal(self, container: QWidget, *, origin: QPoint | None = None,
               targets: list[QWidget] | None = None) -> None:
        self.stop()
        gen = self._generation
        QTimer.singleShot(0, lambda: self._start_wave(container, origin, targets, gen))

    def _collect_targets(self, container: QWidget) -> list[QWidget]:
        candidates: list[QWidget] = []
        seen: set[int] = set()
        for child in container.findChildren(QWidget):
            if not child.isVisible() or child.width() < 20 or child.height() < 20:
                continue
            if isinstance(child, QListView):
                continue
            is_block = isinstance(child, (GlassPanel, ProfileCard)) or child.objectName() in ("homeHero", "launchBar")
            is_control = isinstance(child, (QAbstractButton, QLineEdit, QComboBox))
            if is_block or is_control:
                parent = child.parentWidget()
                skip = False
                while parent is not None and parent is not container:
                    if id(parent) in seen or isinstance(parent, QListView):
                        skip = True
                        break
                    parent = parent.parentWidget()
                if not skip:
                    seen.add(id(child))
                    candidates.append(child)
        return candidates[:self._max_items]

    def _activate_layouts(self, container: QWidget) -> None:
        if container.layout() is not None:
            container.layout().activate()
        for child in container.findChildren(QWidget):
            if child.layout() is not None and child.isVisible():
                child.layout().activate()

    def _start_wave(self, container: QWidget, origin: QPoint | None,
                    targets: list[QWidget] | None, gen: int) -> None:
        if gen != self._generation:
            return
        try:
            if not container.isVisible():
                return
        except RuntimeError:
            return

        self._activate_layouts(container)
        wave_origin = origin if origin is not None else QPoint(0, 0)

        for view in container.findChildren(QListView):
            if view.isVisible() and callable(getattr(view, "reveal_wave", None)):
                view_origin = view.viewport().mapFrom(container, wave_origin)
                view.reveal_wave(view_origin)

        widgets = [w for w in (targets if targets is not None else self._collect_targets(container)) if w.isVisible()]
        if not widgets:
            return

        scored: list[tuple[float, QWidget]] = []
        for w in widgets:
            center = w.mapTo(container, QPoint(w.width() // 2, w.height() // 2))
            dist = hypot(center.x() - wave_origin.x(), center.y() - wave_origin.y())
            scored.append((dist, w))
        scored.sort(key=lambda item: item[0])

        min_dist = scored[0][0]
        max_dist = max(scored[-1][0], min_dist + 1.0)
        span = max_dist - min_dist

        overlay_items: list[tuple[QPixmap, QPointF, float, float]] = []
        for dist, widget in scored:
            ratio = (dist - min_dist) / span
            start_t, span_t = reveal_wave_window(ratio)
            dpr = widget.devicePixelRatioF()
            pixmap = QPixmap(max(1, round(widget.width() * dpr)), max(1, round(widget.height() * dpr)))
            pixmap.setDevicePixelRatio(dpr)
            pixmap.fill(Qt.GlobalColor.transparent)
            was_translucent = widget.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            try:
                widget.render(
                    pixmap,
                    QPoint(0, 0),
                    QRegion(),
                    QWidget.RenderFlag.DrawWindowBackground | QWidget.RenderFlag.DrawChildren,
                )
            finally:
                widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, was_translucent)
            pos = QPointF(widget.mapTo(container, QPoint(0, 0)))
            effect = QGraphicsOpacityEffect(widget)
            effect.setOpacity(0.0)
            widget.setGraphicsEffect(effect)
            self._widgets.append(widget)
            overlay_items.append((pixmap, pos, start_t, span_t))

        self._container = container
        container.installEventFilter(self)
        rise_scale = self._offset_y / max(REVEAL_RISE_PX, 1e-4)
        self._overlay = _RevealOverlay(container, overlay_items, rise_scale)
        self._anim.setDuration(self._duration_ms)
        self._anim.start()

    def _on_step(self, value: object) -> None:
        if self._overlay is not None:
            self._overlay.set_progress(float(value))

    def _on_finished(self) -> None:
        self.stop()


class _ScrollAxis:
    """State for one smooth-scrolling scrollbar axis."""

    def __init__(self, bar: QScrollBar):
        self.bar = bar
        self.current = float(bar.value())
        self.target = float(bar.value())
        self.active = False


class SmoothScrollFilter(QObject):
    """Exponential-glide scroll filter with 1:1 touchpad passthrough and keyboard support."""

    def __init__(
        self,
        area: QAbstractScrollArea,
        *,
        step_px: float = 112.0,
        decay: float = 14.5,
    ):
        super().__init__(area)
        self._area = area
        self._step_px = step_px
        self._decay = decay
        self._internal_set = False
        self._elapsed = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._axes: dict[Qt.Orientation, _ScrollAxis] = {
            Qt.Orientation.Vertical: _ScrollAxis(area.verticalScrollBar()),
            Qt.Orientation.Horizontal: _ScrollAxis(area.horizontalScrollBar()),
        }
        for axis in self._axes.values():
            axis.bar.valueChanged.connect(lambda val, a=axis: self._on_bar_changed(a, val))
            axis.bar.sliderPressed.connect(lambda a=axis: self._sync_axis(a))
            axis.bar.rangeChanged.connect(lambda lo, hi, a=axis: self._on_range_changed(a, lo, hi))
        area.viewport().installEventFilter(self)
        area.installEventFilter(self)

    def _set_bar_value(self, axis: _ScrollAxis, value: int) -> None:
        if value != axis.bar.value():
            self._internal_set = True
            try:
                axis.bar.setValue(value)
            finally:
                self._internal_set = False

    def _tick(self) -> None:
        dt = min(max(self._elapsed.restart() / 1000.0, 0.001), 0.05)
        alpha = 1.0 - exp(-self._decay * dt)
        any_active = False
        for axis in self._axes.values():
            if not axis.active:
                continue
            diff = axis.target - axis.current
            if abs(diff) < 1.0:
                axis.current = axis.target
                axis.active = False
            else:
                axis.current += diff * alpha
                any_active = True
            self._set_bar_value(axis, round(axis.current))
        if not any_active:
            self._timer.stop()

    def _ensure_running(self) -> None:
        if not self._timer.isActive():
            self._elapsed.start()
            self._timer.start()

    def _on_bar_changed(self, axis: _ScrollAxis, value: int) -> None:
        if not self._internal_set:
            axis.active = False
            axis.current = float(value)
            axis.target = float(value)
            if not any(a.active for a in self._axes.values()):
                self._timer.stop()

    def _sync_axis(self, axis: _ScrollAxis) -> None:
        axis.active = False
        val = float(axis.bar.value())
        axis.current = val
        axis.target = val
        if not any(a.active for a in self._axes.values()):
            self._timer.stop()

    def _on_range_changed(self, axis: _ScrollAxis, lo: int, hi: int) -> None:
        f_lo, f_hi = float(lo), float(hi)
        axis.current = min(max(axis.current, f_lo), f_hi)
        axis.target = min(max(axis.target, f_lo), f_hi)

    @staticmethod
    def _has_range(axis: _ScrollAxis) -> bool:
        return axis.bar.maximum() > axis.bar.minimum()

    @staticmethod
    def _at_boundary(axis: _ScrollAxis, delta_px: float) -> bool:
        if delta_px > 0:
            return axis.target <= axis.bar.minimum() and axis.bar.value() <= axis.bar.minimum()
        if delta_px < 0:
            return axis.target >= axis.bar.maximum() and axis.bar.value() >= axis.bar.maximum()
        return True

    def _apply_pixel_delta(self, axis: _ScrollAxis, delta_px: float) -> bool:
        if delta_px == 0 or not self._has_range(axis):
            return False
        if self._at_boundary(axis, delta_px):
            return False
        axis.active = False
        if not any(a.active for a in self._axes.values()):
            self._timer.stop()
        lo, hi = float(axis.bar.minimum()), float(axis.bar.maximum())
        new_val = min(max(axis.current - delta_px, lo), hi)
        axis.current = new_val
        axis.target = new_val
        self._set_bar_value(axis, round(new_val))
        return True

    def _glide_by(self, axis: _ScrollAxis, delta_px: float) -> bool:
        if delta_px == 0 or not self._has_range(axis):
            return False
        if self._at_boundary(axis, delta_px):
            return False
        if not axis.active:
            axis.current = float(axis.bar.value())
            axis.target = axis.current
        lo, hi = float(axis.bar.minimum()), float(axis.bar.maximum())
        max_lead = max(float(axis.bar.pageStep()) * 2.5, 640.0)
        new_target = min(max(axis.target - delta_px, lo), hi)
        new_target = min(max(new_target, axis.current - max_lead), axis.current + max_lead)
        axis.target = min(max(new_target, lo), hi)
        axis.active = True
        self._ensure_running()
        return True

    def _glide_to(self, axis: _ScrollAxis, target_val: float) -> bool:
        if not self._has_range(axis):
            return False
        if not axis.active:
            axis.current = float(axis.bar.value())
        lo, hi = float(axis.bar.minimum()), float(axis.bar.maximum())
        axis.target = min(max(target_val, lo), hi)
        if abs(axis.target - axis.current) < 1.0:
            return False
        axis.active = True
        self._ensure_running()
        return True

    def _handle_key_press(self, event: QEvent) -> bool:
        if isinstance(self._area, _DropdownListView):
            return False
        if event.modifiers() != Qt.KeyboardModifier.NoModifier:
            return False
        key = event.key()
        v_axis = self._axes[Qt.Orientation.Vertical]
        h_axis = self._axes[Qt.Orientation.Horizontal]
        page = float(max(v_axis.bar.pageStep() - 24, 48))

        if key == Qt.Key.Key_PageDown:
            return self._glide_by(v_axis, -page)
        if key == Qt.Key.Key_PageUp:
            return self._glide_by(v_axis, page)

        if not isinstance(self._area, QScrollArea):
            return False
        if key == Qt.Key.Key_Down:
            return self._glide_by(v_axis, -64.0)
        if key == Qt.Key.Key_Up:
            return self._glide_by(v_axis, 64.0)
        if key == Qt.Key.Key_Right:
            return self._glide_by(h_axis, -64.0)
        if key == Qt.Key.Key_Left:
            return self._glide_by(h_axis, 64.0)
        if key == Qt.Key.Key_Home:
            return self._glide_to(v_axis, float(v_axis.bar.minimum()))
        if key == Qt.Key.Key_End:
            return self._glide_to(v_axis, float(v_axis.bar.maximum()))
        return False

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        etype = event.type()
        if etype not in (QEvent.Type.Wheel, QEvent.Type.KeyPress):
            return False
        try:
            area = self._area
            viewport = area.viewport()
        except RuntimeError:
            return False

        if watched in (area, viewport) and etype == QEvent.Type.KeyPress:
            if self._handle_key_press(event):
                event.accept()
                return True
            return False

        if watched is viewport and etype == QEvent.Type.Wheel:
            pixel = event.pixelDelta()
            if not pixel.isNull():
                v_axis = self._axes[Qt.Orientation.Vertical]
                h_axis = self._axes[Qt.Orientation.Horizontal]
                handled = False
                if pixel.y() != 0:
                    target = v_axis if self._has_range(v_axis) else h_axis
                    handled = self._apply_pixel_delta(target, float(pixel.y())) or handled
                if pixel.x() != 0:
                    handled = self._apply_pixel_delta(h_axis, float(pixel.x())) or handled
                if handled:
                    event.accept()
                    return True
                return False

            angle = event.angleDelta()
            v_axis = self._axes[Qt.Orientation.Vertical]
            h_axis = self._axes[Qt.Orientation.Horizontal]
            handled = False
            if (
                event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                and angle.y() != 0
                and angle.x() == 0
                and self._has_range(h_axis)
            ):
                handled = self._glide_by(h_axis, (angle.y() / 120.0) * self._step_px)
            else:
                if angle.y() != 0:
                    target = v_axis if self._has_range(v_axis) else h_axis
                    handled = self._glide_by(target, (angle.y() / 120.0) * self._step_px) or handled
                if angle.x() != 0:
                    handled = self._glide_by(h_axis, (angle.x() / 120.0) * self._step_px) or handled
            if handled:
                event.accept()
                return True
            return False
        return super().eventFilter(watched, event)


def enable_smooth_scroll(
    area: QAbstractScrollArea,
    *,
    step_px: float = 112.0,
    decay: float = 14.5,
) -> SmoothScrollFilter:
    """Attach exponential-glide smooth scrolling to a QScrollArea, QListView, or QTextBrowser."""
    existing = getattr(area, "_smooth_scroll_filter", None)
    if isinstance(existing, SmoothScrollFilter):
        return existing
    if isinstance(area, QAbstractItemView):
        area.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        area.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    filt = SmoothScrollFilter(area, step_px=step_px, decay=decay)
    area._smooth_scroll_filter = filt
    return filt
