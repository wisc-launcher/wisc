"""Native, nonblocking reviews of existing content installation transactions."""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QDialog, QFileDialog, QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from wisc.mods.manager import InstallPlan, ModManager, ModUpdate, primary_content_file, primary_file
from wisc.core.credentials import redact_credentials
from wisc.mods.modpacks import PackInstaller, PackPlan
from wisc.ui import theme as theme
from wisc.mods.platform import ModPlatformClient
from wisc.ui.components import GlassButton, GlassLineEdit, LauncherComboBox, text_label
from wisc.ui.content import ContentAction, ContentImages, ContentItem, ContentList, format_size
from wisc.ui.tasks import LatestServiceTask, ServiceRunner


def manual_ready_ids(client: ModPlatformClient, files: list[dict]) -> set[str]:
    """Checksum checks belong on service workers, including readiness checks."""
    return {str(file.get("id", "")) for file in files if client.is_manual_file_ready(file)}


class ManualFiles(QWidget):
    files_selected = pyqtSignal(object)
    link_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None, *, extensions: str = "JAR files (*.jar)"):
        super().__init__(parent)
        self.extensions = extensions
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)

    def display(self, files: list[dict], ready: set[str]) -> None:
        while self._layout.count():
            widget = self._layout.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        self.setVisible(bool(files))
        if not files:
            return
        self._layout.addWidget(text_label("Manual CurseForge downloads", theme.FONT_ROW_TITLE, bold=True))
        hint = text_label("Download the exact official files, then select them here for verification.", theme.FONT_DETAIL, muted=True)
        hint.setWordWrap(True)
        self._layout.addWidget(hint)
        for file in files:
            button = GlassButton(("✓  " if str(file.get("id", "")) in ready else "↓  ") + str(file.get("filename", "Download")))
            button.setToolTip(str(file.get("manual_url", "")))
            button.clicked.connect(lambda checked=False, url=str(file.get("manual_url", "")): self.link_requested.emit(url))
            self._layout.addWidget(button)
        select = GlassButton("Select downloaded files")
        select.clicked.connect(self._select)
        self._layout.addWidget(select)

    def _select(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Select official CurseForge downloads", "", self.extensions)
        if files:
            self.files_selected.emit([Path(file) for file in files])


class ReviewDialog(QDialog):
    link_requested = pyqtSignal(str)

    def __init__(self, title: str, runner: ServiceRunner, parent: QWidget, *, action: str = "Install"):
        super().__init__(parent.window())
        self.setPalette(parent.window().palette())
        self.setWindowTitle(title)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setObjectName("contentReview")
        self.setMinimumSize(520, 280)
        self.resize(600, 380)
        self._runner = runner
        self._task = LatestServiceTask(runner)
        self._closed = False
        self._busy = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)
        layout.addWidget(text_label(title, theme.FONT_DIALOG_TITLE, bold=True))
        scroll = QScrollArea()
        scroll.setObjectName("contentScroll")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.viewport().setAutoFillBackground(False)
        self.content = QWidget()
        self.content.setObjectName("contentScrollBody")
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(0, 0, 8, 0)
        self.body.setSpacing(12)
        scroll.setWidget(self.content)
        layout.addWidget(scroll, 1)
        self.error = text_label("", theme.FONT_DETAIL)
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        layout.addWidget(self.error)
        footer = QHBoxLayout()
        footer.addStretch()
        cancel = GlassButton("Cancel")
        cancel.setFixedHeight(theme.BUTTON_HEIGHT)
        cancel.clicked.connect(self.reject)
        self.confirm = GlassButton(action, accented=True)
        self.confirm.setFixedHeight(theme.BUTTON_HEIGHT)
        self.confirm.clicked.connect(self._accept)
        footer.addWidget(cancel)
        footer.addWidget(self.confirm)
        layout.addLayout(footer)
        self.finished.connect(self._finished)

    def _finished(self, result: int) -> None:
        self._closed = True
        self._task.close()

    def _accept(self) -> None:
        self.accept()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.content.setEnabled(not busy)
        self.confirm.setEnabled(not busy)

    def set_error(self, message: str) -> None:
        self.error.setText(redact_credentials(message))
        self.error.setVisible(bool(message))

    def run(self, operation: Callable, success: Callable) -> None:
        if self._closed or self._busy:
            return
        self.set_busy(True)
        self.set_error("")

        def ready(value) -> None:
            self.set_busy(False)
            success(value)

        def failed(error: Exception) -> None:
            self.set_busy(False)
            self.set_error(str(error))
            self.refresh()

        self._task.submit(operation, ready, failed)

    def refresh(self) -> None:
        """Update the confirmation's state after background validation."""


