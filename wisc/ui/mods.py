"""Profile-scoped Qt content workspace backed by the existing mod services."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import QRectF, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QButtonGroup, QFileDialog, QHBoxLayout,
    QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from wisc.core.credentials import redact_credentials
from wisc.mods.content import ContentPackManager, LocalContentPack
from wisc.ui import theme as theme
from wisc.mods.manager import (
    InstallPlan, LocalMod, ModManager, ModUpdate, SUPPORTED_LOADERS, UpdateCheck,
    jar_base_name, newer_compatible_version, primary_content_file, primary_file,
    version_matches_environment,
)
from wisc.mods.modpacks import PackInstaller, PackPlan
from wisc.mods.platform import ModPlatformClient
from wisc.ui.components import ElidedLabel, GlassButton, GlassLineEdit, GlassPanel, LauncherComboBox, StaggeredReveal, text_label
from wisc.ui.content import (
    ContentAction, ContentImages, ContentItem, ContentList, ContentPagination,
    SkeletonList, format_downloads, format_size,
)
from wisc.ui.content_details import ContentDetails, RELEASE_OPTIONS
from wisc.ui.content_install import (
    ContentInstallReview, ModInstallReview, PackInstallReview, ReviewDialog, manual_ready_ids,
)
from wisc.ui.tasks import LatestServiceTask, OperationCancelled, ServiceProgress, ServiceRunner


CONTENT_OPTIONS = (("mods", "Mods"), ("modpacks", "Modpacks"), ("shader", "Shaders"), ("resourcepack", "Texture Packs"))
SORT_OPTIONS = (("downloads", "Popular"), ("relevance", "Relevance"), ("newest", "Newest"), ("updated", "Updated"))
PROFILE_KEYS = ("id", "minecraft_version", "loader", "loader_version", "version_id", "is_instance", "game_directory", "instance_name")


def _saved_profiles() -> list[dict]:
    from wisc.core.storage import load_installations
    return load_installations()


def _game_directory(profile: dict) -> Path:
    from wisc.services.launcher import get_profile_game_directory
    return get_profile_game_directory(profile)


def _runtime_directory() -> Path:
    from wisc.services.launcher import minecraft_directory
    return Path(minecraft_directory)


def _is_running() -> bool:
    from wisc.core.state import launcher_log_state
    return bool(launcher_log_state["running"] or launcher_log_state["downloading"])


def _profile_key(profile: dict | None) -> tuple:
    return tuple((profile or {}).get(key) for key in PROFILE_KEYS)


@dataclass
class BrowseState:
    query: str = ""
    sort: str = "downloads"
    offset: int = 0
    total: int = 0
    hits: list[dict] = field(default_factory=list)
    loaded_key: tuple | None = None
    scroll: int = 0


class _RefreshButton(GlassButton):
    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(theme.TEXT if self.isEnabled() else theme.DISABLED_TEXT)
        painter.setPen(QPen(color, theme.STROKE_ICON, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        cx, cy = self.width() / 2, self.height() / 2
        arc_rect = QRectF(cx - 7, cy - 7, 14, 14)
        painter.drawArc(arc_rect, 45 * 16, 280 * 16)
        head = QPainterPath()
        head.moveTo(cx + 2.5, cy - 7.5)
        head.lineTo(cx + 6.5, cy - 6.5)
        head.lineTo(cx + 5.5, cy - 2.5)
        painter.drawPath(head)


class ModsPage(QWidget):
    content_changed = pyqtSignal()
    profile_requested = pyqtSignal(str, str)
    progress_changed = pyqtSignal(str, object, object, bool)
    loading_changed = pyqtSignal(bool)

    PAGE_SIZE = 20

    def __init__(self, runner: ServiceRunner, colors: dict[str, str], parent: QWidget | None = None, *,
                 get_profiles: Callable[[], list[dict]] = _saved_profiles,
                 selected_profile: Callable[[], str | None] = lambda: None,
                 game_directory: Callable[[dict], Path] = _game_directory,
                 is_running: Callable[[], bool] = _is_running,
                 runtime_directory: Path | None = None, client: ModPlatformClient | None = None,
                 pack_installer: PackInstaller | None = None):
        super().__init__(parent)
        self.runner = runner
        self.client = client or ModPlatformClient()
        self._get_profiles, self._selected_profile = get_profiles, selected_profile
        self._game_directory, self._is_running = game_directory, is_running
        self._runtime_directory = runtime_directory
        self._pack_installer = pack_installer
        self._managers: OrderedDict[Path, ModManager] = OrderedDict()
        self._content_managers: OrderedDict[tuple[Path, str], ContentPackManager] = OrderedDict()
        self._profiles: list[dict] = []
        self.profile: dict | None = None
        self.manager: ModManager | None = None
        self.content_manager: ContentPackManager | None = None
        self.local_mods: list[LocalMod] = []
        self.local_packs: list[LocalContentPack] = []
        self._updates: dict[str, ModUpdate] = {}
        self._update_summary = ""
        self._release = "release"
        self._release_choices: dict[tuple, str] = {}
        self.kind = "mods"
        self.provider = "modrinth"
        self.view = "browse"
        self._modes = {key: "browse" for key, _ in CONTENT_OPTIONS}
        self._browse: dict[tuple[str, str], BrowseState] = {}
        self._installed_queries: dict[str, str] = {}
        self._installed_scrolls: dict[str, int] = {}
        self._profile_error = ""
        self._load_error = ""
        self._active = False
        self._loaded_profiles = False
        self._loading = False
        self._scanning = False
        self._loading_profiles = False
        self._checking = False
        self._busy = False
        self._closing = False
        self._phase = "idle"
        self._review: ReviewDialog | None = None
        self._progress: ServiceProgress | None = None
        self._operation_token: int | None = None
        self._undo: tuple[ModManager, str, str] | None = None
        self._pack_plan: PackPlan | None = None
        self._updating_list = False
        self._desired_id: str | None = None
        self._explicit_profile = False
        self._details = None
        self._detail_item: ContentItem | None = None
        self._detail_loaded = False
        self._profile_task = LatestServiceTask(runner)
        self._context_task = LatestServiceTask(runner)
        self._scan_task = LatestServiceTask(runner)
        self._identity_task = LatestServiceTask(runner)
        self._search_task = LatestServiceTask(runner)
        self._details_task = LatestServiceTask(runner)
        self._changelog_task = LatestServiceTask(runner)
        self._check_task = LatestServiceTask(runner)
        self._read_tasks = (self._profile_task, self._context_task, self._scan_task, self._identity_task,
                            self._search_task, self._details_task, self._changelog_task, self._check_task)
        self.images = ContentImages(runner, self)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(350)
        self._debounce.timeout.connect(self._load_browse)
        self._notice_timer = QTimer(self)
        self._notice_timer.setSingleShot(True)
        self._notice_timer.timeout.connect(lambda: self._notify(""))
        self._build_ui()
        self.apply_theme(colors)

    @property
    def details(self):
        if self._details is None:
            self._details = ContentDetails(self.images)
            self._details.back_requested.connect(self.close_details)
            self._details.retry_requested.connect(lambda: self._load_details(fresh=True))
            self._details.install_requested.connect(self._prepare_install)
            self._details.action_requested.connect(self._row_action)
            self._details.release_changed.connect(self._release_changed)
            self._details.link_requested.connect(self._open_link)
            self._details.version_opened.connect(self._load_changelog)
            self.body.addWidget(self._details)
            self._details.apply_theme(self._colors)
        return self._details

    @property
    def browse_state(self) -> BrowseState:
        return self._browse.setdefault((self.kind, self.provider), BrowseState())

    @property
    def can_cancel_operation(self) -> bool:
        return self._progress is not None and self._progress.cancelable

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*theme.PAGE_MARGINS)
        layout.setSpacing(12)
        header_bar = QWidget()
        header_bar.setFixedHeight(theme.HEADER_HEIGHT)
        header = QHBoxLayout(header_bar)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(12)
        self.heading = text_label("Mods", theme.FONT_PAGE_TITLE, bold=True)
        header.addWidget(self.heading)
        self.content_selector = LauncherComboBox(height=theme.BUTTON_HEIGHT, min_width=155, max_width=200)
        self.content_selector.setAccessibleName("Content type")
        for key, label in CONTENT_OPTIONS:
            self.content_selector.addItem(label, key)
        self.content_selector.currentIndexChanged.connect(self._kind_changed)
        header.addWidget(self.content_selector)
        header.addStretch()
        self.profile_selector = LauncherComboBox(height=theme.BUTTON_HEIGHT, min_width=240, max_width=320)
        self.profile_selector.setAccessibleName("Target profile; independent of Play selection")
        self.profile_selector.setPlaceholderText("Choose a profile")
        self.profile_selector.currentIndexChanged.connect(self._profile_selected)
        header.addWidget(self.profile_selector)
        layout.addWidget(header_bar)
        self.body = QStackedWidget()
        self._reveal = StaggeredReveal(self)
        layout.addWidget(self.body, 1)
        self.listing = QWidget()
        listing = QVBoxLayout(self.listing)
        listing.setContentsMargins(0, 0, 0, 0)
        listing.setSpacing(12)
        tabs = QHBoxLayout()
        tabs.setSpacing(8)
        self._tab_group = QButtonGroup(self)
        self.discover = QPushButton("Discover")
        self.installed = QPushButton("Installed")
        for button, view in ((self.discover, "browse"), (self.installed, "installed")):
            button.setObjectName("tab")
            button.setCheckable(True)
            button.setFixedHeight(theme.SEGMENT_HEIGHT)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self._tab_group.addButton(button)
            button.clicked.connect(lambda checked=False, name=view: self.set_view(name))
            tabs.addWidget(button)
        self.discover.setChecked(True)
        tabs.addStretch()
        self.attribution = text_label("Powered by Modrinth", theme.FONT_DETAIL, muted=True)
        tabs.addWidget(self.attribution)
        listing.addLayout(tabs)
        tools = QHBoxLayout()
        tools.setSpacing(8)
        self.search = GlassLineEdit(search_icon=True)
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Search content")
        self.search.setFixedHeight(theme.FIELD_HEIGHT)
        self.search.setMinimumWidth(180)
        self.search.textChanged.connect(self._query_changed)
        self.search.returnPressed.connect(self._submit_search)
        tools.addWidget(self.search, 1)
        self.provider_selector = LauncherComboBox(height=theme.FIELD_HEIGHT, min_width=138, max_width=170)
        self.provider_selector.addItem("Modrinth", "modrinth")
        self.provider_selector.addItem("CurseForge", "curseforge")
        self.provider_selector.setAccessibleName("Content provider")
        self.provider_selector.currentIndexChanged.connect(self._provider_changed)
        tools.addWidget(self.provider_selector)
        self.sort = LauncherComboBox(height=theme.FIELD_HEIGHT, min_width=150, max_width=195, prefix="Sort:")
        self.sort.setAccessibleName("Sort discoveries")
        for key, label in SORT_OPTIONS:
            self.sort.addItem(label, key)
        self.sort.currentIndexChanged.connect(self._sort_changed)
        tools.addWidget(self.sort)
        self.state_filter = LauncherComboBox(height=theme.FIELD_HEIGHT, min_width=126, max_width=160)
        for key, label in (("all", "All mods"), ("enabled", "Enabled"), ("disabled", "Disabled")):
            self.state_filter.addItem(label, key)
        self.state_filter.setAccessibleName("Filter installed mods")
        self.state_filter.currentIndexChanged.connect(self._filter_installed)
        tools.addWidget(self.state_filter)
        self.release_filter = LauncherComboBox(height=theme.FIELD_HEIGHT, min_width=130, max_width=165)
        self.release_filter.setAccessibleName("Release type for mod updates")
        for key, label in RELEASE_OPTIONS:
            self.release_filter.addItem(label, key)
        self.release_filter.currentIndexChanged.connect(lambda: self._release_changed(self.release_filter.currentData()))
        tools.addWidget(self.release_filter)
        self.add = GlassButton("Add JARs")
        self.add.setFixedHeight(theme.FIELD_HEIGHT)
        self.add.clicked.connect(self._add_files)
        tools.addWidget(self.add)
        self.updates = GlassButton("Check updates")
        self.updates.setFixedHeight(theme.FIELD_HEIGHT)
        self.updates.setMinimumWidth(132)
        self.updates.clicked.connect(self._updates_action)
        tools.addWidget(self.updates)
        self.key_button = GlassButton("API key")
        self.key_button.setFixedHeight(theme.FIELD_HEIGHT)
        self.key_button.clicked.connect(self._configure_curseforge)
        tools.addWidget(self.key_button)
        self.refresh_button = _RefreshButton()
        self.refresh_button.setFixedSize(theme.FIELD_HEIGHT, theme.FIELD_HEIGHT)
        self.refresh_button.setToolTip("Refresh")
        self.refresh_button.setAccessibleName("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        tools.addWidget(self.refresh_button)
        listing.addLayout(tools)
        status_bar = QHBoxLayout()
        status_bar.setContentsMargins(0, 0, 0, 0)
        status_bar.setSpacing(12)
        self.status = ElidedLabel()
        self.status.setProperty("muted", True)
        self.status.setFixedHeight(28)
        status_bar.addWidget(self.status, 1)
        self.pagination = ContentPagination()
        self.pagination.requested.connect(self._paginate)
        status_bar.addWidget(self.pagination)
        listing.addLayout(status_bar)
        self.results = QStackedWidget()
        self.list = ContentList(self.images)
        self.list.setAccessibleName("Discovered and installed content")
        self.list.item_opened.connect(self.open_details)
        self.list.action_requested.connect(self._row_action)
        self.list.verticalScrollBar().valueChanged.connect(self._remember_scroll)
        self.results.addWidget(self.list)
        self.skeleton = SkeletonList()
        self.results.addWidget(self.skeleton)
        self.empty = QWidget()
        empty = QVBoxLayout(self.empty)
        empty.setContentsMargins(32, 32, 32, 32)
        empty.addStretch()
        self.empty_title = text_label("Choose an instance", theme.FONT_DIALOG_TITLE, bold=True)
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_note = text_label("", theme.FONT_BODY, muted=True)
        self.empty_note.setWordWrap(True)
        self.empty_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_note.setMaximumWidth(620)
        empty.addWidget(self.empty_title, 0, Qt.AlignmentFlag.AlignHCenter)
        empty.addWidget(self.empty_note, 0, Qt.AlignmentFlag.AlignHCenter)
        self.empty_retry = GlassButton("Refresh profiles")
        self.empty_retry.setFixedHeight(theme.BUTTON_HEIGHT)
        self.empty_retry.clicked.connect(self.refresh)
        empty.addWidget(self.empty_retry, 0, Qt.AlignmentFlag.AlignHCenter)
        empty.addStretch()
        self.results.addWidget(self.empty)
        listing.addWidget(self.results, 1)
        self.body.addWidget(self.listing)
        self.notice_host = QWidget()
        self.notice_host.setFixedHeight(theme.SEGMENT_HEIGHT)
        notice = QHBoxLayout(self.notice_host)
        notice.setContentsMargins(0, 0, 0, 0)
        self.notice = ElidedLabel()
        self.notice.setProperty("muted", True)
        self.notice.setMinimumHeight(22)
        notice.addWidget(self.notice, 1)
        self.undo = GlassButton("Undo")
        self.undo.setFixedHeight(theme.COMPACT_HEIGHT)
        self.undo.setVisible(False)
        self.undo.clicked.connect(self._undo_remove)
        notice.addWidget(self.undo)
        layout.addWidget(self.notice_host)
        self.notice_host.setVisible(False)
        self._render()

    def apply_theme(self, colors: dict[str, str]) -> None:
        self._colors = colors
        self.list.set_accent(colors["btn_primary"], colors["btn_primary_text"])
        if self._details is not None:
            self._details.apply_theme(colors)

    def _save_view_state(self) -> None:
        if self.view == "browse":
            self.browse_state.scroll = self.list.verticalScrollBar().value()
        else:
            self._installed_scrolls[self.kind] = self.list.verticalScrollBar().value()

    def _remember_scroll(self, value: int) -> None:
        if not self._updating_list and self.body.currentWidget() is self.listing:
            if self.view == "browse":
                self.browse_state.scroll = value
            else:
                self._installed_scrolls[self.kind] = value

    def _restore_fields(self) -> None:
        browse = self.view == "browse"
        state = self.browse_state
        self.search.blockSignals(True)
        self.search.setText(state.query if browse else self._installed_queries.get(self.kind, ""))
        self.search.blockSignals(False)
        self.sort.blockSignals(True)
        self.sort.setCurrentIndex(max(0, self.sort.findData(state.sort)))
        self.sort.blockSignals(False)

    def _kind_changed(self) -> None:
        kind = self.content_selector.currentData()
        if kind == self.kind or self._busy or self._review:
            return
        self._save_view_state()
        self._invalidate_reads()
        self.close_details()
        self.kind = kind
        self.view = self._modes[kind]
        self._load_error = ""
        self._restore_fields()
        self._load_context(self.profile)

    def _provider_changed(self) -> None:
        provider = self.provider_selector.currentData()
        if provider == self.provider:
            return
        self._save_view_state()
        self._search_task.invalidate()
        self._debounce.stop()
        self.provider = provider
        self._load_error = ""
        self._restore_fields()
        self._load_browse()

    def set_view(self, view: str) -> None:
        if view == self.view or view not in {"browse", "installed"} or self._busy or self._review:
            return
        self._save_view_state()
        self._search_task.invalidate()
        self._debounce.stop()
        self.view = self._modes[self.kind] = view
        self._loading = False
        self._load_error = ""
        self._restore_fields()
        self._render()
        if view == "browse":
            self._load_browse()
        elif self.kind == "mods":
            self._identify_installed()

    def _query_changed(self, query: str) -> None:
        if self.view == "installed":
            self._installed_queries[self.kind] = query
            self._installed_scrolls[self.kind] = 0
            self._filter_installed()
        else:
            state = self.browse_state
            state.query, state.offset, state.scroll = query, 0, 0
            self._search_task.invalidate()
            self._loading = False
            self._debounce.start()

    def _submit_search(self) -> None:
        if self.view == "browse":
            self._debounce.stop()
            self._load_browse()

    def _sort_changed(self) -> None:
        state = self.browse_state
        state.sort, state.offset, state.scroll = self.sort.currentData(), 0, 0
        if self.view == "browse":
            self._load_browse()

    def _paginate(self, direction: int) -> None:
        if self._loading or self._busy:
            return
        state = self.browse_state
        state.offset = max(0, state.offset + direction * self.PAGE_SIZE)
        state.scroll = 0
        self._load_browse()

    def _filter_installed(self, *args) -> None:
        if self.view == "installed":
            self.list.set_filter(self.search.text(), self.state_filter.currentData() if self.kind == "mods" else "all")
            self.list.verticalScrollBar().setValue(0)
            self._render_feedback()

    def enter(self, profile_id: str | None = None) -> None:
        """Library shortcuts request only their actual saved profile."""
        if self._busy or self._review:
            return
        if profile_id is not None:
            self._desired_id, self._explicit_profile = profile_id, True
            if self.kind != "mods":
                self._save_view_state()
                self._invalidate_reads()
                self.kind = "mods"
                self.view = self._modes["mods"]
                self.content_selector.blockSignals(True)
                self.content_selector.setCurrentIndex(self.content_selector.findData("mods"))
                self.content_selector.blockSignals(False)
                self._restore_fields()
            self.close_details()
        if self._active:
            self._reload_profiles()

    def _reload_profiles(self, *, fresh: bool = False) -> None:
        if not self._active or self._busy or self._review:
            return
        self._loading_profiles = True
        self._render()

        def operation():
            if fresh:
                self.client.clear_cache()
            return [dict(profile) for profile in self._get_profiles()]

        def ready(profiles: list[dict]) -> None:
            self._loading_profiles = False
            self._profiles = profiles
            desired = self._desired_id or (self.profile or {}).get("id") or self._selected_profile()
            target = next((profile for profile in profiles if profile.get("id") == desired), None)
            if target is None and not self._explicit_profile:
                target = next((profile for profile in profiles if profile.get("is_instance")
                               and profile.get("loader", "").lower() in SUPPORTED_LOADERS), profiles[0] if profiles else None)
            if target is None and self._explicit_profile:
                self._notify("This preview profile has no saved instance. Choose an existing profile here.")
            self._desired_id = None
            self._explicit_profile = False
            self.profile_selector.blockSignals(True)
            self.profile_selector.clear()
            for profile in profiles:
                self.profile_selector.addItem(f"{profile.get('name', 'Profile')} · {profile.get('minecraft_version', '')} / {profile.get('loader', '')}", profile["id"])
            self.profile_selector.setCurrentIndex(self.profile_selector.findData(target["id"]) if target else -1)
            self.profile_selector.blockSignals(False)
            self._loaded_profiles = True
            self._load_context(target, fresh=fresh)

        def failed(error: Exception) -> None:
            self._loading_profiles = False
            self._profile_error = str(error)
            self._render()

        self._profile_task.submit(operation, ready, failed)

    def _profile_selected(self) -> None:
        if self._busy or self._review:
            return
        target = next((profile for profile in self._profiles if profile["id"] == self.profile_selector.currentData()), None)
        self._load_context(target)

    def _load_context(self, profile: dict | None, *, fresh: bool = False) -> None:
        changed = _profile_key(profile) != _profile_key(self.profile)
        self._search_task.invalidate()
        self._scan_task.invalidate()
        self._identity_task.invalidate()
        self._check_task.invalidate()
        self._details_task.invalidate()
        self._changelog_task.invalidate()
        self._checking = False
        self._load_error = self._profile_error = ""
        self._loading = False
        if changed:
            self.close_details()
            self.local_mods = []
            self.local_packs = []
            self._updates.clear()
            self._update_summary = ""
            for state in self._browse.values():
                state.hits, state.offset, state.total, state.scroll, state.loaded_key = [], 0, 0, 0, None
        self.profile = dict(profile) if profile else None
        self.manager = self.content_manager = None
        self._scanning = bool(profile)
        kind = self.kind
        self._render()
        if not self._active:
            self._scanning = False
            return

        def operation():
            if not profile:
                return None, None
            if kind == "mods" and not profile.get("is_instance"):
                return None, None
            directory = Path(self._game_directory(profile)).resolve()
            if not directory.is_dir():
                raise ValueError("This profile's game folder is missing. Restore it or edit the profile in the launcher.")
            manager, content_manager = None, None
            if kind == "mods" and profile.get("is_instance"):
                if directory not in self._managers:
                    self._managers[directory] = ModManager(directory, runtime_directory=self._runtime_directory or _runtime_directory())
                    if len(self._managers) > 8:
                        self._managers.popitem(last=False)
                manager = self._managers[directory]
                self._managers.move_to_end(directory)
                if fresh:
                    manager.clear_update_check(profile["minecraft_version"], profile["loader"].lower(),
                                               loader_version=profile.get("loader_version", ""), release_type=self._release)
            elif kind in {"shader", "resourcepack"}:
                key = (directory, kind)
                if key not in self._content_managers:
                    self._content_managers[key] = ContentPackManager(directory, kind)
                    if len(self._content_managers) > 8:
                        self._content_managers.popitem(last=False)
                content_manager = self._content_managers[key]
                self._content_managers.move_to_end(key)
            return manager, content_manager

        def ready(context) -> None:
            self._scanning = False
            self.manager, self.content_manager = context
            self._scan_installed()
            self._load_browse()
            if self._detail_item is not None and not self._detail_loaded:
                self._load_details()

        def failed(error: Exception) -> None:
            self._scanning = False
            self._profile_error = str(error)
            self._render()

        self._context_task.submit(operation, ready, failed)

    def _compatible(self) -> bool:
        return bool(self.manager and self.profile and self.profile.get("is_instance")
                    and self.profile.get("loader", "").lower() in SUPPORTED_LOADERS and self.profile.get("minecraft_version"))

    def _can_browse(self) -> bool:
        if self.kind == "modpacks":
            return True
        if self.kind == "mods":
            return self._compatible()
        return bool(self.content_manager and self.profile)

    def _scan_installed(self) -> None:
        if self.kind == "modpacks":
            self._render()
            return
        if (self.kind == "mods" and not self._compatible()) or (self.kind != "mods" and not self.content_manager):
            self._render()
            return
        self._scanning = True
        manager, profile, kind, release = self.manager or self.content_manager, dict(self.profile), self.kind, self._release
        chosen_release = self._release_choices.get(_profile_key(profile))
        self._render()

        def operation():
            if kind != "mods":
                return manager.scan(), None, release
            mods = manager.list_mods()
            selected = chosen_release or manager.saved_update_release_type(profile["minecraft_version"], profile["loader"].lower(),
                                                                           profile.get("loader_version", ""), profile.get("version_id", "")) or "release"
            check = manager.cached_update_check(profile["minecraft_version"], profile["loader"].lower(),
                                                 loader_version=profile.get("loader_version", ""), release_type=selected,
                                                 version_id=profile.get("version_id", ""))
            return mods, check, selected

        def ready(result) -> None:
            self._scanning = False
            items, check, selected = result
            if kind == "mods":
                self.local_mods = list(check.mods) if check else items
                self._set_release(selected)
                self._apply_update_check(check, saved=True)
                if self.view == "installed":
                    self._identify_installed()
            else:
                self.local_packs = items
            self._render()
            self._sync_details()

        def failed(error: Exception) -> None:
            self._scanning = False
            self._load_error = str(error)
            self._render()

        self._scan_task.submit(operation, ready, failed)

    def _identify_installed(self) -> None:
        if not self._compatible() or self._scanning or self._busy:
            return
        manager = self.manager

        def ready(result) -> None:
            self.local_mods, warnings = result
            if warnings:
                self._notify("\n".join(warnings[:3]))
            self._render()
            self._sync_details()

        self._identity_task.submit(lambda: manager.identify_mods(self.client), ready,
                                   lambda error: self._notify(str(error)))

    def _search_key(self) -> tuple:
        state = self.browse_state
        context = () if self.kind == "modpacks" else _profile_key(self.profile)
        return self.kind, self.provider, context, state.query.strip(), state.sort, state.offset

    def _load_browse(self) -> None:
        self._debounce.stop()
        if not self._active or self.view != "browse" or self._busy or not self._can_browse():
            self._render()
            return
        state = self.browse_state
        key = self._search_key()
        if state.loaded_key == key:
            self._loading = False
            self._render()
            return
        self._loading = True
        self._load_error = ""
        state.hits, state.total = [], 0
        profile, kind, provider = dict(self.profile or {}), self.kind, self.provider
        query, sort, offset = state.query.strip(), state.sort, state.offset
        self._render()

        def operation():
            args = {"provider": provider, "index": sort, "offset": offset, "limit": self.PAGE_SIZE}
            if kind == "modpacks":
                return self.client.search_modpacks(query, **args)
            if kind != "mods":
                return self.client.search_content(query, profile["minecraft_version"], kind, **args)
            return self.client.search(query, profile["minecraft_version"], profile["loader"].lower(), **args)

        def ready(data: dict) -> None:
            if key != self._search_key() or self.view != "browse":
                return
            self._loading = False
            state.hits, state.total, state.loaded_key = data["hits"], int(data.get("total_hits", len(data["hits"]))), key
            self._render()

        def failed(error: Exception) -> None:
            self._loading = False
            self._load_error = str(error)
            self._render()

        self._search_task.submit(operation, ready, failed)

    def refresh(self) -> None:
        if self._busy or self._review:
            return
        self._invalidate_reads()
        self.browse_state.loaded_key = None
        self._updates.clear()
        self._update_summary = ""
        self._detail_loaded = False
        self._reload_profiles(fresh=True)

    def _invalidate_reads(self) -> None:
        self._debounce.stop()
        for task in self._read_tasks:
            task.invalidate()
        self._loading = self._scanning = self._loading_profiles = self._checking = False

    def _installed_profiles(self) -> list[dict]:
        return [profile for profile in self._profiles if isinstance(profile.get("modpack"), dict)]

    def _installed_items(self) -> list[ContentItem]:
        if self.kind == "mods":
            return [ContentItem(
                mod.filename, mod.name, mod.description,
                " · ".join(filter(None, (mod.version, format_size(mod.size), "Pack managed" if mod.pack_owned else ""))),
                mod.icon, (ContentAction("toggle", "Disable mod" if mod.enabled else "Enable mod", switch=True),
                           ContentAction("update", "Update", mod.filename in self._updates, True),
                           ContentAction("remove", "Remove", primary=True)) if mod.filename in self._updates else
                          (ContentAction("toggle", "Disable mod" if mod.enabled else "Enable mod", switch=True), ContentAction("remove", "Remove", primary=True)),
                checked=mod.enabled, payload=mod, search_text=mod.filename,
            ) for mod in self.local_mods]
        if self.kind == "modpacks":
            return [ContentItem(
                profile["id"], profile.get("name", "Modpack"),
                f"{profile['modpack'].get('name', '')} · Pack {profile['modpack'].get('version', 'Imported')}",
                f"{profile.get('minecraft_version', '')} / {profile.get('loader', '')} {profile.get('loader_version', '')}",
                profile.get("icon"), (ContentAction("mods", "Mods"), ContentAction("folder", "Folder")), payload=profile,
            ) for profile in self._installed_profiles()]
        return [ContentItem(pack.filename, pack.title, pack.filename,
                            " · ".join(filter(None, (pack.version, format_size(pack.size)))),
                            actions=(ContentAction("remove", "Remove", primary=True),), payload=pack) for pack in self.local_packs]

    def _browse_items(self) -> list[ContentItem]:
        if self.kind == "mods":
            installed = {mod.project_id for mod in self.local_mods if mod.project_id}
        elif self.kind == "modpacks":
            installed = {profile["modpack"].get("project_id") for profile in self._installed_profiles()}
        else:
            installed = {pack.project_id for pack in self.local_packs if pack.project_id}
        return [ContentItem(
            str(hit.get("project_id") or hit.get("id")), hit.get("title") or hit.get("name", "Project"), hit.get("description", ""),
            " · ".join(filter(None, (hit.get("author", ""), f"{format_downloads(int(hit.get('downloads', 0)))} downloads"))),
            hit.get("icon_url"), (ContentAction("install", "Installed" if hit.get("project_id") in installed else "Install",
                                               hit.get("project_id") not in installed, True),), payload=hit,
        ) for hit in self.browse_state.hits]

    def _empty_state(self) -> tuple[str, str]:
        if self._loading_profiles or self._scanning:
            return "Loading profiles…" if self._loading_profiles else "Reading installed content…", "Your launcher stays responsive while this loads."
        if self._profile_error:
            return "Instance unavailable", self._profile_error
        if self.kind != "modpacks" and not self.profile:
            return "Choose a profile", "Select an existing profile above. Create and install profiles in the existing launcher, then refresh here."
        if self.kind == "mods" and self.profile and not self.profile.get("is_instance"):
            return "Use a separate instance", "This profile uses the global Minecraft folder. Create a separate instance in the launcher to keep its mods isolated from other profiles."
        if self.kind == "mods" and not self._compatible():
            return "This profile needs a mod loader", "Choose an instance with Fabric, Quilt, Forge, or NeoForge and a Minecraft version."
        if self._load_error:
            return "Could not load content", redact_credentials(self._load_error)
        if self._loading:
            return "Searching…", "Finding compatible content on " + ("CurseForge" if self.provider == "curseforge" else "Modrinth") + "."
        if self.view == "browse":
            return "No compatible results", "Try a different search or provider."
        return "No installed content", "Add local JARs or browse compatible projects." if self.kind == "mods" else "Install a pack from Discover to get started."

    def _render(self) -> None:
        if not hasattr(self, "list"):
            return
        browse, mods, packs = self.view == "browse", self.kind == "mods", self.kind == "modpacks"
        self.heading.setText(dict(CONTENT_OPTIONS)[self.kind])
        self.profile_selector.setVisible(not packs)
        locked = self._busy or self._review is not None
        for field in (self.content_selector, self.profile_selector, self.search, self.provider_selector, self.sort,
                      self.state_filter, self.release_filter, self.discover, self.installed, self.add, self.key_button, self.refresh_button):
            field.setEnabled(not locked)
        self.discover.setChecked(browse)
        self.installed.setChecked(not browse)
        count = len(self.local_mods) if mods else len(self._installed_profiles()) if packs else len(self.local_packs)
        self.installed.setText(f"Installed ({count})")
        self.attribution.setVisible(browse)
        self.attribution.setText("Powered by " + ("CurseForge" if self.provider == "curseforge" else "Modrinth"))
        self.provider_selector.setVisible(browse)
        self.sort.setVisible(browse)
        self.state_filter.setVisible(not browse and mods)
        self.release_filter.setVisible(not browse and mods)
        self.key_button.setVisible(browse and self.provider == "curseforge")
        self.add.setVisible(packs or (mods and not browse))
        self.add.setText("Import pack" if packs else "Add JARs")
        self.add.setEnabled(not locked and not self._is_running() and (packs or self._compatible()))
        self.updates.setVisible(mods and not browse)
        self.updates.setText("Checking…" if self._checking else "Update all" if self._updates else "Check updates")
        self.updates.setEnabled(not locked and not self._scanning and not self._checking and self._compatible())
        self.search.setPlaceholderText("Search " + ("installed " if not browse else "") + dict(CONTENT_OPTIONS)[self.kind].lower())
        self.list.actions_enabled = not locked and not self._is_running()
        if self._details is not None:
            self._details.set_can_change(not locked and not self._is_running() and (packs or self._can_browse()))
        rows = self._browse_items() if browse else self._installed_items()
        offset = self.browse_state.scroll if browse else self._installed_scrolls.get(self.kind, 0)
        if self.body.currentWidget() is self.listing:
            self._updating_list = True
            self.list.set_items(rows)
            self.list.set_filter("" if browse else self.search.text(), self.state_filter.currentData() if not browse and mods else "all")
            self.list.verticalScrollBar().setValue(offset)
            self._updating_list = False
        usable = packs or self._can_browse()
        loading = self._loading or self._scanning or self._loading_profiles
        if rows and usable:
            was_list = self.results.currentWidget() is self.list
            self.results.setCurrentWidget(self.list)
            if not was_list:
                self.list.reveal_wave()
        elif loading and usable:
            self.results.setCurrentWidget(self.skeleton)
        else:
            self.results.setCurrentWidget(self.empty)
        title, note = self._empty_state()
        self.empty_title.setText(title)
        self.empty_note.setText(note)
        self.empty_retry.setVisible(not self._loading and not self._loading_profiles and not self._scanning)
        self.empty_retry.setEnabled(not locked)
        self.pagination.display(self.browse_state.offset, self.browse_state.total if browse else 0,
                                busy=self._loading or locked)
        self.loading_changed.emit(self._active and (self._loading or self._scanning or self._loading_profiles or self._checking))
        self.undo.setEnabled(not locked and not self._is_running())
        self._render_feedback()

    def _render_feedback(self) -> None:
        if self._loading:
            message = "Searching…"
        elif self._scanning or self._loading_profiles:
            message = "Reading installed content…"
        elif self.view == "browse":
            message = f"{self.browse_state.total:,} compatible results" if self.kind != "modpacks" else f"{self.browse_state.total:,} modpacks"
        elif self.kind == "mods":
            enabled = sum(mod.enabled for mod in self.local_mods)
            message = f"{enabled} enabled · {len(self.local_mods) - enabled} disabled"
            if self._update_summary:
                message += " · " + self._update_summary
        else:
            message = f"{self.list.proxy.rowCount()} installed"
        if self.kind == "shader":
            message += " · Enable in Minecraft with Iris or OptiFine"
        elif self.kind == "resourcepack":
            message += " · Enable in Minecraft's Resource Packs settings"
        self.status.setText(message)

    def _notify(self, message: str, *, undo: tuple[ModManager, str, str] | None = None) -> None:
        self._notice_timer.stop()
        self.notice.setText(redact_credentials(message))
        self.notice_host.setVisible(bool(message))
        if undo is not None or not message:
            self._undo = undo
        self.undo.setVisible(self._undo is not None)
        if message:
            self._notice_timer.start(15000 if self._undo else 8000)

    def _open_link(self, url: str) -> None:
        target = QUrl(url)
        if target.scheme() in {"http", "https"} and not QDesktopServices.openUrl(target):
            self._notify("Could not open the link in your browser.")

    def open_details(self, item: ContentItem) -> None:
        if self._busy or self._review:
            return
        self._save_view_state()
        self._search_task.invalidate()
        self._loading = False
        self._detail_item, self._detail_loaded = item, False
        self.details.open(item, self.kind, self.profile)
        self.details.set_release(self._release)
        self.body.setCurrentWidget(self.details)
        self._reveal.reveal(self.details)
        self._render()
        self._load_details()

    def close_details(self) -> None:
        if not hasattr(self, "body"):
            return
        self._details_task.invalidate()
        self._changelog_task.invalidate()
        self._detail_item = None
        self._detail_loaded = False
        self.body.setCurrentWidget(self.listing)
        self._reveal.reveal(self.listing)
        self._render()

    def _details_payload(self, item: ContentItem, profile: dict, kind: str, manager: ModManager | None,
                         release: str) -> dict:
        payload = item.payload
        local_info, local, warning = {}, None, ""
        project = {"title": item.title, "description": item.description}
        if isinstance(payload, LocalMod):
            local = payload
            local_info = manager.describe_mod(payload.filename)
            project_id = payload.project_id
            if not project_id:
                try:
                    matched = manager.identify_local(payload.filename, self.client)
                    if matched:
                        project_id = matched.get("project_id", "")
                        local = replace(payload, project_id=project_id, version_id=matched.get("id", ""))
                except Exception as error:
                    warning = str(error)
        elif isinstance(payload, LocalContentPack):
            local = payload
            project_id = payload.project_id
        elif kind == "modpacks" and payload.get("modpack"):
            local = payload
            project_id = payload["modpack"].get("project_id", "")
        else:
            project_id = payload.get("project_id") or payload.get("id", "")
        result = {"project": project, "local_info": local_info, "local": local, "versions": [], "members": [], "warning": warning}
        if not project_id:
            return result
        project["project_id"] = project_id
        if kind == "modpacks":
            operations = (lambda: self.client.modpack_project(project_id), lambda: self.client.modpack_versions(project_id))
        elif kind in {"shader", "resourcepack"}:
            operations = (lambda: self.client.content_project(project_id, kind),
                          lambda: self.client.content_versions(project_id, profile["minecraft_version"], kind))
        else:
            operations = (lambda: self.client.project(project_id), lambda: self.client.project_versions(project_id),
                          lambda: self.client.project_members(project_id))
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="Wisc details") as executor:
            futures = [executor.submit(operation) for operation in operations]
            for name, future in zip(("project", "versions", "members"), futures):
                try:
                    value = future.result()
                    result[name] = {**project, **value} if name == "project" else value
                except Exception as error:
                    result["warning"] = str(error)
        if kind == "mods" and local and not local.pack_owned:
            versions = result["versions"]
            current = next((version for version in versions if version.get("id") == local.version_id), None)
            if current:
                try:
                    loader = profile["loader"].lower()
                    providers = ()
                    if loader == "fabric" and profile.get("loader_version"):
                        providers, _ = manager.profile_providers(profile["minecraft_version"], loader,
                                                                 profile["loader_version"], profile.get("version_id", ""), runtime_only=True)

                    def check_loader(version: dict) -> bool:
                        compatible = version_matches_environment(self.client, version, loader,
                                                                 profile.get("loader_version", ""), providers)
                        version["_profile_compatible"] = compatible
                        return compatible

                    result["update"] = newer_compatible_version(
                        current, versions, profile["minecraft_version"], loader, release_type=release,
                        loader_version=profile.get("loader_version", ""), check_loader=check_loader if loader == "fabric" else None,
                    )
                except Exception as error:
                    result["warning"] = str(error)
        return result

    def _load_details(self, *, fresh: bool = False) -> None:
        if not self._active or self._detail_item is None or self._busy:
            return
        item, profile, kind, manager, release = self._detail_item, dict(self.profile or {}), self.kind, self.manager, self._release
        self._detail_loaded = False
        self.details.set_feedback("Loading details…")

        def operation():
            if fresh:
                self.client.clear_cache()
            return self._details_payload(item, profile, kind, manager, release)

        def ready(data: dict) -> None:
            self._detail_loaded = True
            local = data.get("local")
            if isinstance(local, LocalMod) and local.project_id:
                self.local_mods = [local if mod.filename == local.filename else mod for mod in self.local_mods]
            self.details.display(data)
            self._render()

        def failed(error: Exception) -> None:
            self.details.set_feedback(redact_credentials(str(error)))

        self._details_task.submit(operation, ready, failed)

    def _load_changelog(self, version: dict) -> None:
        self._changelog_task.invalidate()
        if not str(version.get("id", "")).startswith("cf:") or version.get("_changelog_loaded"):
            return
        self.details.changelog_body.display("Loading changelog…")

        def operation():
            result = self.client.version(version["id"])
            if result.get("id") != version["id"] or result.get("project_id") != version.get("project_id"):
                raise ValueError("The provider returned a different version's changelog.")
            if result.get("_changelog_unavailable"):
                raise ConnectionError("The changelog is unavailable. Reopen this version to retry.")
            return result.get("changelog", "")

        def ready(body: str) -> None:
            version["changelog"] = body
            version["_changelog_loaded"] = True
            if self.details._selected_version is version:
                self.details.changelog_body.display(body or "No changelog supplied.", "https://www.curseforge.com/")

        self._changelog_task.submit(operation, ready, lambda error:
                                   self.details.changelog_body.display(redact_credentials(str(error))))

    def _sync_details(self) -> None:
        if self._detail_item is None:
            return
        original = self._detail_item.payload
        project_id = self.details.project.get("project_id")
        if self.kind == "mods":
            local = next((mod for mod in self.local_mods if
                          jar_base_name(mod.filename) == jar_base_name(getattr(original, "filename", ""))
                          or (project_id and mod.project_id == project_id)), None)
        elif self.kind in {"shader", "resourcepack"}:
            local = next((pack for pack in self.local_packs if pack.filename == getattr(original, "filename", "")
                          or (project_id and pack.project_id == project_id)), None)
        else:
            return
        self.details.sync_local(local)

    def _set_release(self, release: str) -> None:
        self._release = release
        self._release_choices[_profile_key(self.profile)] = release
        self.release_filter.blockSignals(True)
        self.release_filter.setCurrentIndex(max(0, self.release_filter.findData(release)))
        self.release_filter.blockSignals(False)
        if self._details is not None:
            self._details.set_release(release)

    def _release_changed(self, release: str) -> None:
        if release == self._release or release not in dict(RELEASE_OPTIONS):
            return
        self._check_task.invalidate()
        self._checking = False
        self._set_release(release)
        self._apply_update_check(None)
        self._render()
        if self._detail_item is not None:
            self._load_details()
        if self._compatible():
            manager, profile = self.manager, dict(self.profile)
            self._check_task.submit(
                lambda: manager.cached_update_check(profile["minecraft_version"], profile["loader"].lower(),
                                                     loader_version=profile.get("loader_version", ""), release_type=release,
                                                     version_id=profile.get("version_id", "")),
                lambda result: self._restore_check(result), lambda error: self._notify(str(error)),
            )

    def _restore_check(self, result: UpdateCheck | None) -> None:
        self._apply_update_check(result, saved=True)
        self._render()

    def _apply_update_check(self, result: UpdateCheck | None, *, saved: bool = False) -> None:
        self._updates = {update.mod.filename: update for update in result.updates} if result else {}
        self._update_summary = ""
        if result is not None:
            self._update_summary = f"{len(result.updates)} updates available" if result.updates else "No updates found"
            if result.warnings:
                self._update_summary += " · Some mods could not be checked"
            if saved:
                self._update_summary += " · Saved check"

    def _updates_action(self) -> None:
        if self._updates:
            updates = tuple(self._updates.values())
            self._prepare_install({"project_id": updates[0].version["project_id"], "title": f"{len(updates)} mods"}, updates=updates)
            return
        if not self._compatible() or self._busy or self._checking:
            return
        self._identity_task.invalidate()
        self._checking = True
        manager, profile, release = self.manager, dict(self.profile), self._release
        self._render()

        def operation():
            self.client.clear_cache()
            return manager.check_updates(self.client, profile["minecraft_version"], profile["loader"].lower(),
                                         loader_version=profile.get("loader_version", ""), release_type=release,
                                         version_id=profile.get("version_id", ""))

        def ready(result: UpdateCheck) -> None:
            self._checking = False
            self.local_mods = list(result.mods)
            self._apply_update_check(result)
            if result.warnings:
                self._notify("\n".join(result.warnings[:4]))
            self._render()
            self._sync_details()

        def failed(error: Exception) -> None:
            self._checking = False
            self._notify(str(error))
            self._render()

        self._check_task.submit(operation, ready, failed)

    def _can_operate(self) -> bool:
        if self._busy or self._review or self._is_running() or (self.kind != "modpacks" and not self._can_browse()):
            self._notify("Choose a compatible profile and close Minecraft before changing content.")
            return False
        return True

    def _validate_target(self, profile: dict) -> None:
        current = next((item for item in self._get_profiles() if item.get("id") == profile["id"]), None)
        if _profile_key(current) != _profile_key(profile):
            raise ValueError("The target profile changed. Refresh and review the installation again.")
        if not Path(self._game_directory(profile)).is_dir():
            raise ValueError("The target instance folder is missing. Restore it before changing content.")

    def _commit_guard(self, progress: ServiceProgress, profile: dict | None = None) -> bool:
        progress.check_cancelled()
        if self._closing or self._is_running():
            return False
        if profile:
            self._validate_target(profile)
        progress.seal_commit()
        return True

    def _execute(self, operation: Callable[[ServiceProgress], Any], message: str, success: Callable,
                 *, phase: str = "installing") -> None:
        if self._busy or self._closing:
            return
        self._invalidate_reads()
        self._busy, self._phase = True, phase
        progress = self._progress = ServiceProgress(message, self)
        progress.changed.connect(lambda text, current, total: self.progress_changed.emit(text, current, total, True))
        self.progress_changed.emit(message, 0, None, True)
        self._render()

        def finish() -> None:
            progress.finish()
            progress.deleteLater()
            self._progress = None
            self._operation_token = None
            self._busy, self._phase = False, "idle"
            self.progress_changed.emit("", 0, None, False)

        def ready(value) -> None:
            finish()
            if self._closing:
                return
            success(value)
            self._render()

        def failed(error: Exception) -> None:
            finish()
            if self._closing:
                return
            self._notify(str(error))
            self._render()
            if self._active:
                self._scan_installed()
                self._load_browse()

        self._operation_token = self.runner.submit(lambda: operation(progress), ready, failed)

    def cancel_operation(self) -> None:
        if self._progress:
            if self._progress.cancel():
                self.progress_changed.emit("Canceling…", 0, None, True)
            else:
                self.progress_changed.emit("Finishing installation…", 0, None, True)

    def _show_review(self, dialog: ReviewDialog, *, on_cancel: Callable | None = None) -> None:
        self._review = dialog
        dialog.link_requested.connect(self._open_link)

        def finished(result: int) -> None:
            if self._review is dialog:
                self._review = None
            if result != ReviewDialog.DialogCode.Accepted and on_cancel is not None:
                on_cancel()
            self._render()
            if not self._busy and self._active:
                self._scan_installed()
                self._load_browse()

        dialog.finished.connect(finished)
        self._render()
        dialog.open()

    def _row_action(self, item: ContentItem, action: str) -> None:
        if item is None:
            return
        payload = item.payload
        if action == "install":
            self._prepare_install(payload)
        elif action == "update" and isinstance(payload, LocalMod):
            update = self._updates.get(payload.filename)
            if update:
                self._prepare_install({"project_id": update.version["project_id"], "title": payload.name}, updates=(update,))
        elif action == "toggle":
            local = self.details._local if item is self._detail_item else payload
            if isinstance(local, LocalMod):
                self._toggle(local)
        elif action == "remove":
            local = self.details._local if item is self._detail_item else payload
            if isinstance(local, (LocalMod, LocalContentPack)):
                self._confirm_remove(local)
        elif action == "mods" and isinstance(payload, dict):
            self.enter(payload["id"])
        elif action == "folder" and isinstance(payload, dict):
            self.runner.submit(lambda: self._game_directory(payload),
                               lambda folder: QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))),
                               lambda error: self._notify(str(error)))

    def _toggle(self, mod: LocalMod) -> None:
        if not self._can_operate():
            return
        manager, profile = self.manager, dict(self.profile)

        def operation(progress):
            if not self._commit_guard(progress, profile):
                raise ValueError("Close Minecraft before changing mods.")
            manager.set_enabled(mod.filename, not mod.enabled)

        self._execute(operation, "Updating mod…", lambda result:
                      self._changed(f"{mod.name} {'disabled' if mod.enabled else 'enabled'}."))

    def _add_files(self) -> None:
        if not self._can_operate():
            return
        if self.kind == "modpacks":
            files, _ = QFileDialog.getOpenFileNames(self, "Import Minecraft modpack", "", "Modpacks (*.mrpack *.zip)")
            if files:
                self._prepare_pack(path=Path(files[0]))
            return
        files, _ = QFileDialog.getOpenFileNames(self, "Add Minecraft mod JARs", "", "JAR files (*.jar)")
        if not files:
            return
        manager, profile, paths = self.manager, dict(self.profile), [Path(file) for file in files]

        def operation(progress):
            if not self._commit_guard(progress, profile):
                raise ValueError("Close Minecraft before changing mods.")
            return manager.import_jars(paths, loader=profile["loader"].lower(), loader_version=profile.get("loader_version", ""))

        self._execute(operation, "Adding local mods…", lambda count: self._changed(f"Added {count} mods."))

    def _confirm_remove(self, item: LocalMod | LocalContentPack) -> None:
        if not self._can_operate():
            return
        manager, profile = self.manager or self.content_manager, dict(self.profile)
        name = item.name if isinstance(item, LocalMod) else item.title
        dialog = ReviewDialog("Remove " + name, self.runner, self, action="Remove")
        note = text_label(f"Remove {item.filename} from {profile.get('name', 'this profile')}?" +
                          (" You can undo this removal." if isinstance(item, LocalMod) else ""), theme.FONT_BODY)
        note.setWordWrap(True)
        dialog.body.addWidget(note)
        dialog.resize(600, 280)

        def remove() -> None:
            self._review = None

            def operation(progress):
                if not self._commit_guard(progress, profile):
                    raise ValueError("Close Minecraft before removing content.")
                return manager.remove(item.filename) if isinstance(item, LocalMod) else manager.remove(item, can_commit=lambda: not self._is_running())

            def ready(token) -> None:
                self._changed(f"Removed {name}.", undo=(manager, token, name) if isinstance(item, LocalMod) else None)

            self._execute(operation, "Removing content…", ready)

        dialog.accepted.connect(remove)
        self._show_review(dialog)

    def _undo_remove(self) -> None:
        if not self._undo or self._busy or self._review or self._is_running():
            return
        manager, token, name = self._undo

        def operation(progress):
            if not manager.game_directory.is_dir():
                raise ValueError("The original instance folder is missing. Restore it before undoing removal.")
            if not self._commit_guard(progress):
                raise ValueError("Close Minecraft before restoring mods.")
            manager.restore(token)

        def restored(result) -> None:
            self._undo = None
            self._changed(f"Restored {name}.")

        self._execute(operation, "Restoring mod…", restored)

    def _changed(self, message: str, *, undo: tuple[ModManager, str, str] | None = None) -> None:
        self.content_changed.emit()
        self._notify(message, undo=undo)
        self._apply_update_check(None)
        if self._active:
            self._scan_installed()
            self._load_browse()
            if self._detail_item is not None:
                self._load_details()

    def _prepare_install(self, project: dict, selected_version: dict | None = None, *, updates: tuple[ModUpdate, ...] = ()) -> None:
        if not self._can_operate():
            return
        if self.kind == "modpacks":
            self._prepare_pack(project=project, version=selected_version)
            return
        if self.kind in {"shader", "resourcepack"}:
            self._prepare_content(project, selected_version)
            return
        manager, profile, release = self.manager, dict(self.profile), self._release

        def operation(progress):
            progress.check_cancelled()
            self._validate_target(profile)
            if updates:
                plan = manager.plan_updates(self.client, updates, profile["minecraft_version"], profile["loader"].lower(),
                                             loader_version=profile.get("loader_version", ""), release_type=release,
                                             version_id=profile.get("version_id", ""))
            else:
                plan = manager.plan_install(self.client, project["project_id"], profile["minecraft_version"], profile["loader"].lower(),
                                             selected_version=selected_version, loader_version=profile.get("loader_version", ""),
                                             version_id=profile.get("version_id", ""))
            progress.check_cancelled()
            manual = [file for version in plan.versions if (file := primary_file(version)).get("manual_required")]
            return plan, manual_ready_ids(self.client, manual)

        def ready(result) -> None:
            plan, ids = result
            if not plan.versions:
                self._notify("This mod is already installed.")
                return
            if not self._active:
                return
            review = ModInstallReview(project, profile, plan, manager, self.client, self.runner, self.images, self,
                                      ready_ids=ids, updates=updates)

            def install(confirmed: InstallPlan) -> None:
                self._review = None

                def operation(progress):
                    self._validate_target(profile)
                    return manager.install(self.client, confirmed, progress,
                                           can_commit=lambda: self._commit_guard(progress, profile))

                self._execute(operation, "Downloading mods…", lambda count:
                              self._changed(f"Updated {len(updates)} mods." if updates else f"Installed {project.get('title', 'mod')}."))

            review.install_requested.connect(install)
            self._show_review(review)

        self._execute(operation, "Checking mod dependencies…", ready, phase="preparing")

    def _prepare_content(self, project: dict, selected_version: dict | None) -> None:
        manager, profile, kind = self.content_manager, dict(self.profile), self.kind

        def operation(progress):
            self._validate_target(profile)
            full = self.client.content_project(project["project_id"], kind)
            versions = self.client.content_versions(project["project_id"], profile["minecraft_version"], kind)
            if not versions:
                raise ValueError("No compatible pack version is available for this profile.")
            if selected_version and not any(version["id"] == selected_version["id"] for version in versions):
                raise ValueError("This version is no longer compatible with the selected profile.")
            manual = [file for version in versions if (file := primary_content_file(version)).get("manual_required")]
            ids = manual_ready_ids(self.client, manual)
            progress.check_cancelled()
            return full, versions, ids

        def ready(result) -> None:
            full, versions, ids = result
            if not self._active:
                return
            selected = selected_version or next((version for version in versions if version.get("version_type") == "release"), versions[0])
            review = ContentInstallReview(full, profile, versions, self.client, self.runner, self, selected=selected, ready_ids=ids)

            def install(version: dict) -> None:
                self._review = None

                def operation(progress):
                    self._validate_target(profile)
                    return manager.install(self.client, full, version, profile["minecraft_version"], progress,
                                           can_commit=lambda: self._commit_guard(progress, profile))

                self._execute(operation, "Downloading pack…", lambda path: self._changed(f"Installed {full.get('title', 'pack')}."))

            review.install_requested.connect(install)
            self._show_review(review)

        self._execute(operation, "Finding compatible pack versions…", ready, phase="preparing")

    def _installer(self) -> PackInstaller:
        if self._pack_installer is None:
            self._pack_installer = PackInstaller(self._runtime_directory or _runtime_directory(), client=self.client)
        return self._pack_installer

    def _suggest_folder(self, installer: PackInstaller, plan: PackPlan) -> str:
        from wisc.services.profiles import instance_folder_name, new_instance_directory
        base = instance_folder_name("", plan.name)[:100]
        profiles = installer.storage.load_installations()
        for number in range(1, 10001):
            folder = base if number == 1 else f"{base}_{number}"
            try:
                new_instance_directory(installer.minecraft_directory, folder, plan.name, profiles)
                return folder
            except FileExistsError:
                continue
        raise ValueError("Choose a different instance folder name for this pack.")

    def _prepare_pack(self, *, project: dict | None = None, version: dict | None = None, path: Path | None = None) -> None:
        def operation(progress):
            installer = self._installer()
            plan = None
            try:
                if path is not None:
                    plan = installer.prepare_local(path, progress=progress, cancel_event=progress.cancel_event)
                else:
                    identifier = project.get("project_id") or project["id"]
                    full = self.client.modpack_project(identifier)
                    versions = self.client.modpack_versions(identifier) if version is None else [version]
                    selected = version or next((entry for entry in versions if entry.get("version_type") == "release"), versions[0] if versions else None)
                    if selected is None:
                        raise ValueError("This modpack has no supported client release.")
                    selected = self.client.modpack_version(selected["id"])
                    provider = "curseforge" if identifier.startswith("cf:") else "modrinth"
                    file = installer.archive_file(selected, provider)
                    if file.get("manual_required") and not self.client.is_manual_file_ready(file):
                        progress.check_cancelled()
                        return {"archive": True, "project": full, "versions": [selected]}
                    plan = installer.prepare_remote(full, selected, progress=progress, cancel_event=progress.cancel_event)
                folder = self._suggest_folder(installer, plan)
                ids = manual_ready_ids(self.client, plan.manual_files())
                self._pack_plan = plan
                progress.check_cancelled()
                if self._closing:
                    raise OperationCancelled("Modpack preparation canceled.")
                return {"plan": plan, "installer": installer, "folder": folder, "ready_ids": ids}
            except BaseException:
                installer.discard(plan)
                if self._pack_plan is plan:
                    self._pack_plan = None
                raise

        def ready(result: dict) -> None:
            if result.get("archive"):
                if not self._active:
                    return
                review = ContentInstallReview(result["project"], None, result["versions"], self.client, self.runner, self, archive=True)

                def selected(version: dict) -> None:
                    self._review = None
                    self._prepare_pack(project=result["project"], version=version)

                review.install_requested.connect(selected)
                self._show_review(review)
                return
            plan, installer = result["plan"], result["installer"]
            self._pack_plan = plan
            if not self._active:
                self._discard_plan(installer, plan)
                return
            review = PackInstallReview(plan, installer, self.runner, self.images, self,
                                       folder_name=result["folder"], ready_ids=result["ready_ids"])

            def install(options: dict) -> None:
                self._review = None

                def operation(progress):
                    try:
                        return installer.install(plan, **options, progress=progress, cancel_event=progress.cancel_event,
                                                 can_commit=lambda: self._commit_guard(progress))
                    finally:
                        installer.discard(plan)

                def installed(profile: dict) -> None:
                    self._pack_plan = None
                    self._profiles.append(profile)
                    self.close_details()
                    self.set_view("installed")
                    self._changed("Installed " + profile.get("name", "modpack") + ".")

                self._execute(operation, "Installing " + plan.name + "…", installed)

            review.install_requested.connect(install)
            self._show_review(review, on_cancel=lambda: self._discard_plan(installer, plan))

        self._execute(operation, "Reading modpack…", ready, phase="preparing")

    def _discard_plan(self, installer: PackInstaller, plan: PackPlan) -> None:
        self._pack_plan = None
        if not self._closing:
            self.runner.submit(lambda: installer.discard(plan), lambda result: None, lambda error: self._notify(str(error)))

    def _configure_curseforge(self) -> None:
        if self._busy or self._review:
            return
        dialog = ReviewDialog("CurseForge setup", self.runner, self, action="Save key")
        note = text_label("Use an API key registered for your launcher. Wisc stores it in the system credential vault when available.", theme.FONT_BODY)
        note.setWordWrap(True)
        dialog.body.addWidget(note)
        field = GlassLineEdit()
        field.setEchoMode(GlassLineEdit.EchoMode.Password)
        field.setPlaceholderText("Launcher API key")
        field.setAccessibleName("CurseForge launcher API key")
        field.setFixedHeight(48)
        dialog.body.addWidget(field)
        get_key = GlassButton("Get an API key")
        get_key.clicked.connect(lambda: self._open_link("https://console.curseforge.com/"))
        dialog.body.addWidget(get_key)
        clear = GlassButton("Clear key")
        dialog.body.addWidget(clear)
        dialog.finished.connect(lambda result: field.clear())

        def saved(persisted: bool) -> None:
            dialog.accept()
            self._notify("CurseForge key saved securely." if persisted else "CurseForge key set for this session.")
            self.refresh()

        def save() -> None:
            value = field.text()
            field.clear()
            dialog.run(lambda: self.client.curseforge.set_api_key(value), saved)

        def removed(result) -> None:
            dialog.accept()
            self._notify("CurseForge key cleared.")
            self.refresh()

        dialog.confirm.clicked.disconnect()
        dialog.confirm.clicked.connect(save)
        clear.clicked.connect(lambda: dialog.run(self.client.curseforge.clear_api_key, removed))
        self._show_review(dialog)

    def shutdown(self) -> None:
        if self._closing:
            return
        pending_plan, installer, phase = self._pack_plan, self._pack_installer, self._phase
        self._closing = True
        if self._progress:
            self._progress.cancel()
            self._progress.finish()
        if self._review:
            self._review.reject()
        if pending_plan and installer and phase != "installing":
            from threading import Thread
            Thread(target=installer.discard, args=(pending_plan,),
                   name="Wisc pack cleanup", daemon=True).start()
            self._pack_plan = None
        self._invalidate_reads()
        for task in self._read_tasks:
            task.close()
        self.loading_changed.emit(False)
        self.progress_changed.emit("", 0, None, False)
        self._managers.clear()
        self._content_managers.clear()
        self.images.set_visible(False)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._active = True
        self.images.set_visible(True)
        if not self._busy:
            self._reload_profiles()
        self._render()

    def hideEvent(self, event) -> None:
        self._save_view_state()
        self._active = False
        self._invalidate_reads()
        self.images.set_visible(False)
        if self._phase == "preparing" and self._progress:
            self._progress.cancel()
        if self._review:
            self._review.reject()
        self.loading_changed.emit(False)
        super().hideEvent(event)
