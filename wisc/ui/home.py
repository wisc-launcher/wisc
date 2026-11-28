"""Qt Home composition; service actions are delivered through explicit signals."""

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout, QPushButton, QStyle,
    QVBoxLayout, QWidget,
)

from wisc.core.paths import ASSETS_DIR
from wisc.ui import theme as theme
from wisc.ui.components import (
    ElidedLabel, GlassButton, LauncherComboBox, ProfileCard,
    artwork_image, build_profile_actions_menu, text_label,
)
from wisc.ui.images import ContentImages
from wisc.ui.theme import ui_font


@dataclass(frozen=True)
class HomeProfile:
    id: str
    name: str
    version: str
    loader: str
    artwork: Path
    icon: Path
    installed: bool = True


class HomePage(QWidget):
    profile_selected = pyqtSignal(object)
    launch_requested = pyqtSignal(str)
    cancel_requested = pyqtSignal()
    operation_changed = pyqtSignal(object, object)
    edit_requested = pyqtSignal(str)
    folder_requested = pyqtSignal(str)
    action_requested = pyqtSignal(str, str)
    create_requested = pyqtSignal()
    library_requested = pyqtSignal()
    logs_requested = pyqtSignal()
    account_requested = pyqtSignal()

    def __init__(self, profiles: Sequence[HomeProfile], colors: dict[str, str], *,
                 username: str = "Player", selected_id: str | None = None,
                 parent: QWidget | None = None, images: ContentImages | None = None):
        super().__init__(parent)
        if len({profile.id for profile in profiles}) != len(profiles):
            raise ValueError("Home profile IDs must be unique.")
        self._profiles = list(profiles)
        self._profiles_by_id = {profile.id: profile for profile in profiles}
        self._images = images
        self._accent = colors["btn_primary"]
        self._selected: HomeProfile | None = None
        self._busy = False
        self._cards: dict[str, ProfileCard] = {}
        self._notice = QTimer(self)
        self._notice.setSingleShot(True)
        self._notice.timeout.connect(self._restore_status)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 16)
        layout.setSpacing(0)
        account_row = QHBoxLayout()
        account_row.addStretch(1)
        self.account_button = GlassButton("")
        self.account_button.setIconSize(QSize(24, 24))
        self.account_button.setFixedHeight(theme.SEGMENT_HEIGHT)
        self.account_button.setToolTip("Accounts")
        self.account_button.setAccessibleName("Accounts")
        self.account_button.clicked.connect(self.account_requested.emit)
        self.set_account(username)
        account_row.addWidget(self.account_button)
        layout.addLayout(account_row)

        hero = QVBoxLayout()
        hero.setContentsMargins(0, 25, 0, 25)
        hero.setSpacing(0)
        hero.addStretch(1)
        hero.addWidget(text_label("MINECRAFT JAVA EDITION", theme.FONT_LABEL, pixel=True, muted=True))
        hero.addSpacing(8)
        self.title = ElidedLabel()
        self.title.setFont(ui_font(theme.FONT_HERO, bold=True))
        self.title.setFixedHeight(64)
        hero.addWidget(self.title)
        hero.addSpacing(8)
        self.details = text_label("", theme.FONT_LABEL, muted=True)
        hero.addWidget(self.details)
        hero.addSpacing(20)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.play_button = QPushButton()
        self.play_button.setObjectName("launch")
        self.play_button.setFixedWidth(184)
        self.play_button.setFixedHeight(theme.PRIMARY_BUTTON_HEIGHT)
        self.play_button.clicked.connect(self._play)
        actions.addWidget(self.play_button)
        self.edit_button = GlassButton("Edit")
        self.edit_button.setFixedHeight(theme.PRIMARY_BUTTON_HEIGHT)
        self.edit_button.clicked.connect(lambda: self._request(self.edit_requested))
        actions.addWidget(self.edit_button)
        self.folder_button = GlassButton("Folder")
        self.folder_button.setFixedHeight(theme.PRIMARY_BUTTON_HEIGHT)
        self.folder_button.clicked.connect(lambda: self._request(self.folder_requested))
        actions.addWidget(self.folder_button)
        actions.addStretch(1)
        hero.addLayout(actions)
        hero.addStretch(2)
        layout.addLayout(hero, 1)

        shelf_heading = QHBoxLayout()
        shelf_heading.setSpacing(10)
        shelf_heading.addWidget(text_label("Library", theme.FONT_SHELF_HEADING, bold=True))
        count = len(profiles)
        self._shelf_count = text_label(f"{count} profile{'s' if count != 1 else ''}", theme.FONT_DETAIL, muted=True)
        shelf_heading.addWidget(self._shelf_count)
        shelf_heading.addStretch(1)
        view_all = QPushButton("View all  \u2192")
        view_all.setObjectName("quiet")
        view_all.setFixedHeight(theme.COMPACT_HEIGHT)
        view_all.clicked.connect(self.library_requested.emit)
        shelf_heading.addWidget(view_all)
        layout.addLayout(shelf_heading)
        layout.addSpacing(12)
        self._shelf = QHBoxLayout()
        self._shelf.setSpacing(12)
        self.new_profile = GlassButton(radius=theme.RADIUS_CARD)
        self.new_profile.setObjectName("newProfile")
        self.new_profile.setFixedSize(112, 150)
        self.new_profile.setAccessibleName("Create a new profile")
        self.new_profile.setCursor(Qt.CursorShape.PointingHandCursor)
        tile = QVBoxLayout(self.new_profile)
        tile.setSpacing(8)
        tile.addStretch(1)
        for label in (text_label("+", theme.FONT_ADD_PROFILE), text_label("New profile", theme.FONT_DETAIL, muted=True)):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            tile.addWidget(label)
        tile.addStretch(1)
        self.new_profile.clicked.connect(self.create_requested.emit)
        self._shelf.addWidget(self.new_profile)
        layout.addLayout(self._shelf)
        layout.addSpacing(18)

        footer = QHBoxLayout()
        footer.setSpacing(12)
        self.status = ElidedLabel()
        self.status.setFont(ui_font(theme.FONT_DETAIL))
        self.status.setProperty("muted", True)
        footer.addWidget(self.status, 1)
        logs = GlassButton("Logs")
        logs.setFixedHeight(theme.COMPACT_HEIGHT)
        logs.clicked.connect(self.logs_requested.emit)
        footer.addWidget(logs)
        layout.addLayout(footer)

        if profiles:
            self.select_profile(selected_id if selected_id in self._profiles_by_id else profiles[0].id)
        else:
            self.title.setText("No profiles")
            self.details.setText("")
            self._refresh_actions()
            self._restore_status()

    @property
    def selected_profile(self) -> HomeProfile | None:
        return self._selected

    def set_account(self, username: str, skin_path: Path | str | None = None) -> None:
        name = (username or "Player").strip() or "Player"
        self.account_button.setText("  " + name.replace("&", "&&"))
        skin = artwork_image(str(skin_path)) if skin_path else QPixmap()
        if skin.isNull():
            skin = artwork_image(str(ASSETS_DIR / "skins" / "default_steve.png"))
        face = skin.copy(8, 8, 8, 8)
        self.account_button.setIcon(QIcon(face.scaled(
            24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation,
        )))

    def set_profiles(self, profiles: Sequence[HomeProfile], selected_id: str | None = None) -> None:
        if len({profile.id for profile in profiles}) != len(profiles):
            raise ValueError("Home profile IDs must be unique.")
        self._profiles = list(profiles)
        self._profiles_by_id = {profile.id: profile for profile in profiles}
        for card in self._cards.values():
            self._shelf.removeWidget(card)
            card.hide()
            card.deleteLater()
        self._cards.clear()
        count = len(self._profiles)
        self._shelf_count.setText(f"{count} profile{'s' if count != 1 else ''}")
        if self._profiles:
            target_id = selected_id if selected_id in self._profiles_by_id else (
                self._selected.id if self._selected and self._selected.id in self._profiles_by_id
                else self._profiles[0].id
            )
            self._selected = None
            self.select_profile(target_id)
        else:
            self._selected = None
            self.title.setText("No profiles")
            self.details.setText("")
            self._refresh_actions()
            self._refresh_shelf()
            self._restore_status()

    def select_profile(self, profile_id: str) -> None:
        if self._busy:
            return
        profile = self._profiles_by_id.get(profile_id)
        if profile is None:
            return
        self._selected = profile
        self.title.setText(profile.name)
        self.details.setText(f"{profile.version}  \u00b7  {profile.loader}")
        self._notice.stop()
        self._refresh_actions()
        self._refresh_shelf()
        self._restore_status()
        self.profile_selected.emit(profile)

    def apply_theme(self, colors: dict[str, str]) -> None:
        self._accent = colors["btn_primary"]
        for card in self._cards.values():
            card.set_accent(colors["btn_primary"])

    def show_notice(self, message: str, duration: int = 5000) -> None:
        self.status.setText(message)
        self._notice.start(duration)

    def set_operation(self, label: str | None, progress: int | None = None) -> None:
        """Update launch controls and publish progress to the window's shared host."""
        self._busy = bool(label)
        self._notice.stop()
        for card in self._cards.values():
            card.setEnabled(not self._busy)
        self.new_profile.setEnabled(not self._busy)
        self._refresh_actions()
        self._restore_status()
        self.operation_changed.emit(label, progress)

    def _restore_status(self) -> None:
        self.status.setText("")

    def _refresh_actions(self) -> None:
        selected = self._selected is not None
        self.play_button.setEnabled(selected or self._busy)
        self.edit_button.setEnabled(selected and not self._busy)
        self.folder_button.setEnabled(selected and not self._busy)
        text = "Cancel" if self._busy else "Play" if selected and self._selected.installed else "Install && Play"
        self.play_button.setText(text)
        icon = QStyle.StandardPixmap.SP_MediaStop if self._busy else QStyle.StandardPixmap.SP_MediaPlay
        self.play_button.setIcon(self.style().standardIcon(icon))

    def _request(self, signal) -> None:
        if self._selected and not self._busy:
            signal.emit(self._selected.id)

    def _play(self) -> None:
        if self._busy:
            self.cancel_requested.emit()
        else:
            self._request(self.launch_requested)

    def _refresh_shelf(self) -> None:
        slots = 4 if self.width() >= 1366 else 3
        visible = [profile.id for profile in self._profiles[:slots]]
        if self._selected and self._selected.id not in visible and visible:
            visible[-1] = self._selected.id
        for key in tuple(self._cards):
            if key not in visible:
                card = self._cards.pop(key)
                self._shelf.removeWidget(card)
                card.hide()
                card.deleteLater()
        for index, key in enumerate(visible):
            card = self._cards.get(key)
            if card is None:
                profile = self._profiles_by_id[key]
                card = ProfileCard(profile.name, f"{profile.version} \u00b7 {profile.loader}",
                                   profile.artwork, profile.icon, self._accent, images=self._images)
                card.clicked.connect(lambda checked=False, identity=key: self.select_profile(identity))
                menu = build_profile_actions_menu(
                    card,
                    installed=profile.installed,
                    include_open_home=False,
                    on_action=lambda action, identity=key: self.action_requested.emit(identity, action),
                )
                card.set_actions_menu(menu)
                self._cards[key] = card
            if self._shelf.indexOf(card) != index:
                self._shelf.insertWidget(index, card, 1)
            card.setChecked(self._selected is not None and key == self._selected.id)
            card.setEnabled(not self._busy)
            card.show()

    def showEvent(self, event) -> None:
        if self._images is not None:
            self._images.set_visible(True)
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        if self._images is not None:
            self._images.set_visible(False)
        super().hideEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_shelf()