class ModInstallReview(ReviewDialog):
    install_requested = pyqtSignal(object)

    def __init__(self, project: dict, profile: dict, plan: InstallPlan, manager: ModManager,
                 client: ModPlatformClient, runner: ServiceRunner, images: ContentImages,
                 parent: QWidget, *, ready_ids: set[str], updates: tuple[ModUpdate, ...] = ()):
        title = f"Update {len(updates)} mods" if updates else "Install " + project.get("title", "mod")
        super().__init__(title, runner, parent, action="Update all" if updates else "Install")
        self.project, self.profile, self.plan = project, profile, plan
        self.manager, self.client, self.updates = manager, client, updates
        self.selected: set[str] = set()
        self._original = plan
        self._plans: OrderedDict[frozenset, tuple[InstallPlan, set[str]]] = OrderedDict()
        self._plans[frozenset()] = (plan, ready_ids)
        self._ready_ids = ready_ids
        self._manual_failed = False
        self.body.addWidget(text_label(f"{profile.get('name', 'Instance')} · Minecraft {profile['minecraft_version']} / {profile['loader']}", theme.FONT_BODY))
        self.summary = text_label("", theme.FONT_LABEL, bold=True)
        self.summary.setWordWrap(True)
        self.body.addWidget(self.summary)
        self.dependencies = ContentList(images)
        palette = parent.window().palette()
        self.dependencies.set_accent(palette.highlight().color(), palette.highlightedText().color())
        self.dependencies.setAccessibleName("Installation dependencies; Space includes an optional dependency")
        self.dependencies.action_requested.connect(self._optional)
        self.body.addWidget(self.dependencies)
        self.notes = text_label("", theme.FONT_DETAIL, muted=True)
        self.notes.setWordWrap(True)
        self.notes.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.body.addWidget(self.notes)
        self.manual = ManualFiles()
        self.manual.link_requested.connect(self.link_requested.emit)
        self.manual.files_selected.connect(self._manual_files)
        self.body.addWidget(self.manual)
        self.body.addStretch()
        self.refresh()

    def _manual_records(self) -> list[dict]:
        return [file for version in self.plan.versions if (file := primary_file(version)).get("manual_required")]

    def refresh(self) -> None:
        root = self.plan.root_version or (self.plan.versions[-1] if self.plan.versions else {})
        sizes = [primary_file(version).get("size") for version in self.plan.versions]
        total = sum(sizes) if all(isinstance(size, int) and size >= 0 for size in sizes) else None
        count = len(self.plan.versions)
        self.summary.setText(f"{root.get('version_number') or root.get('name', 'Selected versions')} · "
                             f"{count} {'download' if count == 1 else 'downloads'} · {format_size(total)}")
        rows = []
        for dependency in self.plan.dependencies:
            optional = not dependency.required and not dependency.installed
            status = "Provided by profile" if (dependency.version or {}).get("runtime") else "Bundled" if dependency.bundled else (
                "Installed" if dependency.installed else "Required" if dependency.required else "Optional"
            )
            checked = dependency.project_id in self.selected if optional else None
            rows.append(ContentItem(
                dependency.project_id, dependency.name,
                dependency.issue or (dependency.version or {}).get("version_number", ""), status,
                actions=(ContentAction("toggle", "Include" if optional else status,
                                       optional and not dependency.issue),),
                checked=checked, payload=dependency,
            ))
        self.dependencies.set_items(rows)
        self.dependencies.setVisible(bool(rows))
        self.dependencies.setFixedHeight(min(288, len(rows) * 96))
        notes = []
        if self.updates:
            targets = {version["project_id"]: version for version in self.plan.root_versions}
            notes.extend(f"{update.mod.name}: {update.mod.version} → "
                         f"{targets.get(update.mod.project_id, update.version).get('version_number', '')}"
                         for update in self.updates)
        if self.plan.replacements:
            notes.append("Replaces " + ", ".join(self.plan.replacements) + ". Previous files stay in launcher trash.")
        if self.plan.disabled_projects:
            notes.append("Disabled mods will stay disabled.")
        notes.extend(self.plan.warnings)
        self.notes.setText("\n\n".join(notes))
        self.notes.setVisible(bool(notes))
        manual = self._manual_records()
        self.manual.display(manual, self._ready_ids)
        self.confirm.setEnabled(not self._busy and not self._manual_failed
                                and all(str(file.get("id", "")) in self._ready_ids for file in manual))
        height = 320 + min(288, len(rows) * 96) + min(120, len(notes) * 26) + (140 if manual else 0)
        self.resize(self.width(), min(550, height))

    def _resolve(self, selection: set[str]) -> tuple[InstallPlan, set[str]]:
        roots = tuple(deepcopy(version) for version in self.plan.root_versions)
        for version in roots:
            version.pop("_metadata_warning", None)
            version.pop("_fabric_loader_metadata", None)
        updated = self.manager.plan_install(
            self.client, self.project["project_id"], self.profile["minecraft_version"], self.profile["loader"].lower(),
            selected_version=roots[0], selected_versions=roots if self.updates else (),
            loader_version=self.profile.get("loader_version", ""), optional_projects=tuple(sorted(selection)),
            version_id=self.profile.get("version_id", ""),
        )
        if updated.snapshot != self._original.snapshot or updated.runtime_snapshot != self._original.runtime_snapshot:
            raise ValueError("The instance or its runtime changed. Cancel and review the installation again.")
        files = [file for version in updated.versions if (file := primary_file(version)).get("manual_required")]
        return updated, manual_ready_ids(self.client, files)

    def _optional(self, item: ContentItem, action: str) -> None:
        if self._busy or self._closed or item.checked is None:
            return
        selection = self.selected ^ {item.key}
        key = frozenset(selection)
        if key in self._plans and not self._manual_failed:
            self.selected = selection
            self.plan, self._ready_ids = self._plans[key]
            self._plans.move_to_end(key)
            self.refresh()
            return

        def ready(result) -> None:
            self.selected = selection
            self.plan, self._ready_ids = result
            self._plans[key] = result
            while len(self._plans) > 16:
                self._plans.popitem(last=False)
            self._manual_failed = False
            self.refresh()

        self.run(lambda: self._resolve(selection), ready)

    def _manual_files(self, paths: list[Path]) -> None:
        if self._busy or self._closed:
            return
        plan = self.plan
        selection = self.selected.copy()
        self._manual_failed = True
        self._plans.clear()

        def operation():
            self.client.register_manual_files(plan, paths)
            return self._resolve(selection)

        def ready(result) -> None:
            self.plan, self._ready_ids = result
            self._plans[frozenset(selection)] = result
            self._manual_failed = False
            self.refresh()

        self.run(operation, ready)

    def _accept(self) -> None:
        if self.confirm.isEnabled() and not self._closed:
            self.install_requested.emit(self.plan)
            self.accept()


