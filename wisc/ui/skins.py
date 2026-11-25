"""Qt Skins workspace backed by the launcher's existing Ely.by services."""

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel,
    QScrollArea, QVBoxLayout, QWidget,
)

from wisc.ui import theme as theme
from wisc.ui.components import ElidedLabel, GlassButton, GlassPanel, text_label
from wisc.ui.skin_viewer import SkinPreview
from wisc.ui.tasks import LatestServiceTask, ServiceRunner
from wisc.ui.theme import MUTED, ui_font


@dataclass
class _SkinState:
    account: dict[str, Any]
    choice: dict[str, str]
    renderer: Any
    status: str
    warning: str = ""
    avatar: bytes = b""

    @property
    def offline(self) -> bool:
        return self.account.get("type") == "offline"


def _require_account(expected: dict[str, Any]) -> dict[str, Any]:
    from wisc.core.storage import get_active_account

    account = get_active_account()
    if any(account.get(key) != expected.get(key) for key in ("id", "type", "username")):
        raise ValueError("Your account changed. Refresh to reload it.")
    return account


def _load_skin_state(expected: dict[str, Any] | None = None) -> _SkinState:
    # Import only when opening Skins: Home/Library do not initialize game storage.
    from PIL import Image
    from wisc.core.storage import get_active_account
    from wisc.services import skins

    account = _require_account(expected) if expected is not None else get_active_account()
    offline = account.get("type") == "offline"
    choice = (skins.load_offline_cosmetics(str(account["id"])) if offline
              else skins.load_active_skin_choice())
    model = choice.get("model", "classic")
    source = choice.get("custom_path", "") if offline else ""
    if not offline:
        cache = skins.get_skins_dir() / f"ely_{account.get('username', '').lower()}.png"
        source = str(cache)
        try:
            metadata = json.loads(cache.with_suffix(".json").read_text(encoding="utf-8"))
            model = "slim" if metadata.get("model") == "slim" else "classic"
        except (OSError, ValueError, AttributeError):
            pass

    skin = skins.get_default_skin(model)
    status = "Default Alex" if model == "slim" else "Default Steve"
    warning = ""
    if source and Path(source).is_file():
        try:
            with Image.open(source) as image:
                if image.size not in ((64, 64), (64, 32)):
                    raise ValueError("Unsupported Minecraft skin dimensions.")
                skin = skins.ensure_64x64(image)
            status = "Local skin" if offline else "Ely.by skin"
        except (OSError, ValueError):
            warning = ("The saved skin could not be opened." if offline else
                       "The cached skin could not be opened. Refresh to try again.")
    elif offline and choice.get("skin_type") == "custom":
        warning = "The saved skin is missing."

    cape = None
    if offline and choice.get("cape_path"):
        try:
            with Image.open(choice["cape_path"]) as image:
                cape = image.convert("RGBA")
        except (OSError, ValueError):
            warning = "The saved cape could not be opened."

    return _SkinState(
        account, choice, skins.SkinRenderer(skin, model, "hero", cape=cape), status,
        warning, skins.render_head_avatar_bytes(skin, scale=6),
    )


def _sync_ely_skin(state: _SkinState, force: bool) -> _SkinState:
    from wisc.services import skins

    _require_account(state.account)
    data, model = skins.fetch_ely_skin(str(state.account.get("username", "")),
                                      force_refresh=force, timeout=6.0)
    _require_account(state.account)
    if skins.load_active_skin_choice() != state.choice:
        raise ValueError("Your skin changed. Refresh to reload it.")
    if data is None:
        raise OSError("Could not load your Ely.by skin. Try refreshing again.")
    if not skins.save_active_skin_choice("ely", model=model):
        raise OSError("Could not save your Ely.by skin. Try refreshing again.")
    return _load_skin_state(state.account)


