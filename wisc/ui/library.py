"""Scrollable profile library composed from the shared Qt artwork cards."""

from typing import Sequence

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from wisc.ui import theme as theme
from wisc.ui.components import (
    GlassLineEdit, LauncherComboBox, text_label,
)
from wisc.ui.images import ContentImages
from wisc.ui.content import ContentItem, ProfileGrid
from wisc.ui.home import HomeProfile
from wisc.ui.tasks import ServiceRunner


class LibraryPage(QWidget):
    profile_selected = pyqtSignal(str)
    action_requested = pyqtSignal(str, str)
    create_requested = pyqtSignal()

    def __init__(self, profiles: Sequence[HomeProfile], colors: dict[str, str],
                 parent: QWidget | None = None, *, runner: ServiceRunner):
        super().__init__(parent)
        self._images = ContentImages(runner, self)
        self._profiles = list(profiles)
        self._layout_signature = None
        self._selected_id: str | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*theme.PAGE_MARGINS)
        layout.setSpacing(theme.PAGE_SPACING)
        header_bar = QWidget()
        header_bar.setFixedHeight(theme.HEADER_HEIGHT)
        heading = QHBoxLayout(header_bar)
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(12)
        heading.addWidget(text_label("Library", theme.FONT_PAGE_TITLE, bold=True))
        self.count = text_label("", theme.FONT_DETAIL, muted=True)
        heading.addWidget(self.count)
        heading.addStretch(1)
        create = QPushButton("New profile")
        create.setProperty("primary", True)
        create.setFixedHeight(theme.BUTTON_HEIGHT)
        create.clicked.connect(self.create_requested.emit)
        heading.addWidget(create)
        layout.addWidget(header_bar)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.search = GlassLineEdit(search_icon=True)
        self.search.setPlaceholderText("Search profiles")
        self.search.setAccessibleName("Search profiles")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedHeight(theme.FIELD_HEIGHT)
        self.search.textChanged.connect(self._filter_changed)
        filters.addWidget(self.search, 1)
        self.loader_filter = LauncherComboBox(height=theme.FIELD_HEIGHT, min_width=136, max_width=220)
        self.loader_filter.addItem("All loaders")
        self.loader_filter.addItems(sorted({profile.loader for profile in profiles}))
        self.loader_filter.setAccessibleName("Filter by loader")
        self.loader_filter.currentTextChanged.connect(self._filter_changed)
        filters.addWidget(self.loader_filter)
        self.sort = LauncherComboBox(height=theme.FIELD_HEIGHT, min_width=160, max_width=220, prefix="Sort:")
        self.sort.addItems(("Saved order", "Name A\u2013Z", "Name Z\u2013A"))
        self.sort.setAccessibleName("Sort profiles")
        self.sort.currentTextChanged.connect(self._filter_changed)
        filters.addWidget(self.sort)
        layout.addLayout(filters)

        self.results = QStackedWidget()
        self.scroll = ProfileGrid(self._images)
        self.scroll.setAccessibleName("Profile library")
        self.scroll.set_accent(colors["btn_primary"], colors["btn_primary_text"])
        self.scroll.item_opened.connect(lambda item: self.profile_selected.emit(item.key))
        self.scroll.action_requested.connect(self._action_requested)
        self.results.addWidget(self.scroll)
        self.empty_host = QWidget()
        empty_layout = QVBoxLayout(self.empty_host)
        empty_layout.setContentsMargins(0, 0, 0, 0)
        empty_layout.addStretch(1)
        self.empty = text_label("No profiles", theme.FONT_LABEL, muted=True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty, 0, Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addStretch(1)
        self.results.addWidget(self.empty_host)
        layout.addWidget(self.results, 1)
        self._reflow()

    def _action_requested(self, item: ContentItem, action: str) -> None:
        if action != "menu":
            self.action_requested.emit(item.key, action)

    def showEvent(self, event) -> None:
        self._images.set_visible(True)
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self._images.set_visible(False)
        super().hideEvent(event)

    def set_selected(self, profile_id: str) -> None:
        self._selected_id = profile_id
        self.scroll.selected_id = profile_id
        self.scroll.viewport().update()

    def apply_theme(self, colors: dict[str, str]) -> None:
        self.scroll.set_accent(colors["btn_primary"], colors["btn_primary_text"])

    def _filter_changed(self, value: str) -> None:
        self.scroll.verticalScrollBar().setValue(0)
        self._layout_signature = None
        self._reflow()

    def _visible_profiles(self) -> list[HomeProfile]:
        query = self.search.text().strip().casefold()
        loader = self.loader_filter.currentText()
        profiles = [profile for profile in self._profiles
                    if (loader == "All loaders" or profile.loader == loader)
                    and (not query or query in f"{profile.name} {profile.version} {profile.loader}".casefold())]
        if self.sort.currentIndex():
            profiles.sort(key=lambda profile: profile.name.casefold(), reverse=self.sort.currentIndex() == 2)
        return profiles

    def _reflow(self) -> None:
        profiles = self._visible_profiles()
        signature = tuple(profile.id for profile in profiles)
        if signature == self._layout_signature:
            return
        self._layout_signature = signature
        self.count.setText(f"{len(profiles)} profile{'s' if len(profiles) != 1 else ''}")
        self.scroll.set_items([ContentItem(profile.id, profile.name,
                                          details=f"{profile.version} \u00b7 {profile.loader}", payload=profile)
                               for profile in profiles])
        self.results.setCurrentWidget(self.scroll if profiles else self.empty_host)
