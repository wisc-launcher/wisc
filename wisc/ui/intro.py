"""Full-window startup intro overlay for Wisc Launcher."""

from __future__ import annotations

from math import hypot
from pathlib import Path

from PyQt6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QMovie, QPainter, QPixmap, QRadialGradient
from PyQt6.QtWidgets import QWidget

from wisc.core.paths import ASSETS_DIR


BLACK = QColor("#000000")


class StartupIntroOverlay(QWidget):
    """Show the logo and title animation until Home is ready to reveal."""

    first_painted = pyqtSignal()
    finished = pyqtSignal()

    def __init__(
        self,
        parent: QWidget,
        *,
        logo_path: Path | None = None,
        text_animation_path: Path | None = None,
        home_ready: bool = True,
        logo_fade_ms: int = 850,
        text_delay_ms: int = 620,
        hold_ms: int = 350,
        fade_out_ms: int = 680,
    ) -> None:
        super().__init__(parent)
        resolved_logo = logo_path or (ASSETS_DIR / "icons" / "wisc_mark.png")
        self._text_animation_path = text_animation_path or (ASSETS_DIR / "intro" / "wisc_text.webp")
        self._logo = QPixmap(str(resolved_logo)) if resolved_logo.is_file() else QPixmap()
        self._text_delay_ms = text_delay_ms
        self._hold_ms = hold_ms
        self._home_ready = home_ready
        self._painted = False

        self._logo_alpha = 0.0
        self._exit_progress = 0.0
        self._text_frame: QPixmap | None = None
        self._movie: QMovie | None = None
        self._exiting = False

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._logo_anim = QVariantAnimation(self)
        self._logo_anim.setStartValue(0.0)
        self._logo_anim.setEndValue(1.0)
        self._logo_anim.setDuration(logo_fade_ms)
        self._logo_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._logo_anim.valueChanged.connect(self._on_logo_tick)

        self._text_timer = QTimer(self)
        self._text_timer.setSingleShot(True)
        self._text_timer.timeout.connect(self._start_text_animation)

        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.timeout.connect(lambda: self._begin_fade_out(duration_ms=fade_out_ms))

        self._fade_anim = QVariantAnimation(self)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setDuration(fade_out_ms)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.Linear)
        self._fade_anim.valueChanged.connect(self._on_fade_tick)
        self._fade_anim.finished.connect(self._on_complete)

    def start(self) -> None:
        """Show the overlay over the full parent window and play the startup intro."""
        if self.parentWidget() is not None:
            self.setGeometry(self.parentWidget().rect())
        self._logo_anim.stop()
        self._fade_anim.stop()
        self._text_timer.stop()
        self._hold_timer.stop()
        self._release_movie()

        self._painted = False
        self._exiting = False
        self._logo_alpha = 0.0
        self._exit_progress = 0.0
        self._text_frame = None
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

        self.show()
        self.raise_()
        self.setFocus()

        if self._text_animation_path.is_file():
            self._text_timer.start(self._text_delay_ms)
        else:
            self._hold_timer.start(self._text_delay_ms + self._hold_ms)
        self._logo_anim.start()

    def skip(self) -> None:
        """Fade out early when the user clicks or presses a dismiss key."""
        self._begin_fade_out(duration_ms=180)

    def shutdown(self) -> None:
        """Stop timers and release the title frames."""
        self._logo_anim.stop()
        self._fade_anim.stop()
        self._text_timer.stop()
        self._hold_timer.stop()
        self._release_movie()
        self._text_frame = None
        self.hide()

    def set_home_ready(self) -> None:
        self._home_ready = True
        if self._exiting and self.isVisible():
            self._start_fade()

    def _start_text_animation(self) -> None:
        if self._exiting or not self.isVisible():
            return
        movie = QMovie(str(self._text_animation_path), b"webp", self)
        self._movie = movie
        movie.frameChanged.connect(self._on_frame)
        movie.finished.connect(self._on_text_finished)
        movie.error.connect(self._on_error)
        movie.start()

    def _release_movie(self) -> None:
        movie, self._movie = self._movie, None
        if movie is not None:
            movie.stop()
            movie.deleteLater()

    def _begin_fade_out(self, *, duration_ms: int | None = None) -> None:
        if self._exiting or not self.isVisible():
            return
        self._exiting = True
        self._text_timer.stop()
        self._hold_timer.stop()
        self._release_movie()
        if duration_ms is not None:
            self._fade_anim.setDuration(duration_ms)
        if self._home_ready:
            self._start_fade()

    def _start_fade(self) -> None:
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self._logo_anim.stop()
        self._fade_anim.start()

    def _on_logo_tick(self, value: object) -> None:
        self._logo_alpha = float(value)
        self.update()

    def _on_frame(self, _index: int) -> None:
        if self._movie is not None and not self._exiting:
            self._text_frame = self._movie.currentPixmap()
            self.update()

    def _on_text_finished(self) -> None:
        if not self._exiting:
            self._release_movie()
            self._hold_timer.start(self._hold_ms)

    def _on_error(self, *_args) -> None:
        self._begin_fade_out(duration_ms=180)

    def _on_fade_tick(self, value: object) -> None:
        self._exit_progress = float(value)
        self.update()

    def _on_complete(self) -> None:
        self.shutdown()
        self.finished.emit()

    def mousePressEvent(self, event) -> None:
        self.skip()
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Space, Qt.Key.Key_Return):
            self.skip()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event) -> None:
        t = self._exit_progress
        if t >= 0.999:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        rect = QRectF(self.rect())
        cx, cy = rect.center().x(), rect.center().y()

        # 1. Black backdrop: solid before exit, then soft center-out radial reveal
        if t <= 0.001:
            painter.fillRect(rect, BLACK)
        else:
            eased = 1.0 - (1.0 - t) ** 3
            max_r = hypot(cx, cy) * 1.15
            outer_r = max(1.0, max_r * eased * 1.45)
            inner_stop = max(0.0, min(0.75, eased * 0.82))
            edge_alpha = round(255 * (1.0 - max(0.0, (t - 0.55) / 0.45) ** 1.5))

            grad = QRadialGradient(QPointF(cx, cy), outer_r)
            grad.setColorAt(0.0, QColor(0, 0, 0, 0))
            if inner_stop > 0.01:
                grad.setColorAt(inner_stop, QColor(0, 0, 0, 0))
            grad.setColorAt(1.0, QColor(0, 0, 0, edge_alpha))
            painter.fillRect(rect, grad)

        # 2. Logo & "Wisc" softly dissolve + drift up as the center opens
        content_t = min(1.0, t / 0.58)
        content_alpha = 1.0 - (1.0 - (1.0 - content_t) ** 2) if t > 0.0 else 1.0
        content_dy = -8.0 * (1.0 - (1.0 - content_t) ** 3) if t > 0.0 else 0.0

        if content_alpha > 0.005:
            if not self._logo.isNull() and self._logo_alpha > 0.005:
                painter.save()
                painter.setOpacity(content_alpha * self._logo_alpha)
                draw_h = 92.0
                aspect = self._logo.width() / max(1, self._logo.height())
                draw_w = draw_h * aspect
                logo_rect = QRectF(
                    cx - draw_w / 2.0,
                    cy - 54.0 - draw_h / 2.0 + content_dy,
                    draw_w,
                    draw_h,
                )
                painter.drawPixmap(logo_rect, self._logo, QRectF(self._logo.rect()))
                painter.restore()

            if self._text_frame is not None and not self._text_frame.isNull():
                painter.save()
                painter.setOpacity(content_alpha)
                clip_w, clip_h = 360.0, 120.0
                text_rect = QRectF(
                    cx - clip_w / 2.0,
                    cy + 50.0 - clip_h / 2.0 + content_dy,
                    clip_w,
                    clip_h,
                )
                painter.drawPixmap(text_rect, self._text_frame, QRectF(self._text_frame.rect()))
                painter.restore()

        if not self._painted:
            self._painted = True
            self.first_painted.emit()