class StatusDot(QWidget):
    """Small circular status indicator for the player appearance state."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(9, 9)
        self._color = QColor(MUTED)

    def set_color(self, color: str | QColor) -> None:
        new_color = QColor(color)
        if self._color != new_color:
            self._color = new_color
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(self._color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(1, 1, 7, 7)


def _glass_divider() -> QFrame:
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet(theme.DIVIDER_STYLESHEET)
    return line


class SkinsPage(QWidget):
    cosmetics_changed = pyqtSignal(str)
    progress_changed = pyqtSignal(str, bool)

    def __init__(self, runner: ServiceRunner, colors: dict[str, str], parent: QWidget | None = None):
        super().__init__(parent)
        self._runner = runner
        self._task = LatestServiceTask(runner)
        self._colors = colors
        self._state: _SkinState | None = None
        self._busy = False
        self._synced_account: tuple | None = None
        self._notice = QTimer(self)
        self._notice.setSingleShot(True)
        self._notice.timeout.connect(lambda: self._set_message(""))

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(*theme.PAGE_MARGINS)
        page_layout.setSpacing(theme.PAGE_SPACING)
        header_bar = QWidget()
        header_bar.setFixedHeight(theme.HEADER_HEIGHT)
        header_layout = QHBoxLayout(header_bar)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addWidget(text_label("Skins", theme.FONT_PAGE_TITLE, bold=True))
        header_layout.addStretch(1)
        page_layout.addWidget(header_bar)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("skinsScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.viewport().setAutoFillBackground(False)

        scroll_content = QWidget()
        scroll_content.setObjectName("skinsContent")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(0)

        workspace = QWidget()
        workspace.setMinimumWidth(880)
        workspace.setMaximumWidth(920)
        workspace_layout = QHBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(20)

        preview_panel = GlassPanel()
        preview_panel.setMinimumWidth(360)
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(24, 20, 24, 20)
        preview_layout.setSpacing(12)
        preview_header = QHBoxLayout()
        preview_header.addWidget(text_label("Preview", theme.FONT_LABEL, bold=True))
        preview_header.addStretch(1)
        preview_header.addWidget(text_label("Drag to rotate", theme.FONT_DETAIL, muted=True))
        preview_layout.addLayout(preview_header)

        self.preview = SkinPreview(runner)
        self.preview.setMinimumHeight(350)
        self.preview.render_failed.connect(self._error_message)
        self.preview.rotated.connect(lambda: self._select_view("3d"))
        preview_layout.addWidget(self.preview, 1)

        views = QHBoxLayout()
        views.setSpacing(8)
        self._views = QButtonGroup(self)
        self._view_buttons: dict[str, GlassButton] = {}
        for name, label, yaw, pitch in (("3d", "3D", -25, 10), ("front", "Front", 0, 0),
                                       ("back", "Back", 180, 0)):
            button = GlassButton(label)
            button.setCheckable(True)
            button.setFixedHeight(theme.SEGMENT_HEIGHT)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAccessibleName(f"{label} skin view")
            button.clicked.connect(lambda checked=False, n=name, y=yaw, p=pitch: self._set_view(n, y, p))
            self._views.addButton(button)
            self._view_buttons[name] = button
            views.addWidget(button, 1)
        preview_layout.addLayout(views)
        self._select_view("3d")
        workspace_layout.addWidget(preview_panel, 1)

        details_panel = GlassPanel()
        details_panel.setMinimumWidth(360)
        details_layout = QVBoxLayout(details_panel)
        details_layout.setContentsMargins(24, 20, 24, 20)
        details_layout.setSpacing(12)

        account_header = QHBoxLayout()
        account_header.addWidget(text_label("Account", theme.FONT_DETAIL, muted=True))
        account_header.addStretch(1)
        self.account_badge = text_label("", theme.FONT_SMALL, bold=True)
        self.account_badge.setStyleSheet(theme.ACCOUNT_BADGE_STYLESHEET)
        account_header.addWidget(self.account_badge)
        details_layout.addLayout(account_header)

        identity = QHBoxLayout()
        identity.setSpacing(14)
        self.avatar = QLabel()
        self.avatar.setFixedSize(56, 56)
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar.setStyleSheet(theme.AVATAR_STYLESHEET)
        identity.addWidget(self.avatar)
        player_details = QVBoxLayout()
        player_details.setSpacing(4)
        self.player = ElidedLabel("Loading\u2026")
        self.player.setFont(ui_font(theme.FONT_PLAYER, bold=True))
        player_details.addWidget(self.player)
        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        self.status_dot = StatusDot()
        status_row.addWidget(self.status_dot)
        self.status = text_label("Loading skin\u2026", theme.FONT_DETAIL, muted=True)
        status_row.addWidget(self.status)
        status_row.addStretch(1)
        player_details.addLayout(status_row)
        identity.addLayout(player_details, 1)
        details_layout.addLayout(identity)

        details_layout.addSpacing(4)
        details_layout.addWidget(_glass_divider())
        details_layout.addSpacing(4)
        details_layout.addWidget(text_label("Your skin", theme.FONT_SECTION_HEADING, bold=True))
        self.skin_hint = text_label("Change your skin on Ely.by, then refresh here.", theme.FONT_BODY, muted=True)
        self.skin_hint.setWordWrap(True)
        details_layout.addWidget(self.skin_hint)
        details_layout.addSpacing(12)

        self.manage = GlassButton("Manage on Ely.by", accented=True)
        self.manage.setFixedHeight(theme.PRIMARY_BUTTON_HEIGHT)
        self.manage.setCursor(Qt.CursorShape.PointingHandCursor)
        self.manage.clicked.connect(self._open_manager)
        details_layout.addWidget(self.manage)
        self.refresh = GlassButton("Refresh skin")
        self.refresh.setFixedHeight(theme.PRIMARY_BUTTON_HEIGHT)
        self.refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh.clicked.connect(self._refresh)
        details_layout.addWidget(self.refresh)

        self.message = text_label("", theme.FONT_DETAIL, muted=True)
        self.message.setWordWrap(True)
        self.message.setMinimumHeight(34)
        policy = self.message.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.message.setSizePolicy(policy)
        self.message.hide()
        details_layout.addWidget(self.message)
        details_layout.addStretch(1)
        workspace_layout.addWidget(details_panel, 1)

        scroll_layout.addStretch(1)
        scroll_layout.addWidget(workspace, 0, Qt.AlignmentFlag.AlignHCenter)
        scroll_layout.addStretch(1)
        self.scroll.setWidget(scroll_content)
        page_layout.addWidget(self.scroll, 1)

        self.apply_theme(colors)
        self._set_busy(False)

    def apply_theme(self, colors: dict[str, str]) -> None:
        self._colors = colors
        for button in (*self._view_buttons.values(), self.manage, self.refresh):
            button.update()
        if self._state is not None:
            self._update_status_indicator(self._state)

    def _select_view(self, name: str) -> None:
        if name in self._view_buttons:
            self._view_buttons[name].setChecked(True)

    def _set_view(self, name: str, yaw: float, pitch: float) -> None:
        self._select_view(name)
        self.preview.set_view(yaw, pitch)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for button in self._view_buttons.values():
            button.setEnabled(self._state is not None)
        self.refresh.setEnabled(not busy)
        self.manage.setEnabled(not busy and self._state is not None and not self._state.offline)
        if not busy:
            self.progress_changed.emit("", False)

    def _set_message(self, message: str, *, error: bool = False, transient: bool = False) -> None:
        self._notice.stop()
        self.message.setProperty("muted", not error)
        self.message.style().unpolish(self.message)
        self.message.style().polish(self.message)
        self.message.setText(message)
        self.message.setVisible(bool(message))
        if message and transient:
            self._notice.start(3500)

    def _error_message(self, message: str) -> None:
        self._set_message(message, error=True)

    def _run(self, operation: Callable, message: str, *, changed: bool = False,
             sync_after: bool = False, force: bool = False) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self._set_message(message)
        self.progress_changed.emit(message, True)

        def ready(state: _SkinState) -> None:
            self._display(state)
            self._set_busy(False)
            self._set_message(state.warning or ("Skin refreshed." if changed and force else ""),
                              error=bool(state.warning), transient=not state.warning)
            if changed:
                self._synced_account = tuple(state.account.get(k) for k in ("id", "type", "username"))
                self.cosmetics_changed.emit(str(state.account["id"]))
            if sync_after and not state.offline:
                key = tuple(state.account.get(k) for k in ("id", "type", "username"))
                if force or self._synced_account != key or state.choice.get("skin_type") != "ely":
                    self._sync(force)

        def failed(error: Exception) -> None:
            self._set_busy(False)
            if self._state is not None:
                self._display(self._state)
            self._error_message(str(error))

        self._task.submit(operation, ready, failed)

    def _update_status_indicator(self, state: _SkinState) -> None:
        self.account_badge.setText("Offline" if state.offline else "Ely.by")
        self.status.setText(state.status)
        active = state.status in ("Ely.by skin", "Local skin") and not state.warning
        self.status_dot.set_color(self._colors["btn_primary"] if active else MUTED)

    def _display(self, state: _SkinState) -> None:
        self._state = state
        self.player.setText(str(state.account.get("username", "Player")))
        self._update_status_indicator(state)
        avatar = QPixmap()
        if avatar.loadFromData(state.avatar):
            self.avatar.setPixmap(avatar.scaled(
                48, 48, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation,
            ))
        else:
            self.avatar.clear()
        self.skin_hint.setText(
            "Sign in with an Ely.by account to change your skin." if state.offline else
            "Change your skin on Ely.by, then refresh here."
        )
        self.manage.setToolTip("Sign in with an Ely.by account first." if state.offline else
                               "Open the Ely.by skin manager")
        self.preview.set_renderer(state.renderer)

    def _sync(self, force: bool) -> None:
        state = self._state
        if state is not None and not state.offline:
            self.status.setText("Refreshing\u2026")
            self._run(lambda: _sync_ely_skin(state, force), "Refreshing skin\u2026",
                      changed=True, force=force)

    def _refresh(self) -> None:
        self._synced_account = None
        # Reload the active account before deciding whether a network refresh applies.
        self._run(_load_skin_state, "Loading skin\u2026", sync_after=True, force=True)

    def _open_manager(self) -> None:
        if self._state is None or self._state.offline or self._busy:
            return
        if not QDesktopServices.openUrl(QUrl("https://ely.by/skins")):
            self._error_message("Could not open Ely.by. Visit ely.by/skins in your browser.")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._run(_load_skin_state, "Loading skin\u2026", sync_after=True)

    def hideEvent(self, event) -> None:
        self.preview.suspend()
        super().hideEvent(event)

    def shutdown(self) -> None:
        self._task.close()
        self._set_busy(False)
        self.preview.shutdown()
        self._state = None
