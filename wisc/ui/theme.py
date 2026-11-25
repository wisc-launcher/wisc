"""Qt appearance: fonts, colors, radii, painter tokens, and scoped QSS.

Widgets own layout and interaction; keep their appearance values here. The
selectable Minecraft palettes remain shared with the classic frontend.
"""

import sys
from functools import lru_cache

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PyQt6.QtWidgets import QApplication, QWidget

from wisc.core.paths import ASSETS_DIR
from wisc.core.themes import DEFAULT_THEME, THEMES, get_theme


SURFACE = "#0B0D0A"
TEXT = "#F1F5EC"
MUTED = "#B1BAAD"
BASE = "#161A14"
ALTERNATE_BASE = "#20251D"
DISABLED_TEXT = "#74806C"
DEFAULT_ACCENT = "#46BA34"
SWITCH_TRACK = "#454C40"
SURFACE_COLORREF = int.from_bytes(bytes.fromhex(SURFACE[1:]), "little")  # Windows 0x00BBGGRR.

PIXEL_FONT_FAMILY = "Pixelify Sans"
WINDOWS_FONT_FAMILY = "Segoe UI"
FONT_SMALL = 11
FONT_DETAIL = 12
FONT_BODY = 13
FONT_LABEL = 14
FONT_ROW_TITLE = 15
FONT_SUBHEADING = 16
FONT_SHELF_HEADING = 17
FONT_SECTION_HEADING = 18
FONT_DIALOG_TITLE = 20
FONT_PLAYER = 22
FONT_PAGE_TITLE = 24
FONT_ADD_PROFILE = 32
FONT_HERO = 48

RADIUS_SQUARE = 0
RADIUS_FIELD = 5
RADIUS_BUTTON = 8
RADIUS_CARD = 12
RADIUS_PANEL = 14
PILL_RADIUS_RATIO = 0.5
STROKE_FOCUS = 1
STROKE_SELECTION = 2
STROKE_ICON = 1.6
STROKE_CHEVRON = 1.5

PAGE_MARGINS = (28, 20, 28, 16)
PAGE_SPACING = 16
HEADER_HEIGHT = 44
FIELD_HEIGHT = 48
PRIMARY_BUTTON_HEIGHT = 44
BUTTON_HEIGHT = 40
SEGMENT_HEIGHT = 36
COMPACT_HEIGHT = 34
PROGRESS_HOST_HEIGHT = 47

GLASS_OPACITY = 0.54
GLASS_PRESSED_OPACITY = 0.20
GLASS_HOVER_OPACITY = 0.11
GLASS_FOCUS_OPACITY = 0.08
SELECTOR_OPEN_OPACITY = 0.10
ROW_HOVER_OPACITY = SELECTOR_HOVER_OPACITY = 0.06
DISABLED_CARD_OPACITY = 0.55
ARTWORK_BLUR_RADIUS = 18
VIGNETTE_HORIZONTAL = ((0, 240), (0.32, 185), (0.62, 40), (0.85, 25), (1, 130))
VIGNETTE_VERTICAL = ((0, 0), (0.25, 0), (0.65, 45), (1, 245))
FEATURE_VIGNETTE_STRENGTH = 0.60
BUTTON_FOCUS_FILL = (255, 255, 255, 14)
SWITCH_ON_ALPHA = 100
SWITCH_OFF_ALPHA = 180
SWITCH_DISABLED_ALPHA = 65
SWITCH_DISABLED_THUMB_ALPHA = 105
DROPDOWN_HOVER_ALPHA = 38
CARD_CAPTION_ALPHA = 100
CARD_SHADE_TOP_ALPHA = 0
CARD_SHADE_BOTTOM_ALPHA = 160
WINDOW_PRESSED_ALPHA = 36
WINDOW_HOVER_ALPHA = 20

# Preserve local stylesheet scope rather than changing Qt's inheritance rules.
DIVIDER_STYLESHEET = "background: rgba(255, 255, 255, 18); border: none;"
ACCOUNT_BADGE_STYLESHEET = (
    f"background: rgba(255, 255, 255, 16); border-radius: {RADIUS_FIELD}px; padding: 3px 9px;"
)
AVATAR_STYLESHEET = f"background: rgba(255, 255, 255, 10); border-radius: {RADIUS_BUTTON}px;"
DROPDOWN_STYLESHEET = """
            QListView { background: transparent; border: 0; padding: 0; outline: 0; }
            QScrollBar:vertical { background: transparent; width: 6px; margin: 2px 0; }
            QScrollBar::handle:vertical { background: rgba(241, 245, 236, 65); border-radius: 3px; min-height: 24px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
        """


