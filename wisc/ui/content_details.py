"""One Qt details view for mods, modpacks, shaders, and texture packs."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup, QCheckBox, QFrame, QHBoxLayout, QScrollArea,
    QStackedWidget, QVBoxLayout, QWidget,
)

from wisc.mods.compatibility import version_supports_profile
from wisc.core.credentials import redact_credentials
from wisc.mods.manager import LocalMod, version_loader_compatible
from wisc.ui import theme as theme
from wisc.ui.components import ElidedLabel, GlassButton, GlassPanel, GlassLineEdit, LauncherComboBox, text_label
from wisc.ui.content import (
    ContentAction, ContentImage, ContentImages, ContentItem, ContentList,
    ContentMarkdown, ContentPagination, format_downloads, format_size,
)
from wisc.ui.theme import ui_font


RELEASE_OPTIONS = (("release", "Stable"), ("all", "All releases"), ("beta", "Beta"), ("alpha", "Alpha"))


class ContentDetails(QWidget):
    back_requested = pyqtSignal()
    retry_requested = pyqtSignal()
    install_requested = pyqtSignal(object, object)
    action_requested = pyqtSignal(object, str)
    release_changed = pyqtSignal(str)
    link_requested = pyqtSignal(str)
    version_opened = pyqtSignal(object)

    def __init__(self, images: ContentImages, parent: QWidget | None = None):
        super().__init__(parent)
        self.images = images
        self.item: ContentItem | None = None
        self.kind = "mods"
        self.profile: dict = {}
        self.project: dict = {}
        self.versions: list[dict] = []
        self._offset = 0
        self._can_change = False
        self._loaded = False
        self._update: dict | None = None
        self._local: Any = None
        self._selected_version: dict | None = None
        self._gallery_signature: tuple = ()
        self._gallery_offset = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        back_bar = QHBoxLayout()
        back = GlassButton("‹  Back")
        back.setFixedHeight(theme.SEGMENT_HEIGHT)
        back.setAccessibleName("Back to content list")
        back.clicked.connect(self.back_requested.emit)
        back_bar.addWidget(back)
        back_bar.addStretch()
        self.target = ElidedLabel()
        self.target.setProperty("muted", True)
        self.target.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        back_bar.addWidget(self.target, 1)
        layout.addLayout(back_bar)

        hero = GlassPanel(radius=theme.RADIUS_CARD)
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(16, 14, 16, 14)
        hero_layout.setSpacing(16)
        self.artwork = ContentImage(images)
        self.artwork.setFixedSize(64, 64)
        hero_layout.addWidget(self.artwork)
        info = QVBoxLayout()
        info.setSpacing(4)
        self.title = ElidedLabel()
        self.title.setFont(ui_font(theme.FONT_PAGE_TITLE, bold=True))
        self.subtitle = ElidedLabel()
        self.subtitle.setProperty("muted", True)
        self.summary = ElidedLabel()
        self.summary.setProperty("muted", True)
        for label in (self.title, self.subtitle, self.summary):
            info.addWidget(label)
        hero_layout.addLayout(info, 1)
        self.install = GlassButton("Install", accented=True)
        self.install.setFixedHeight(theme.PRIMARY_BUTTON_HEIGHT)
        self.install.clicked.connect(self._install_latest)
        self.toggle = GlassButton("Disable")
        self.toggle.setFixedHeight(theme.PRIMARY_BUTTON_HEIGHT)
        self.toggle.clicked.connect(lambda: self.action_requested.emit(self.item, "toggle"))
        self.remove = GlassButton("Remove", accented=True)
        self.remove.setFixedHeight(theme.PRIMARY_BUTTON_HEIGHT)
        self.remove.clicked.connect(lambda: self.action_requested.emit(self.item, "remove"))
        for button in (self.install, self.toggle, self.remove):
            hero_layout.addWidget(button)
        layout.addWidget(hero)

        tabs = QHBoxLayout()
        tabs.setSpacing(8)
        self._tab_group = QButtonGroup(self)
        self._tab_buttons: dict[str, GlassButton] = {}
        for key, label in (("overview", "Overview"), ("versions", "Versions"), ("gallery", "Gallery")):
            button = GlassButton(label)
            button.setCheckable(True)
            button.setFixedHeight(theme.SEGMENT_HEIGHT)
            button.clicked.connect(lambda checked=False, name=key: self._set_section(name))
            self._tab_group.addButton(button)
            self._tab_buttons[key] = button
            tabs.addWidget(button)
        tabs.addStretch()
        self.retry = GlassButton("Retry")
        self.retry.setFixedHeight(theme.SEGMENT_HEIGHT)
        self.retry.clicked.connect(self.retry_requested.emit)
        tabs.addWidget(self.retry)
        layout.addLayout(tabs)
        self.feedback = text_label("", theme.FONT_DETAIL, muted=True)
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        self.body = QStackedWidget()
        layout.addWidget(self.body, 1)

        self.overview = QWidget()
        overview = QHBoxLayout(self.overview)
        overview.setContentsMargins(0, 0, 0, 0)
        overview.setSpacing(16)
        self.description = self._document_panel(overview, 1)
        metadata_panel = GlassPanel(radius=theme.RADIUS_CARD)
        metadata_panel.setFixedWidth(236)
        metadata_layout = QVBoxLayout(metadata_panel)
        metadata_layout.setContentsMargins(14, 14, 14, 14)
        metadata_scroll = QScrollArea()
        metadata_scroll.setObjectName("contentScroll")
        metadata_scroll.setFrameShape(QFrame.Shape.NoFrame)
        metadata_scroll.setWidgetResizable(True)
        metadata_scroll.viewport().setAutoFillBackground(False)
        self.metadata_host = QWidget()
        self.metadata_host.setObjectName("contentScrollBody")
        self.metadata_layout = QVBoxLayout(self.metadata_host)
        self.metadata_layout.setContentsMargins(0, 0, 0, 0)
        self.metadata_layout.setSpacing(12)
        metadata_scroll.setWidget(self.metadata_host)
        metadata_layout.addWidget(metadata_scroll)
        overview.addWidget(metadata_panel)
        self.body.addWidget(self.overview)

        self.version_page = QWidget()
        versions = QVBoxLayout(self.version_page)
        versions.setContentsMargins(0, 0, 0, 0)
        versions.setSpacing(8)
        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.version_search = GlassLineEdit()
        self.version_search.setPlaceholderText("Search versions")
        self.version_search.setAccessibleName("Search project versions")
        self.version_search.setClearButtonEnabled(True)
        self.version_search.setFixedHeight(theme.FIELD_HEIGHT)
        self.version_search.textChanged.connect(self._filter_versions)
        filters.addWidget(self.version_search, 1)
        self.release_filter = LauncherComboBox(height=theme.FIELD_HEIGHT, min_width=148, max_width=185)
        for key, label in RELEASE_OPTIONS:
            self.release_filter.addItem(label, key)
        self.release_filter.setAccessibleName("Filter release type")
        self.release_filter.currentIndexChanged.connect(self._release_changed)
        filters.addWidget(self.release_filter)
        self.compatible = QCheckBox("Compatible only")
        self.compatible.setChecked(True)
        self.compatible.toggled.connect(self._filter_versions)
        filters.addWidget(self.compatible)
        versions.addLayout(filters)
        self.version_count = text_label("", theme.FONT_DETAIL, muted=True)
        versions.addWidget(self.version_count)
        self.version_list = ContentList(images)
        self.version_list.setAccessibleName("Project version history")
        self.version_list.item_opened.connect(lambda item: self.open_version(item.payload))
        self.version_list.action_requested.connect(lambda item, action:
                                                   self.install_requested.emit(self.project, item.payload))
        versions.addWidget(self.version_list, 1)
        self.version_pagination = ContentPagination()
        self.version_pagination.requested.connect(self._paginate_versions)
        versions.addWidget(self.version_pagination)
        self.body.addWidget(self.version_page)

        self.gallery = QWidget()
        gallery = QVBoxLayout(self.gallery)
        gallery.setContentsMargins(0, 0, 0, 0)
        gallery.setSpacing(8)
        self.gallery_scroll = QScrollArea()
        self.gallery_scroll.setObjectName("contentScroll")
        self.gallery_scroll.setWidgetResizable(True)
        self.gallery_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.gallery_scroll.viewport().setAutoFillBackground(False)
        self.gallery_body = QWidget()
        self.gallery_body.setObjectName("contentScrollBody")
        self.gallery_layout = QVBoxLayout(self.gallery_body)
        self.gallery_layout.setContentsMargins(0, 0, 8, 0)
        self.gallery_layout.setSpacing(12)
        self.gallery_scroll.setWidget(self.gallery_body)
        gallery.addWidget(self.gallery_scroll, 1)
        self.gallery_pagination = ContentPagination()
        self.gallery_pagination.requested.connect(self._paginate_gallery)
        gallery.addWidget(self.gallery_pagination)
        self.body.addWidget(self.gallery)

        self.changelog = QWidget()
        changelog = QVBoxLayout(self.changelog)
        changelog.setContentsMargins(0, 0, 0, 0)
        changelog.setSpacing(8)
        change_header = QHBoxLayout()
        versions_back = GlassButton("‹  Versions")
        versions_back.clicked.connect(lambda: self.body.setCurrentWidget(self.version_page))
        change_header.addWidget(versions_back)
        self.version_title = ElidedLabel()
        self.version_title.setFont(ui_font(theme.FONT_SUBHEADING, bold=True))
        change_header.addWidget(self.version_title, 1)
        self.version_install = GlassButton("Install", accented=True)
        self.version_install.clicked.connect(lambda: self.install_requested.emit(self.project, self._selected_version))
        change_header.addWidget(self.version_install)
        changelog.addLayout(change_header)
        self.version_requirements = text_label("", theme.FONT_DETAIL, muted=True)
        self.version_requirements.setWordWrap(True)
        changelog.addWidget(self.version_requirements)
        self.changelog_body = self._document_panel(changelog, 1)
        self.body.addWidget(self.changelog)
        self._set_section("overview")

    def _document_panel(self, layout, stretch: int) -> ContentMarkdown:
        panel = GlassPanel(radius=theme.RADIUS_CARD)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(18, 14, 18, 14)
        document = ContentMarkdown(self.images)
        document.link_requested.connect(self.link_requested.emit)
        panel_layout.addWidget(document)
        layout.addWidget(panel, stretch)
        return document

    def apply_theme(self, colors: dict[str, str]) -> None:
        self.version_list.set_accent(colors["btn_primary"], colors["btn_primary_text"])
        for document in (self.description, self.changelog_body):
            document.set_accent(colors["btn_primary"])

    def open(self, item: ContentItem, kind: str, profile: dict | None) -> None:
        self.item, self.kind, self.profile = item, kind, dict(profile or {})
        self.project = {"title": item.title, "description": item.description}
        self.versions = []
        self._local = item.payload if isinstance(item.payload, LocalMod) else None
        self._update = None
        self._loaded = False
        self._selected_version = None
        self._offset = 0
        self._gallery_offset = 0
        self._set_section("overview")
        self.title.setText(item.title)
        self.summary.setText(item.description)
        self.subtitle.setText(item.details)
        self.artwork.source = item.icon
        self.artwork.update()
        self.target.setText(self.profile.get("name", "") + (
            f" · {self.profile.get('minecraft_version', '')} / {self.profile.get('loader', '')}" if self.profile else "New instance"
        ))
        self.description.display(item.description or "Loading project documentation…")
        self.set_feedback("Loading details…")
        self._refresh_actions()

    def display(self, data: dict) -> None:
        self.project.update(data.get("project", {}))
        self.project.setdefault("project_id", self.project.get("id", ""))
        self.versions = data.get("versions", [])
        self._local = data.get("local", self._local)
        self._update = data.get("update")
        self._loaded = True
        info = data.get("local_info", {})
        self.title.setText(self.project.get("title") or self.project.get("name") or self.item.title)
        self.summary.setText(self.project.get("description") or self.item.description)
        members = data.get("members", [])
        authors = ", ".join(filter(None, (member.get("user", {}).get("username", "") for member in members)))
        self.subtitle.setText(" · ".join(filter(None, (
            "by " + (authors or self.project.get("author", "")) if authors or self.project.get("author") else "",
            self.item.details,
        ))))
        self.artwork.source = (getattr(self._local, "icon", None) or info.get("icon")
                               or self.project.get("icon_url") or self.item.icon)
        self.artwork.update()
        body = self.project.get("body") or info.get("description") or self.item.description
        if not body:
            body = "This project has no description."
        if not self.project.get("project_id"):
            body += "\n\nOnline version history is unavailable for this local file."
        self.description.display(body, self._base_url())
        self._display_metadata(info, authors)
        self._display_gallery()
        self.set_feedback(data.get("warning", ""))
        self._refresh_actions()
        self._filter_versions()

    def set_feedback(self, message: str) -> None:
        self.feedback.setText(redact_credentials(message))
        self.feedback.setVisible(bool(message))
        self.retry.setVisible(bool(message) and message != "Loading details…")

    def set_can_change(self, enabled: bool) -> None:
        changed = self._can_change != enabled
        self._can_change = enabled
        self._refresh_actions()
        self.version_list.actions_enabled = enabled
        self.version_list.viewport().update()
        if changed and self._loaded:
            self._display_versions()

    def sync_local(self, local: Any) -> None:
        self._local = local
        self._refresh_actions()
        if self._loaded:
            self._display_versions()

    def set_release(self, release: str) -> None:
        self.release_filter.blockSignals(True)
        self.release_filter.setCurrentIndex(max(0, self.release_filter.findData(release)))
        self.release_filter.blockSignals(False)
        self._filter_versions()

    def _release_changed(self) -> None:
        self._filter_versions()
        self.release_changed.emit(self.release_filter.currentData())

    def _base_url(self) -> str:
        return "https://www.curseforge.com/" if str(self.project.get("project_id", "")).startswith("cf:") else "https://modrinth.com/"

    def _supports_profile(self, version: dict) -> bool:
        if self.kind == "modpacks":
            return True
        if self.kind != "mods":
            return self.profile.get("minecraft_version") in version.get("game_versions", [])
        loader = str(self.profile.get("loader", "")).lower()
        return (version_supports_profile(version, self.profile.get("minecraft_version", ""), loader)
                and version_loader_compatible(version, loader, self.profile.get("loader_version", "")) is not False
                and version.get("_profile_compatible") is not False)

    def _can_install_version(self, version: dict | None) -> bool:
        return bool(self._can_change and self._loaded and version and self._supports_profile(version)
                    and not getattr(self._local, "pack_owned", False)
                    and version.get("id") != getattr(self._local, "version_id", None))

    def _latest_version(self) -> dict | None:
        compatible = [version for version in self.versions if self._supports_profile(version)]
        return next((version for version in compatible if version.get("version_type") == "release"),
                    compatible[0] if compatible else None)

    def _refresh_actions(self) -> None:
        local_mod = self._local if isinstance(self._local, LocalMod) else None
        has_local = self._local is not None
        self.toggle.setVisible(local_mod is not None)
        self.toggle.setText("Disable" if local_mod and local_mod.enabled else "Enable")
        self.toggle.setEnabled(self._can_change and local_mod is not None)
        self.remove.setVisible(has_local and self.kind != "modpacks")
        self.remove.setEnabled(self._can_change and has_local)
        candidate = self._update if local_mod else self._latest_version()
        self.install.setText("Pack managed" if local_mod and local_mod.pack_owned else "Update" if self._update else
                             "Installed" if has_local and self.kind != "modpacks" else "Install")
        self.install.setEnabled(self._can_install_version(candidate) and (not has_local or self._update is not None or self.kind == "modpacks"))
        self.version_install.setEnabled(self._can_install_version(self._selected_version))

    def _install_latest(self) -> None:
        candidate = self._update if isinstance(self._local, LocalMod) else self._latest_version()
        if self._can_install_version(candidate):
            self.install_requested.emit(self.project, candidate)

    def _set_section(self, name: str) -> None:
        pages = {"overview": self.overview, "versions": self.version_page, "gallery": self.gallery}
        self.body.setCurrentWidget(pages[name])
        self._tab_buttons[name].setChecked(True)

    def _display_metadata(self, info: dict, authors: str) -> None:
        while self.metadata_layout.count():
            widget = self.metadata_layout.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        project = self.project
        license_info = project.get("license", {})
        license_name = license_info.get("name") or license_info.get("id", "") if isinstance(license_info, dict) else str(license_info)
        values = [("Author", authors or project.get("author", "")),
                  ("Downloads", format_downloads(int(project.get("downloads", 0)))),
                  ("License", license_name), ("Categories", ", ".join(project.get("categories", []))),
                  ("Client", project.get("client_side", "")), ("Server", project.get("server_side", ""))]
        if self._local is not None:
            values.extend((("File", getattr(self._local, "filename", "")),
                           ("Version", getattr(self._local, "version", "")),
                           ("Size", format_size(getattr(self._local, "size", None)))))
        if isinstance(self._local, LocalMod) and self._local.pack_owned:
            values.append(("Updates", "Managed by the modpack"))
        for name, value in values:
            if value:
                label = text_label(f"{name}\n{value}", theme.FONT_DETAIL, muted=True)
                label.setWordWrap(True)
                label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                self.metadata_layout.addWidget(label)
        for name, key in (("Project page", "project_url"), ("Source", "source_url"), ("Wiki", "wiki_url"),
                          ("Issues", "issues_url"), ("Community", "discord_url")):
            url = project.get(key)
            if name == "Project page" and not url and project.get("project_id"):
                path = "modpack" if self.kind == "modpacks" else "mod" if self.kind == "mods" else self.kind
                if not project["project_id"].startswith("cf:"):
                    url = f"https://modrinth.com/{path}/{project.get('slug') or project['project_id']}"
            if url:
                button = GlassButton(name)
                button.clicked.connect(lambda checked=False, target=str(url): self.link_requested.emit(target))
                self.metadata_layout.addWidget(button)
        self.metadata_layout.addStretch()

    def _filter_versions(self, *args) -> None:
        self._offset = 0
        self._display_versions()

    def _filtered_versions(self) -> list[dict]:
        query = self.version_search.text().strip().casefold()
        release = self.release_filter.currentData()
        return [version for version in self.versions
                if (release == "all" or version.get("version_type", "release") == release)
                and (not self.compatible.isChecked() or self._supports_profile(version))
                and (not query or query in f"{version.get('name', '')} {version.get('version_number', '')} {' '.join(version.get('game_versions', []))}".casefold())]

    def _display_versions(self) -> None:
        versions = self._filtered_versions()
        items = []
        for version in versions[self._offset:self._offset + 20]:
            files = version.get("files", [])
            file = next((file for file in files if file.get("primary")), files[0] if files else {})
            compatible = self._supports_profile(version)
            installed = version.get("id") == getattr(self._local, "version_id", None)
            actions = (ContentAction("install", "Installed" if installed else "Install",
                                     self._can_install_version(version), True),)
            items.append(ContentItem(
                str(version.get("id")), version.get("name") or version.get("version_number", "Version"),
                " · ".join(filter(None, (version.get("version_type", "release").title(), version.get("date_published", "")[:10],
                                         "Compatible" if compatible else "Different game / loader"))),
                " · ".join(filter(None, (file.get("filename", ""), format_size(file.get("size"))))),
                self.artwork.source, actions, payload=version,
            ))
        self.version_list.set_items(items)
        self.version_count.setText(f"{len(versions)} versions" if versions else "No versions match these filters.")
        self.version_pagination.display(self._offset, len(versions))

    def _paginate_versions(self, direction: int) -> None:
        self._offset = max(0, self._offset + direction * 20)
        self._display_versions()

    def open_version(self, version: dict) -> None:
        self._selected_version = version
        self.version_title.setText(version.get("name") or version.get("version_number", "Version"))
        self.version_requirements.setText(" · ".join(filter(None, (
            "Minecraft " + ", ".join(version.get("game_versions", [])),
            ", ".join(version.get("loaders", [])),
            "Compatible with this instance" if self._supports_profile(version) else "Requires a different game version or loader",
        ))))
        body = version.get("changelog") or "No changelog supplied for this version."
        self.changelog_body.display(body, self._base_url())
        self._refresh_actions()
        self.body.setCurrentWidget(self.changelog)
        self.version_opened.emit(version)

    def _display_gallery(self) -> None:
        entries = self.project.get("gallery", [])
        signature = (self._gallery_offset, tuple((entry.get("url"), entry.get("title"), entry.get("description")) for entry in entries))
        self._tab_buttons["gallery"].setVisible(bool(entries))
        if signature == self._gallery_signature:
            return
        self._gallery_signature = signature
        while self.gallery_layout.count():
            widget = self.gallery_layout.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        for entry in entries[self._gallery_offset:self._gallery_offset + 6]:
            panel = GlassPanel(radius=theme.RADIUS_CARD)
            content = QVBoxLayout(panel)
            content.setContentsMargins(14, 14, 14, 14)
            image = ContentImage(self.images, entry.get("url"), limit=768)
            image.setFixedHeight(260)
            content.addWidget(image)
            if entry.get("title"):
                content.addWidget(text_label(entry["title"], theme.FONT_LABEL, bold=True))
            if entry.get("description"):
                description = text_label(entry["description"], theme.FONT_DETAIL, muted=True)
                description.setWordWrap(True)
                content.addWidget(description)
            original = GlassButton("Open original")
            original.clicked.connect(lambda checked=False, url=entry.get("url", ""): self.link_requested.emit(url))
            content.addWidget(original)
            self.gallery_layout.addWidget(panel)
        self.gallery_layout.addStretch()
        self.gallery_scroll.verticalScrollBar().setValue(0)
        self.gallery_pagination.display(self._gallery_offset, len(entries), page_size=6)

    def _paginate_gallery(self, direction: int) -> None:
        total = len(self.project.get("gallery", []))
        self._gallery_offset = min(max(0, self._gallery_offset + direction * 6), max(0, (total - 1) // 6 * 6))
        self._display_gallery()