class ContentInstallReview(ReviewDialog):
    install_requested = pyqtSignal(object)

    def __init__(self, project: dict, profile: dict | None, versions: list[dict], client: ModPlatformClient,
                 runner: ServiceRunner, parent: QWidget, *, selected: dict | None = None, archive: bool = False,
                 ready_ids: set[str] | None = None):
        super().__init__(("Download pack archive" if archive else "Install ") + project.get("title", "pack"), runner, parent,
                         action="Continue" if archive else "Install")
        self.project, self.client, self.archive = project, client, archive
        self.versions = versions
        self._ready_ids = ready_ids or set()
        hint = text_label(f"{profile.get('name', 'Profile')} · Minecraft {profile.get('minecraft_version', '')}" if profile else
                          "This pack will create a separate instance with its own game and loader versions.", theme.FONT_BODY)
        hint.setWordWrap(True)
        self.body.addWidget(hint)
        self.selector = LauncherComboBox(height=48, min_width=440, max_width=520)
        self.selector.setAccessibleName("Choose pack version")
        for version in versions:
            self.selector.addItem(f"{version.get('version_number') or version.get('name', 'Version')} · {version.get('version_type', 'release')}", version["id"])
        if selected:
            self.selector.setCurrentIndex(max(0, self.selector.findData(selected["id"])))
        self.selector.currentIndexChanged.connect(self._version_changed)
        self.body.addWidget(self.selector)
        self.file_info = text_label("", theme.FONT_DETAIL, muted=True)
        self.file_info.setWordWrap(True)
        self.body.addWidget(self.file_info)
        self.manual = ManualFiles(extensions="Pack files (*.zip *.mrpack)")
        self.manual.link_requested.connect(self.link_requested.emit)
        self.manual.files_selected.connect(self._manual_files)
        self.body.addWidget(self.manual)
        self.body.addStretch()
        self.refresh()

    def selected(self) -> dict:
        return next(version for version in self.versions if version["id"] == self.selector.currentData())

    def _file(self) -> dict:
        version = self.selected()
        if self.archive:
            provider = "curseforge" if str(version.get("project_id", "")).startswith("cf:") else "modrinth"
            return PackInstaller.archive_file(version, provider)
        return primary_content_file(version)

    def refresh(self) -> None:
        file = self._file()
        manual = [file] if file.get("manual_required") else []
        self.file_info.setText(f"{file.get('filename', '')} · {format_size(file.get('size'))}")
        self.manual.display(manual, self._ready_ids)
        self.confirm.setEnabled(not self._busy and all(str(file.get("id", "")) in self._ready_ids for file in manual))

    def _version_changed(self) -> None:
        self.refresh()

    def _manual_files(self, paths: list[Path]) -> None:
        file = self._file()

        def operation():
            self.client.curseforge.register_manual_files([file], paths)
            return manual_ready_ids(self.client, [file])

        def ready(ids) -> None:
            self._ready_ids.update(ids)
            self.refresh()

        self.run(operation, ready)

    def _accept(self) -> None:
        if self.confirm.isEnabled() and not self._closed:
            self.install_requested.emit(self.selected())
            self.accept()