def with_alpha(color: str | QColor, alpha: int) -> QColor:
    """Copy a theme color with an 8-bit alpha for painter fills."""
    result = QColor(color)
    result.setAlpha(alpha)
    return result


class FocusCues(QObject):
    """Show button focus for keyboard navigation without outlining mouse clicks."""

    def __init__(self, application: QApplication):
        super().__init__(application)
        self._application = application
        self._keyboard = False

    def _set_cue(self, widget: QWidget | None, visible: bool) -> None:
        if widget is None or bool(widget.property("keyboardFocus")) == visible:
            return
        widget.setProperty("keyboardFocus", visible)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    def pointer_input(self) -> None:
        self._keyboard = False
        self._set_cue(self._application.focusWidget(), False)

    def eventFilter(self, watched, event) -> bool:
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress:
            self.pointer_input()
        elif kind == QEvent.Type.KeyPress and event.key() in (
            Qt.Key.Key_Tab, Qt.Key.Key_Backtab, Qt.Key.Key_Left, Qt.Key.Key_Right,
            Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Home, Qt.Key.Key_End,
        ):
            self._keyboard = True
            self._set_cue(self._application.focusWidget(), True)
        elif isinstance(watched, QWidget) and kind == QEvent.Type.FocusIn:
            keyboard = event.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason,
                                           Qt.FocusReason.ShortcutFocusReason)
            self._keyboard = keyboard or self._keyboard
            self._set_cue(watched, self._keyboard and event.reason() != Qt.FocusReason.MouseFocusReason)
        elif isinstance(watched, QWidget) and kind == QEvent.Type.FocusOut:
            self._set_cue(watched, False)
        return False


def install_focus_cues() -> FocusCues:
    application = QApplication.instance()
    cues = getattr(application, "_wisc_focus_cues", None)
    if cues is None:
        cues = FocusCues(application)
        application._wisc_focus_cues = cues
        application.installEventFilter(cues)
    return cues


def ui_font(size: int, *, bold: bool = False, pixel: bool = False) -> QFont:
    return QFont(_font_template(QApplication.font().toString(), size, bold, pixel))


@lru_cache(maxsize=64)
def _font_template(base: str, size: int, bold: bool, pixel: bool) -> QFont:
    font = QFont(PIXEL_FONT_FAMILY) if pixel else QFont()
    if not pixel:
        font.fromString(base)
    font.setPixelSize(size)
    font.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
    return font


def install_fonts() -> None:
    QFontDatabase.addApplicationFont(str(ASSETS_DIR / "fonts" / "PixelifySans.ttf"))
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
    if sys.platform == "win32":
        font.setFamily(WINDOWS_FONT_FAMILY)
    font.setPixelSize(FONT_BODY)
    QApplication.setFont(font)


def dark_palette(colors: dict[str, str]) -> QPalette:
    palette = QPalette()
    for role, value in {
        QPalette.ColorRole.Window: SURFACE,
        QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: BASE,
        QPalette.ColorRole.AlternateBase: ALTERNATE_BASE,
        QPalette.ColorRole.Text: TEXT,
        QPalette.ColorRole.Button: ALTERNATE_BASE,
        QPalette.ColorRole.ButtonText: TEXT,
        QPalette.ColorRole.ToolTipBase: ALTERNATE_BASE,
        QPalette.ColorRole.ToolTipText: TEXT,
        QPalette.ColorRole.Highlight: colors["btn_primary"],
        QPalette.ColorRole.HighlightedText: colors["btn_primary_text"],
        QPalette.ColorRole.Link: colors["btn_primary"],
        QPalette.ColorRole.LinkVisited: colors["btn_primary_hover"],
        QPalette.ColorRole.PlaceholderText: MUTED,
    }.items():
        palette.setColor(role, QColor(value))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(DISABLED_TEXT))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(DISABLED_TEXT))
    return palette


