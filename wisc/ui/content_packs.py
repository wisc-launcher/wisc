"""Profile-scoped shader and texture pack discovery and ZIP downloads."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable

import flet as ft

from wisc.mods.content import CONTENT_FOLDERS, ContentPackManager, LocalContentPack
from wisc.mods.manager import primary_content_file
from wisc.ui import theme
from wisc.ui.controls import (AcrylicSelector, launcher_button, launcher_icon_button, launcher_tab,
                              select_tab, search_input, rounded_artwork, format_size, format_downloads, card_surface)
from wisc.ui.mod_details import open_link
from wisc.ui.mod_list import ModList
from wisc.ui.modpacks import CONTENT_OPTIONS, PROVIDER_OPTIONS, SORT_OPTIONS, PackDetailsPage
from wisc.ui.motion import StaggeredReveal
from wisc.ui.profiles import profile_list_surface
from wisc.ui.progress import track_progress


CONTENT_LABELS = {"shader": "Shaders", "resourcepack": "Texture Packs"}


def _text(value: str, size: int = 13, *, emphasis: bool = False, **kwargs) -> ft.Text:
    kwargs.setdefault("color", theme.TEXT if emphasis else theme.MUTED)
    return ft.Text(value, size=size, weight=ft.FontWeight.W_600 if emphasis else ft.FontWeight.NORMAL, **kwargs)


class ContentPacksPage(ft.Container):
    PAGE_SIZE = 20

    def __init__(self, page: ft.Page, *, client, get_profiles: Callable, selected_profile: Callable,
                 game_directory: Callable, is_running: Callable, notify: Callable, dialogs: Callable,
                 open_folder: Callable, on_changed: Callable, on_content_change: Callable,
                 configure_curseforge: Callable, other_busy: Callable, progress=None, entrance=None):
        self._page = page
        self.client = client
        self._get_profiles = get_profiles
        self._selected_profile = selected_profile
        self._game_directory = game_directory
        self._is_running = is_running
        self._show_notification = notify
        self._dialogs = dialogs
        self._open_folder = open_folder
        self._on_changed = on_changed
        self._other_busy = other_busy
        self._progress = progress
        self._entrance = entrance
        self.kind = "shader"
        self.profile = None
        self.manager = None
        self.provider = "modrinth"
        self.view = "browse"
        self.hits = []
        self.local_packs = []
        self.total_hits = 0
        self.search_offset = 0
        self.busy = False
        self.loading = False
        self.error = ""
        self._active = False
        self._generation = 0
        self._pending_load = None
        self._load_activity = None
        self._review_open = False
        self._installing = False
        self._operation_id = 0
        self._states = {}
        self._details_open = False
        self._detail_local = None
        self._detail_filename = ""
        self._queries = {"browse": "", "installed": ""}
        self._scrolls = {"browse": 0.0, "installed": 0.0}
        self.heading = _text("Shaders", 24, emphasis=True)
        self.content_selector = AcrylicSelector(CONTENT_OPTIONS, "shader", on_content_change, width=160, tooltip="Content type")
        self.profile_selector = AcrylicSelector([], None, self._profile_changed, width=280, tooltip="Select Profile")
        self.header = ft.Row([self.heading, self.content_selector, ft.Container(expand=True), self.profile_selector], spacing=16)
        self.browse_tab = launcher_tab("Discover", lambda e: self.set_view("browse"))
        self.installed_tab = launcher_tab("Installed", lambda e: self.set_view("installed"))
        self.folder_button = launcher_button("Open folder", self._open_content_folder)
        self.attribution = _text("Powered by Modrinth", 11)
        self.tabs = ft.Row([self.browse_tab, self.installed_tab, ft.Container(expand=True), self.folder_button, self.attribution], spacing=8)
        self.search = search_input("Search shaders", on_change=self._search_changed, on_submit=self._search_submitted)
        self.provider_selector = AcrylicSelector(PROVIDER_OPTIONS, "modrinth", self._provider_changed, width=160, tooltip="Content provider")
        self.sort = AcrylicSelector(SORT_OPTIONS, "downloads", self._sort_changed, width=212, prefix="Sort:")
        self.key_button = launcher_icon_button(icon=ft.Icons.KEY_SHARP, tooltip="Set up CurseForge API key", on_click=configure_curseforge)
        self.refresh_button = launcher_icon_button(icon=ft.Icons.REFRESH_SHARP, tooltip="Refresh packs", on_click=self._refresh_requested)
        self.toolbar = ft.Row([self.search, self.provider_selector, self.sort, self.key_button, self.refresh_button], spacing=12)
        self.note = _text("Shaders need Iris or OptiFine. Enable downloaded shaders in Minecraft's video settings.", 12)
        self.status = _text("", 12, expand=True)
        self.previous = launcher_icon_button(icon=ft.Icons.CHEVRON_LEFT_SHARP, tooltip="Previous page", on_click=lambda e: self._paginate(-1))
        self.next = launcher_icon_button(icon=ft.Icons.CHEVRON_RIGHT_SHARP, tooltip="Next page", on_click=lambda e: self._paginate(1))
        self.page_label = _text("", 12)
        self.pagination = ft.Row([self.previous, self.page_label, self.next], spacing=6, tight=True)
        self.status_row = ft.Row([self.status, self.pagination], spacing=12)
        self.list_view = ModList(lambda: None)
        self.list_body = ft.Container(expand=True, content=self.list_view)
        self.list_host = profile_list_surface(self.list_body)
        self.file_picker = ft.FilePicker()
        page.services.append(self.file_picker)
        self.listing = ft.Container(expand=True, content=ft.Column([
            self.header, self.tabs, self.toolbar, self.note, self.status_row, self.list_host,
        ], expand=True, spacing=12, horizontal_alignment=ft.CrossAxisAlignment.STRETCH))
        self.details_page = PackDetailsPage(
            page, client=client, content_kind=self.kind, get_profile=lambda: self.profile,
            on_back=self.close_details,
            on_install=lambda project, version: self._page.run_task(self._prepare_install, project, version),
            can_install=lambda: bool(self.manager) and not self.busy and not self._other_busy() and not self._is_running(),
            on_remove=lambda e: self._confirm_remove(self._detail_local) if self._detail_local else None,
            progress=progress,
        )
        self.details_host = ft.Container(expand=True, visible=False, content=self.details_page)
        super().__init__(expand=True, visible=False, content=ft.Stack([self.listing, self.details_host], expand=True))
        self.reveal = StaggeredReveal(page, self.list_host)

    @property
    def reveal_controls(self) -> list[ft.Control]:
        return self.details_page.reveal_controls if self._details_open else [self.header, self.tabs, self.toolbar, self.note, self.list_host]

    def _update(self) -> None:
        if self._active:
            try:
                self.update()
            except RuntimeError:
                pass

    def enter(self, kind: str, *, defer_load: bool = False) -> None:
        if kind != self.kind and self._details_open:
            self.details_page.leave()
            self._details_open = False
            self.listing.visible = True
            self.details_host.visible = False
        self.details_page.content_kind = kind
        self.kind = kind
        self._active = True
        self.list_view.reset_viewport()
        saved = self._states.get(kind, {})
        self.view = saved.get("view", "browse")
        self.provider = saved.get("provider", "modrinth")
        self.search_offset = saved.get("offset", 0)
        self._queries = saved.get("queries", {"browse": "", "installed": ""}).copy()
        self._scrolls = saved.get("scrolls", {"browse": 0.0, "installed": 0.0}).copy()
        self.search.value = self._queries[self.view]
        self.provider_selector.refresh_options(PROVIDER_OPTIONS, self.provider)
        self.sort.refresh_options(SORT_OPTIONS, saved.get("sort", "downloads"))
        self.content_selector.refresh_options(CONTENT_OPTIONS, kind)
        profiles = self._get_profiles()
        desired = saved.get("profile_id") or (self._selected_profile() or {}).get("id")
        self.profile = next((p for p in profiles if p.get("id") == desired), profiles[0] if profiles else None)
        self.profile_selector.refresh_options([(p["id"], p["name"]) for p in profiles], (self.profile or {}).get("id"))
        self.hits = []
        self.total_hits = 0
        self.refresh(defer_load=defer_load)
        if self._details_open:
            self.details_page.resume()

    def leave(self) -> None:
        self._scrolls[self.view] = self.list_view._scroll_pixels
        self._states[self.kind] = {"view": self.view, "provider": self.provider, "offset": self.search_offset,
                                  "queries": self._queries.copy(), "scrolls": self._scrolls.copy(),
                                  "sort": self.sort.value, "profile_id": (self.profile or {}).get("id")}
        self._active = False
        self._generation += 1
        self._pending_load = None
        self._finish_load()
        self.reveal.finish(update=False)
        self.details_page.leave()
        if self._review_open:
            self._close_review()
        elif not self._installing:
            self._operation_id += 1
            self.busy = False

    def _finish_load(self) -> None:
        self.loading = False
        if self._load_activity:
            self._load_activity.finish()
            self._load_activity = None

    def refresh(self, *, defer_load: bool = False) -> None:
        if self.busy:
            return
        self._generation += 1
        self._finish_load()
        self._pending_load = None
        self.error = ""
        self.manager = None
        self.local_packs = []
        if self.profile:
            try:
                self.manager = ContentPackManager(self._game_directory(self.profile), self.kind)
            except (ValueError, OSError) as error:
                self.error = str(error)
        if self.manager:
            self.loading = True
            self._pending_load = (self._generation, self.manager, self.profile.copy(), self.kind, self.view,
                                  self.provider, self.search.value or "", self.sort.value, self.search_offset)
        self._render()
        self._update()
        if not defer_load:
            self.start_loading()

    def start_loading(self) -> None:
        pending, self._pending_load = self._pending_load, None
        if pending is not None:
            activity = track_progress(self._progress, f"Loading {CONTENT_LABELS[self.kind].lower()}...", priority=40)
            self._load_activity = activity
            self._page.run_task(self._load, *pending, activity)

    async def _load(self, generation, manager, profile, kind, view, provider, query, sort, offset, activity) -> None:
        try:
            local = await asyncio.to_thread(manager.scan)
            data = await asyncio.to_thread(self.client.search_content, query, profile["minecraft_version"], kind,
                                           provider=provider, index=sort, offset=offset, limit=self.PAGE_SIZE) if view == "browse" else None
            if self._entrance:
                await self._entrance.wait_until_finished()
            if generation != self._generation or not self._active:
                return
            self.local_packs = local
            if data is not None:
                self.hits = data["hits"]
                self.total_hits = int(data.get("total_hits", len(self.hits)))
            self.loading = False
            self._render()
            self._update()
            if self._scrolls[self.view]:
                self._page.run_task(self._restore_scroll, generation)
        except Exception as error:
            if generation == self._generation and self._active:
                self.loading = False
                self.error = str(error)
                self._render()
                self._update()
        finally:
            activity.finish()
            if self._load_activity is activity:
                self._load_activity = None

    async def _restore_scroll(self, generation: int) -> None:
        await asyncio.sleep(0.06)
        if generation == self._generation and self._active and not self._details_open:
            try:
                await self.list_view.scroll_to(offset=self._scrolls[self.view], duration=0)
            except RuntimeError:
                pass

    def set_view(self, view: str) -> None:
        if view == self.view or self.busy:
            return
        self._queries[self.view] = self.search.value or ""
        self._scrolls[self.view] = self.list_view._scroll_pixels
        self.view = view
        self.search.value = self._queries[view]
        self.refresh()

    def _profile_changed(self, e) -> None:
        if self.busy:
            return
        self.profile = next((p for p in self._get_profiles() if p["id"] == self.profile_selector.value), None)
        self.hits = []
        self.total_hits = 0
        self.search_offset = 0
        self._scrolls = {"browse": 0.0, "installed": 0.0}
        self.refresh()

    def _provider_changed(self, e) -> None:
        if not self.busy:
            self.provider = self.provider_selector.value
            self.hits = []
            self.total_hits = 0
            self.search_offset = 0
            self._scrolls["browse"] = 0
            self.refresh()

    def _sort_changed(self, e) -> None:
        if not self.busy:
            self.search_offset = 0
            self._scrolls["browse"] = 0
            self.refresh()

    def _search_changed(self, e) -> None:
        if self.busy:
            return
        self._queries[self.view] = self.search.value or ""
        self._scrolls[self.view] = 0
        if self.view == "installed":
            self._render()
            self._update()
        else:
            self._generation += 1
            self._finish_load()
            self._page.run_task(self._debounced_search, self._generation)

    async def _debounced_search(self, generation: int) -> None:
        await asyncio.sleep(0.35)
        if generation == self._generation and self._active and not self.busy:
            self.search_offset = 0
            self.refresh()

    def _search_submitted(self, e) -> None:
        if not self.busy:
            self.search_offset = 0
            self.refresh()

    def _paginate(self, direction: int) -> None:
        if not self.loading and not self.busy:
            self.search_offset = max(0, self.search_offset + direction * self.PAGE_SIZE)
            self._scrolls["browse"] = 0
            self.refresh()

    def _refresh_requested(self, e) -> None:
        if not self.busy:
            self.client.clear_cache()
            self.refresh()

    def _open_content_folder(self, e) -> None:
        if self.manager and not self.busy:
            try:
                self.manager._check_directory()
                self.manager.directory.mkdir(exist_ok=True)
                self._open_folder(self.manager.directory)
            except (ValueError, OSError) as error:
                self._show_notification(str(error), "error")

    def _render(self) -> None:
        self._sync_details()
        label = CONTENT_LABELS[self.kind]
        browse = self.view == "browse"
        locked = self.busy or self._other_busy()
        self.heading.value = label
        self.content_selector.disabled = self.profile_selector.disabled = locked
        self.browse_tab.disabled = self.installed_tab.disabled = locked or not self.profile
        select_tab(self.browse_tab, browse)
        select_tab(self.installed_tab, not browse)
        self.installed_tab.content.value = f"Installed · {len(self.local_packs)}" if self.local_packs else "Installed"
        self.provider_selector.visible = self.sort.visible = browse
        self.key_button.visible = browse and self.provider == "curseforge"
        self.search.hint_text = f"Search {label.lower()}" if browse else f"Search installed {label.lower()}"
        for control in (self.search, self.provider_selector, self.sort, self.key_button):
            control.disabled = locked or not self.profile
        self.folder_button.disabled = locked or not self.manager
        self.refresh_button.disabled = locked or self.loading
        self.attribution.visible = browse
        self.attribution.value = "Powered by CurseForge" if self.provider == "curseforge" else "Powered by Modrinth"
        self.note.value = ("Shaders need Iris or OptiFine. Enable downloaded shaders in Minecraft's video settings." if self.kind == "shader"
                           else "Enable downloaded texture packs in Minecraft's Resource Packs menu.")
        version = (self.profile or {}).get("minecraft_version", "")
        self.status.value = ("Downloading pack..." if self._installing else "Loading packs..." if self.loading
                             else f"Minecraft {version} · {self.total_hits:,} results" if browse else f"{len(self.local_packs)} installed packs")
        self.pagination.visible = browse and self.total_hits > self.PAGE_SIZE and not self.error
        self.previous.disabled = locked or self.loading or self.search_offset == 0
        self.next.disabled = locked or self.loading or self.search_offset + self.PAGE_SIZE >= self.total_hits
        self.page_label.value = f"{self.search_offset // self.PAGE_SIZE + 1} / {max(1, (self.total_hits + self.PAGE_SIZE - 1) // self.PAGE_SIZE)}"
        if not self.profile:
            self._empty("Select a profile", "Choose a profile to download shaders or texture packs for its Minecraft version.")
        elif self.error:
            self._empty("Could not load packs", self.error, launcher_button("Retry", self._refresh_requested))
        else:
            query = (self.search.value or "").casefold()
            items = self.hits if browse else [p for p in self.local_packs if query in (p.title + " " + p.filename).casefold()]
            self.list_body.content = self.list_view
            self.list_view.set_items(items, self._row, offset=self._scrolls[self.view])
            if not items:
                self._empty("Finding packs" if self.loading else "No packs found", "Try another search or provider." if browse
                            else f"Download packs from Discover or place ZIPs in {CONTENT_FOLDERS[self.kind]}.")

    def _empty(self, title: str, description: str, action=None) -> None:
        self.list_view.set_items([], self._row)
        self.list_body.content = ft.Container(alignment=ft.Alignment.CENTER, padding=24, content=ft.Column([
            _text(title, 20, emphasis=True), _text(description), *([action] if action else []),
        ], tight=True, spacing=12, horizontal_alignment=ft.CrossAxisAlignment.CENTER))

    def _row(self, item) -> ft.Container:
        installed = isinstance(item, LocalContentPack)
        title = item.title if installed else item.get("title", "Pack")
        icon_url = None if installed else item.get("icon_url")
        fallback = ft.Icon(ft.Icons.LANDSCAPE_OUTLINED if self.kind == "shader" else ft.Icons.TEXTURE, size=32, color=theme.MUTED)
        icon = ft.Image(src=icon_url, width=48, height=48, fit=ft.BoxFit.CONTAIN, error_content=fallback) if icon_url else fallback
        description = item.filename if installed else item.get("description", "")
        detail = f"{item.version or 'Local pack'} · {format_size(item.size)}" if installed else f"{item.get('author', 'Unknown')} · {format_downloads(item.get('downloads', 0))} downloads"
        ready = not installed and any(p.project_id == item.get("project_id") for p in self.local_packs)
        action = launcher_icon_button(
            icon=ft.Icons.DELETE_OUTLINE_SHARP if installed else ft.Icons.CHECK_SHARP if ready else ft.Icons.DOWNLOAD_ROUNDED,
            tooltip="Remove pack" if installed else "Installed" if ready else f"Download {title}",
            primary=not installed and not ready,
            disabled=self.busy or self._other_busy() or self._is_running() or bool(ready), width=44, height=44,
            on_click=(lambda e: self._confirm_remove(item)) if installed else (lambda e: self._page.run_task(self._prepare_install, item)),
        )
        details = ft.Column([_text(title, 15, emphasis=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                             _text(description, 13, color=theme.TEXT_SECONDARY, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                             _text(detail, 12, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)], expand=True, spacing=4)
        identifier = item.filename if installed else item.get("project_id")
        return card_surface(
            ft.Row([ft.GestureDetector(content=ft.Row([rounded_artwork(icon, size=48), details], spacing=16),
                                      expand=True, mouse_cursor=ft.MouseCursor.CLICK,
                                      on_tap=lambda e: self.open_details(item)), action], spacing=12,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            glow_color=theme.GLOW, horizontal_padding=16,
            data=(self.kind, self.view, identifier), key=ft.ValueKey(f"content-{self.kind}-{self.view}-{identifier}"),
        )

    def open_details(self, item: dict | LocalContentPack) -> None:
        if self.busy:
            return
        self._scrolls[self.view] = self.list_view._scroll_pixels
        self.reveal.finish(update=False)
        self._detail_local = item if isinstance(item, LocalContentPack) else None
        self._detail_filename = self._detail_local.filename if self._detail_local else ""
        if self._detail_local:
            item = {"project_id": item.project_id, "title": item.title,
                    "description": f"{item.filename} · {format_size(item.size)}",
                    "body": f"Installed in `{CONTENT_FOLDERS[self.kind]}/{item.filename}`.\n\n"
                            f"{self.note.value}", "project_type": self.kind}
        self._details_open = True
        self.listing.visible = False
        self.details_host.visible = True
        self.details_page.open(item)
        self._sync_details()
        self._update()

    def _sync_details(self) -> None:
        if not self._details_open:
            return
        project_id = self.details_page.project.get("project_id")
        if self._detail_filename:
            self._detail_local = next((pack for pack in self.local_packs if pack.filename == self._detail_filename), None)
        else:
            self._detail_local = next((pack for pack in self.local_packs if project_id and pack.project_id == project_id), None)
        self.details_page.installed = self._detail_local is not None
        self.details_page.remove_button.visible = self._detail_local is not None
        self.details_page.render()

    def close_details(self) -> None:
        self.details_page.leave()
        self._details_open = False
        self.details_host.visible = False
        self.listing.visible = True
        self._render()
        self._update()
        self._page.run_task(self._restore_scroll, self._generation)

    def _can_operate(self) -> bool:
        if self.busy or self._other_busy() or self._is_running() or not self.manager:
            self._show_notification("Select a profile and close Minecraft before changing packs.", "warning")
            return False
        return True

    async def _prepare_install(self, project: dict, requested_version: dict | None = None) -> None:
        if not self._can_operate():
            return
        generation, manager, profile, kind = self._generation, self.manager, self.profile.copy(), self.kind
        self._operation_id += 1
        operation_id = self._operation_id
        self.busy = True
        self._render()
        self._update()
        try:
            with track_progress(self._progress, "Finding compatible pack versions...", priority=60):
                versions = await asyncio.to_thread(self.client.content_versions, project["project_id"], profile["minecraft_version"], kind)
            if not self._active or generation != self._generation:
                if operation_id == self._operation_id:
                    self.busy = False
                return
            if not versions:
                raise ValueError("No compatible ZIP is available for this Minecraft version.")
            default = next((v for v in versions if v.get("version_type") == "release"), versions[0])
            if requested_version:
                default = next((v for v in versions if v["id"] == requested_version.get("id")), None)
                if default is None:
                    raise ValueError("This pack version is no longer compatible with the selected profile.")
            selector = AcrylicSelector([(v["id"], f"{v.get('version_number') or v.get('name')} · {v.get('version_type', 'release')}") for v in versions],
                                       default["id"], lambda e: update_version(), width=440, tooltip="Pack version")
            detail = _text("", 12)
            manual_button = launcher_button("Open official download", lambda e: None, visible=False)
            select_manual = launcher_button("Select downloaded ZIP", lambda e: None, visible=False)
            download_button = launcher_button("Download", lambda e: None, primary=True)

            def selected():
                return next(v for v in versions if v["id"] == selector.value)

            def update_version():
                file = primary_content_file(selected())
                manual = bool(file.get("manual_required"))
                ready = not manual or self.client.is_manual_file_ready(file)
                detail.value = f"{file['filename']} · {format_size(file.get('size', 0))}"
                manual_button.visible = select_manual.visible = manual
                manual_button.on_click = lambda e: open_link(file.get("manual_url", ""))
                download_button.disabled = not ready
                self._page.update()

            async def pick_manual(e):
                files = await self.file_picker.pick_files(dialog_title="Select the official pack ZIP", allow_multiple=False,
                                                         file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["zip"])
                try:
                    if files:
                        if not files[0].path:
                            raise ValueError("Selecting a downloaded ZIP requires the desktop launcher.")
                        await asyncio.to_thread(self.client.curseforge.register_manual_files, [primary_content_file(selected())], [Path(files[0].path)])
                        update_version()
                except Exception as error:
                    self._show_notification(str(error), "error")

            async def download(e):
                version = selected()
                self._review_open = False
                self._dialogs().close()
                self._installing = True
                self._render()
                self._update()
                try:
                    with track_progress(self._progress, f"Downloading {project.get('title', 'pack')}...", priority=100) as activity:
                        await asyncio.to_thread(manager.install, self.client, project, version, profile["minecraft_version"], activity,
                                                can_commit=lambda: not self._is_running())
                    self._show_notification(f"Installed {project.get('title', 'pack')} in {profile['name']}.", "success", CONTENT_LABELS[kind])
                    self._on_changed()
                except Exception as error:
                    self._show_notification(str(error), "error", "Could not install pack")
                finally:
                    self.busy = self._installing = False
                    if self._active:
                        self.refresh()

            select_manual.on_click = pick_manual
            download_button.on_click = download
            self._review_open = True
            self._dialogs().show(ft.Column([
                _text(project.get("description", ""), 13), _text(f"{profile['name']} · Minecraft {profile['minecraft_version']}", 13, emphasis=True),
                selector, detail, _text(f"Installs in {CONTENT_FOLDERS[kind]}. {self.note.value}", 12), manual_button, select_manual,
            ], spacing=14), title=_text(project.get("title", "Download pack"), 22, emphasis=True),
                actions=[launcher_button("Cancel", self._close_review), download_button], on_cancel=self._close_review, width=540, height=470)
            update_version()
        except Exception as error:
            if operation_id != self._operation_id:
                return
            self.busy = False
            self._show_notification(str(error), "error", "Could not load pack")
            self._render()
            self._update()

    def _close_review(self, e=None) -> None:
        self._review_open = False
        self.busy = False
        self._dialogs().close()
        self._render()
        self._update()

    def _confirm_remove(self, item: LocalContentPack) -> None:
        if not self._can_operate():
            return
        manager = self.manager

        def close(e=None):
            self._dialogs().close()

        async def remove(e):
            close()
            if not self._can_operate():
                return
            self.busy = True
            self._render()
            self._update()
            try:
                with track_progress(self._progress, "Removing pack...", priority=80):
                    await asyncio.to_thread(manager.remove, item, can_commit=lambda: not self._is_running())
                self._show_notification(f"Removed {item.title}.", "success")
                if self._details_open and self._detail_local and self._detail_local.filename == item.filename:
                    self.close_details()
                self._on_changed()
            except Exception as error:
                self._show_notification(str(error), "error")
            finally:
                self.busy = False
                self.refresh()

        self._dialogs().show(_text(f"Remove {item.title} from {self.profile['name']}?"), title=_text("Remove pack", 22, emphasis=True),
                             actions=[launcher_button("Cancel", close), launcher_button("Remove", remove, primary=True)],
                             on_cancel=close, width=500, height=280)