class PackInstallReview(ReviewDialog):
    install_requested = pyqtSignal(object)

    def __init__(self, plan: PackPlan, installer: PackInstaller, runner: ServiceRunner,
                 images: ContentImages, parent: QWidget, *, folder_name: str, ready_ids: set[str]):
        super().__init__("Install " + plan.name, runner, parent)
        self.resize(600, 530)
        self.plan, self.installer = plan, installer
        self.selected: set[str] = set()
        self._ready_ids = ready_ids
        self.body.addWidget(text_label(f"Pack {plan.pack_version} · Minecraft {plan.minecraft_version} / {plan.loader} {plan.loader_version}", theme.FONT_BODY))
        for label, attr, value in (("Instance name", "name_input", plan.name), ("Instance folder", "folder_input", folder_name)):
            self.body.addWidget(text_label(label, theme.FONT_DETAIL, muted=True))
            field = GlassLineEdit()
            field.setAccessibleName(label)
            field.setText(value)
            field.setFixedHeight(40)
            setattr(self, attr, field)
            self.body.addWidget(field)
        self.summary = text_label("", theme.FONT_BODY, bold=True)
        self.body.addWidget(self.summary)
        self.optional = ContentList(images)
        palette = parent.window().palette()
        self.optional.set_accent(palette.highlight().color(), palette.highlightedText().color())
        self.optional.setAccessibleName("Optional modpack files")
        self.optional.action_requested.connect(self._optional)
        self.body.addWidget(self.optional)
        self.manual = ManualFiles(extensions="Pack files (*.jar *.zip)")
        self.manual.link_requested.connect(self.link_requested.emit)
        self.manual.files_selected.connect(self._manual_files)
        self.body.addWidget(self.manual)
        self.body.addStretch()
        self.refresh()

    def refresh(self) -> None:
        selection = tuple(sorted(self.selected))
        self.summary.setText(f"{len(self.plan.selected_files(selection))} files · {format_size(self.plan.download_size(selection))} to download")
        rows = [ContentItem(file.path, file.label or file.path.rsplit("/", 1)[-1],
                            format_size(file.size), "Optional", actions=(ContentAction("toggle", "Include"),),
                            checked=file.path in self.selected, payload=file) for file in self.plan.optional_files]
        self.optional.set_items(rows)
        self.optional.setFixedHeight(min(192, len(rows) * 96))
        self.optional.setVisible(bool(rows))
        manual = self.plan.manual_files(selection)
        self.manual.display(manual, self._ready_ids)
        self.confirm.setEnabled(not self._busy and all(str(file.get("id", "")) in self._ready_ids for file in manual))

    def _optional(self, item: ContentItem, action: str) -> None:
        if self._busy:
            return
        selection = self.selected ^ {item.key}

        def ready(ids) -> None:
            self.selected = selection
            self._ready_ids = ids
            self.refresh()

        self.run(lambda: manual_ready_ids(self.installer.client, self.plan.manual_files(tuple(sorted(selection)))), ready)

    def _manual_files(self, paths: list[Path]) -> None:
        manual = self.plan.manual_files(tuple(sorted(self.selected)))

        def operation():
            self.installer.client.curseforge.register_manual_files(manual, paths)
            return manual_ready_ids(self.installer.client, manual)

        def ready(ids) -> None:
            self._ready_ids = ids
            self.refresh()

        self.run(operation, ready)

    def _accept(self) -> None:
        from wisc.services.profiles import new_instance_directory

        name = self.name_input.text().strip() or self.plan.name
        folder = self.folder_input.text().strip()
        selected = tuple(sorted(self.selected))

        def operation():
            new_instance_directory(self.installer.minecraft_directory, folder, name, self.installer.storage.load_installations())
            return {"name": name, "folder_name": folder, "optional_paths": selected}

        def ready(options) -> None:
            self.install_requested.emit(options)
            self.accept()

        if self.confirm.isEnabled():
            self.run(operation, ready)