def stylesheet(colors: dict[str, str]) -> str:
    accent = colors["btn_primary"]
    selection = QColor(accent)
    selection_fill = f"rgba({selection.red()}, {selection.green()}, {selection.blue()}, 46)"
    return f"""
        QWidget {{ color: {TEXT}; }}
        QWidget#tabs {{ background: rgba(255, 255, 255, 4); border-radius: 11px; }}
        QLabel {{ background: transparent; }}
        QLabel[muted="true"] {{ color: {MUTED}; }}
        QPushButton, QToolButton {{
            background: {SURFACE}; border: 0; border-radius: {RADIUS_BUTTON}px;
            padding: 8px 14px; font-weight: 600;
        }}
        QPushButton:hover, QToolButton:hover {{ background: #161815; }}
        QPushButton:pressed, QToolButton:pressed {{ background: {SURFACE}; }}
        QPushButton[glass="true"], QPushButton[glass="true"]:hover,
        QPushButton[glass="true"]:pressed {{ background: transparent; }}
        QPushButton[keyboardFocus="true"]:focus, QToolButton[keyboardFocus="true"]:focus {{
            border: 0;
        }}
        QPushButton:disabled {{ color: {DISABLED_TEXT}; background: {SURFACE}; }}
        QPushButton#launch, QPushButton[primary="true"], QPushButton[glass="true"]:checked {{
            background: {accent}; color: {colors['btn_primary_text']};
        }}
        QPushButton#launch, QPushButton[primary="true"] {{
            padding: 8px 22px;
        }}
        QPushButton#launch:hover, QPushButton[primary="true"]:hover,
        QPushButton[glass="true"]:checked:hover {{ background: {colors['btn_primary_hover']}; }}
        QPushButton#launch:pressed, QPushButton[primary="true"]:pressed,
        QPushButton[glass="true"]:checked:pressed {{ background: {colors['btn_primary_active']}; }}
        QPushButton#launch:disabled, QPushButton[primary="true"]:disabled,
        QPushButton[glass="true"]:checked:disabled {{ background: {SURFACE}; color: {DISABLED_TEXT}; }}
        QPushButton#nav {{ background: transparent; color: {MUTED}; padding: 0; }}
        QPushButton#nav:hover {{ background: rgba(255, 255, 255, 10); color: {TEXT}; }}
        QPushButton#nav:checked {{ background: {selection_fill}; color: {accent}; }}
        QPushButton#tab {{ background: transparent; color: {MUTED}; padding: 6px 14px; border-radius: {RADIUS_BUTTON}px; }}
        QPushButton#tab:hover {{ background: rgba(255, 255, 255, 10); color: {TEXT}; }}
        QPushButton#tab:checked {{ background: {selection_fill}; color: #FFFFFF; }}
        QPushButton#tab:checked:hover {{ background: {selection_fill}; color: #FFFFFF; }}
        QPushButton#quiet {{ background: transparent; color: {MUTED}; padding: 6px 10px; }}
        QPushButton#quiet:hover {{ background: rgba(255, 255, 255, 10); color: {TEXT}; }}
        QPushButton#newProfile {{ background: transparent; border-radius: {RADIUS_CARD}px; padding: 12px; }}
        QPushButton#newProfile:hover {{ background: transparent; }}
        QComboBox {{ background: transparent; border: 0; }}
        QLineEdit {{ background: transparent; border: 0; border-radius: {RADIUS_FIELD}px; padding: 8px 14px; }}
        QScrollArea#libraryScroll, QWidget#libraryContent,
        QScrollArea#skinsScroll, QWidget#skinsContent,
        QScrollArea#optionsScroll, QWidget#optionsContent,
        QScrollArea#contentScroll, QWidget#contentScrollBody,
        QListView#contentList, QTextBrowser#contentMarkdown {{ background: transparent; border: 0; }}
        QListView#contentList::item {{ background: transparent; border: 0; }}
        QDialog#contentReview {{ background: {SURFACE}; }}
        QCheckBox {{ background: transparent; spacing: 8px; }}
        QCheckBox::indicator {{ width: 16px; height: 16px; }}
        QScrollBar:vertical {{
            background: rgba(11, 13, 10, 65); width: 8px; margin: 0; border-radius: 4px;
        }}
        QScrollBar::handle:vertical {{
            background: rgba(177, 186, 173, 100); min-height: 28px; border-radius: 4px;
        }}
        QScrollBar::handle:vertical:hover {{ background: rgba(177, 186, 173, 160); }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
        QToolButton#cardActions {{ background: rgba(11, 13, 10, 170); padding: 0; border-radius: {RADIUS_FIELD}px; }}
        QToolButton#cardActions::menu-indicator {{ image: none; }}
        QMenu {{ background: transparent; border: 0; padding: 6px; }}
        QMenu::item {{ padding: 8px 18px; border-radius: {RADIUS_FIELD}px; }}
        QMenu::item:selected {{ background: {selection_fill}; }}
        QProgressBar {{ background: rgba(255, 255, 255, 12); border: 0; border-radius: 3px; }}
        QProgressBar::chunk {{ background: {accent}; border-radius: 3px; }}
        QLabel[progressStatus="true"] {{ color: #FFFFFF; }}
        QToolTip {{ background: #171C14; color: {TEXT}; border: 0; padding: 8px; }}
    """
