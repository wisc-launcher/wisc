"""In-app profile creation and editing page, plus profile action menus and delete confirmation."""

from __future__ import annotations

from pathlib import Path
import uuid

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from wisc.core.paths import ASSETS_DIR
from wisc.services import artwork as artwork_service
from wisc.services import banners as banner_service
from wisc.services import launcher
from wisc.services import profiles as profile_service
from wisc.ui import theme as theme
from wisc.ui.components import (
    GlassButton, GlassLineEdit, GlassPanel, LauncherComboBox,
    ProfileCard, enable_smooth_scroll, resolve_profile_icon_path, text_label,
)
from wisc.ui.components import build_profile_actions_menu as build_profile_actions_menu
from wisc.ui.options import GlassSwitch
from wisc.ui.tasks import LatestServiceTask, ServiceRunner

LOADERS = ("Vanilla", "Fabric", "Forge", "Quilt", "NeoForge")
NESTED_GLASS_OPACITY = 0.80


def bundled_profile_icons() -> list[tuple[str, Path]]:
    """Return available bundled block and mob face profile icons."""
    icons: list[tuple[str, Path]] = []
    for folder in ("icon_blocks", "icon_faces"):
        directory = ASSETS_DIR / "icons" / folder
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.png")):
            label = path.stem.replace("_", " ").title()
            icons.append((label, path))
    return icons


class ProfileEditorPage(QWidget):
    """In-app two-column page to create a new profile or edit an existing one."""

    back_requested = pyqtSignal()
    profile_saved = pyqtSignal(dict, bool)  # (saved_record, is_new)

    def __init__(
        self,
        runner: ServiceRunner,
        colors: dict[str, str],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._runner = runner
        self._colors = colors
        self._existing_profile: dict | None = None
        self._is_new = True
        self._existing_profiles: list[dict] = []
        self._versions_task = LatestServiceTask(runner)
        self._loader_task = LatestServiceTask(runner)
        self._catalog: list[dict] = []
        self._latest_release: str | None = None
        self._name_customized = False
        self._folder_customized = False
        self._icon_value = "grass_block.png"
        self._custom_banner = ""
        self._current_loader = "Vanilla"
        self._preview_artwork = ASSETS_DIR / "version-art" / "java-edition.webp"

        root = QVBoxLayout(self)
        root.setContentsMargins(*theme.PAGE_MARGINS)
        root.setSpacing(theme.PAGE_SPACING)

        # --- Header bar ---
        header_bar = QWidget()
        header_bar.setFixedHeight(theme.HEADER_HEIGHT)
        header = QHBoxLayout(header_bar)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(12)
        self.back_btn = GlassButton("\u2039  Back")
        self.back_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
        self.back_btn.setAccessibleName("Back")
        self.back_btn.clicked.connect(self.back_requested.emit)
        header.addWidget(self.back_btn)
        self.page_title = text_label("New profile", theme.FONT_PAGE_TITLE, bold=True)
        header.addWidget(self.page_title)
        header.addStretch(1)
        root.addWidget(header_bar)

        # --- Scrollable centered body ---
        scroll = QScrollArea()
        scroll.setObjectName("contentScroll")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.viewport().setAutoFillBackground(False)
        enable_smooth_scroll(scroll)

        scroll_body = QWidget()
        scroll_body.setObjectName("contentScrollBody")
        center_wrap = QHBoxLayout(scroll_body)
        center_wrap.setContentsMargins(0, 4, 8, 12)
        center_wrap.addStretch(1)

        container = QWidget()
        container.setMaximumWidth(880)
        columns = QHBoxLayout(container)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(20)
        columns.setAlignment(Qt.AlignmentFlag.AlignTop)

        # === LEFT COLUMN: Live Preview + 4x4 Icon Grid ===
        left_col = QVBoxLayout()
        left_col.setSpacing(14)

        self._preview_card = ProfileCard(
            "Latest",
            "Latest \u00b7 Vanilla",
            self._preview_artwork,
            resolve_profile_icon_path(self._icon_value),
            self._colors["btn_primary"],
            self,
        )
        self._preview_card.setCheckable(False)
        self._preview_card.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._preview_card.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        left_col.addWidget(self._preview_card)

        self.icon_panel = GlassPanel(radius=theme.RADIUS_CARD)
        self.icon_panel.setObjectName("profileIconPanel")
        icon_layout = QVBoxLayout(self.icon_panel)
        icon_layout.setContentsMargins(14, 14, 14, 14)
        icon_layout.setSpacing(10)
        icon_layout.addWidget(text_label("Profile icon", theme.FONT_DETAIL, muted=True))

        icon_grid = QGridLayout()
        icon_grid.setSpacing(8)
        self._icon_buttons: dict[str, GlassButton] = {}
        self._icon_group = QButtonGroup(self)
        self._icon_group.setExclusive(True)
        for idx, (label, path) in enumerate(bundled_profile_icons()[:16]):
            btn = GlassButton(radius=theme.RADIUS_BUTTON, opacity=NESTED_GLASS_OPACITY)
            btn.setObjectName("profileIconTile")
            btn.setFixedSize(48, 48)
            pixmap = QPixmap(str(path)).scaled(
                34,
                34,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            btn.setIcon(QIcon(pixmap))
            btn.setIconSize(QSize(34, 34))
            btn.setCheckable(True)
            btn.setToolTip(label)
            btn.setAccessibleName(label)
            btn.clicked.connect(lambda checked=False, name=path.name: self._set_icon(name))
            self._icon_group.addButton(btn)
            self._icon_buttons[path.name] = btn
            icon_grid.addWidget(btn, idx // 4, idx % 4)
        icon_layout.addLayout(icon_grid)

        custom_icon_btn = GlassButton("Custom image\u2026", opacity=NESTED_GLASS_OPACITY)
        custom_icon_btn.setFixedHeight(theme.COMPACT_HEIGHT)
        custom_icon_btn.clicked.connect(self._browse_custom_icon)
        icon_layout.addWidget(custom_icon_btn)

        banner_row = QHBoxLayout()
        banner_row.setSpacing(6)
        custom_banner_btn = GlassButton("Custom banner\u2026", opacity=NESTED_GLASS_OPACITY)
        custom_banner_btn.setFixedHeight(theme.COMPACT_HEIGHT)
        custom_banner_btn.clicked.connect(self._browse_custom_banner)
        banner_row.addWidget(custom_banner_btn, 1)
        self.clear_banner_btn = GlassButton("Reset", opacity=NESTED_GLASS_OPACITY)
        self.clear_banner_btn.setFixedHeight(theme.COMPACT_HEIGHT)
        self.clear_banner_btn.clicked.connect(self._clear_custom_banner)
        self.clear_banner_btn.setVisible(False)
        banner_row.addWidget(self.clear_banner_btn)
        icon_layout.addLayout(banner_row)

        left_col.addWidget(self.icon_panel)
        left_col.addStretch(1)

        left_widget = QWidget()
        left_widget.setFixedWidth(252)
        left_widget.setLayout(left_col)
        columns.addWidget(left_widget, 0, Qt.AlignmentFlag.AlignTop)

        # === RIGHT COLUMN: Structured Form ===
        right_col = QVBoxLayout()
        right_col.setSpacing(14)

        self.form_panel = GlassPanel(radius=theme.RADIUS_CARD)
        self.form_panel.setObjectName("profileFormPanel")
        self._apply_form_field_styles()
        form = QVBoxLayout(self.form_panel)
        form.setContentsMargins(20, 18, 20, 20)
        form.setSpacing(14)

        # Profile Name
        name_group = QVBoxLayout()
        name_group.setSpacing(6)
        name_group.addWidget(text_label("Profile name", theme.FONT_DETAIL, muted=True))
        self.name_edit = GlassLineEdit(opacity=NESTED_GLASS_OPACITY)
        self.name_edit.setFixedHeight(theme.FIELD_HEIGHT)
        self.name_edit.setPlaceholderText("Defaults to the selected version")
        self.name_edit.textEdited.connect(self._on_name_edited)
        name_group.addWidget(self.name_edit)
        form.addLayout(name_group)

        # Mod Loader (Segmented Pills)
        loader_group = QVBoxLayout()
        loader_group.setSpacing(6)
        loader_group.addWidget(text_label("Mod loader", theme.FONT_DETAIL, muted=True))
        loader_row = QHBoxLayout()
        loader_row.setSpacing(6)
        self._loader_group = QButtonGroup(self)
        self._loader_group.setExclusive(True)
        self._loader_buttons: dict[str, GlassButton] = {}
        for name in LOADERS:
            btn = GlassButton(name, radius=theme.RADIUS_BUTTON, opacity=NESTED_GLASS_OPACITY)
            btn.setCheckable(True)
            btn.setFixedHeight(theme.COMPACT_HEIGHT)
            btn.clicked.connect(lambda checked=False, l=name: self._select_loader(l))
            self._loader_group.addButton(btn)
            self._loader_buttons[name] = btn
            loader_row.addWidget(btn, 1)
        loader_group.addLayout(loader_row)
        form.addLayout(loader_group)

        # Minecraft Version + Loader Version side-by-side
        ver_row = QHBoxLayout()
        ver_row.setSpacing(12)

        mc_col = QVBoxLayout()
        mc_col.setSpacing(6)
        mc_col.addWidget(text_label("Minecraft version", theme.FONT_DETAIL, muted=True))
        self.mc_combo = LauncherComboBox(
            height=theme.FIELD_HEIGHT,
            min_width=160,
            max_width=16777215,
            opacity=NESTED_GLASS_OPACITY,
        )
        self.mc_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.mc_combo.currentTextChanged.connect(self._on_mc_version_changed)
        mc_col.addWidget(self.mc_combo)
        ver_row.addLayout(mc_col, 1)

        self.loader_version_host = QWidget()
        lv_col = QVBoxLayout(self.loader_version_host)
        lv_col.setContentsMargins(0, 0, 0, 0)
        lv_col.setSpacing(6)
        lv_col.addWidget(text_label("Loader version", theme.FONT_DETAIL, muted=True))
        self.loader_version_combo = LauncherComboBox(
            height=theme.FIELD_HEIGHT,
            min_width=160,
            max_width=16777215,
            opacity=NESTED_GLASS_OPACITY,
        )
        self.loader_version_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lv_col.addWidget(self.loader_version_combo)
        ver_row.addWidget(self.loader_version_host, 1)
        form.addLayout(ver_row)

        self.snapshots_switch = GlassSwitch("Show snapshots and older versions", False, colors["btn_primary"])
        self.snapshots_switch.toggled.connect(self._populate_mc_versions)
        form.addWidget(self.snapshots_switch)

        # Instance & Folder
        self.instance_switch = GlassSwitch("Isolated instance folder", True, colors["btn_primary"])
        self.instance_switch.toggled.connect(self._on_instance_toggled)
        form.addWidget(self.instance_switch)

        self.folder_host = QWidget()
        f_col = QVBoxLayout(self.folder_host)
        f_col.setContentsMargins(0, 0, 0, 0)
        f_col.setSpacing(6)
        f_col.addWidget(text_label("Instance folder name", theme.FONT_DETAIL, muted=True))
        self.folder_edit = GlassLineEdit(opacity=NESTED_GLASS_OPACITY)
        self.folder_edit.setFixedHeight(theme.FIELD_HEIGHT)
        self.folder_edit.setPlaceholderText("Auto-generated from profile name")
        self.folder_edit.textEdited.connect(self._on_folder_edited)
        f_col.addWidget(self.folder_edit)
        form.addWidget(self.folder_host)

        self.instance_hint = text_label(
            "Instance folder location cannot be changed after creation.",
            theme.FONT_DETAIL,
            muted=True,
        )
        self.instance_hint.setVisible(False)
        form.addWidget(self.instance_hint)

        # Advanced (Collapsible)
        self.advanced_toggle = GlassButton("Advanced options  \u25be", opacity=NESTED_GLASS_OPACITY)
        self.advanced_toggle.setFixedHeight(theme.COMPACT_HEIGHT)
        self.advanced_toggle.clicked.connect(self._toggle_advanced)
        form.addWidget(self.advanced_toggle, 0, Qt.AlignmentFlag.AlignLeft)

        self.advanced_host = QWidget()
        adv_layout = QHBoxLayout(self.advanced_host)
        adv_layout.setContentsMargins(0, 0, 0, 0)
        adv_layout.setSpacing(12)

        mem_col = QVBoxLayout()
        mem_col.setSpacing(6)
        mem_col.addWidget(text_label("Memory (MB, optional)", theme.FONT_DETAIL, muted=True))
        self.memory_edit = GlassLineEdit(opacity=NESTED_GLASS_OPACITY)
        self.memory_edit.setFixedHeight(theme.FIELD_HEIGHT)
        self.memory_edit.setPlaceholderText("Global default")
        mem_col.addWidget(self.memory_edit)
        adv_layout.addLayout(mem_col, 1)

        jvm_col = QVBoxLayout()
        jvm_col.setSpacing(6)
        jvm_col.addWidget(text_label("JVM arguments (optional)", theme.FONT_DETAIL, muted=True))
        self.jvm_edit = GlassLineEdit(opacity=NESTED_GLASS_OPACITY)
        self.jvm_edit.setFixedHeight(theme.FIELD_HEIGHT)
        self.jvm_edit.setPlaceholderText("e.g. -XX:+UseG1GC")
        jvm_col.addWidget(self.jvm_edit)
        adv_layout.addLayout(jvm_col, 2)

        self.advanced_host.setVisible(False)
        form.addWidget(self.advanced_host)

        # Error & Footer inside right column
        self.error = text_label("", theme.FONT_DETAIL)
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #F38BA8;")
        self.error.hide()
        form.addWidget(self.error)

        footer = QHBoxLayout()
        footer.setSpacing(10)
        footer.addStretch(1)
        self.cancel_btn = GlassButton("Cancel", opacity=NESTED_GLASS_OPACITY)
        self.cancel_btn.setFixedHeight(theme.BUTTON_HEIGHT)
        self.cancel_btn.clicked.connect(self.back_requested.emit)
        footer.addWidget(self.cancel_btn)
        self.save_btn = QPushButton("Create profile")
        self.save_btn.setProperty("primary", True)
        self.save_btn.setFixedHeight(theme.BUTTON_HEIGHT)
        self.save_btn.clicked.connect(self._save)
        footer.addWidget(self.save_btn)
        form.addLayout(footer)

        right_col.addWidget(self.form_panel)
        right_col.addStretch(1)
        columns.addLayout(right_col, 1)

        center_wrap.addWidget(container, 1)
        center_wrap.addStretch(1)
        scroll.setWidget(scroll_body)
        root.addWidget(scroll, 1)

    def _apply_form_field_styles(self) -> None:
        accent = self._colors["btn_primary"]
        accent_text = self._colors["btn_primary_text"]
        accent_color = QColor(accent)
        tile_fill = f"rgba({accent_color.red()}, {accent_color.green()}, {accent_color.blue()}, 44)"
        self.icon_panel.setStyleSheet(f"""
            QWidget#profileIconPanel QPushButton#profileIconTile {{
                padding: 0px;
            }}
            QWidget#profileIconPanel QPushButton#profileIconTile:checked {{
                background: {tile_fill};
                border: 2px solid {accent};
            }}
        """)
        self.form_panel.setStyleSheet(f"""
            QWidget#profileFormPanel QLineEdit {{
                border-radius: {theme.RADIUS_FIELD}px;
                padding: 0 12px;
            }}
            QWidget#profileFormPanel QPushButton[checkable="true"]:checked {{
                background: {accent};
                color: {accent_text};
                font-weight: 600;
            }}
        """)

    def apply_theme(self, colors: dict[str, str]) -> None:
        self._colors = colors
        accent = colors["btn_primary"]
        self.snapshots_switch.set_accent(accent)
        self.instance_switch.set_accent(accent)
        self._apply_form_field_styles()
        self._refresh_preview()

    def open_profile(
        self,
        profile: dict | None = None,
        existing_profiles: list[dict] | None = None,
    ) -> None:
        """Reset and populate the page for creating or editing a profile."""
        self._versions_task.invalidate()
        self._loader_task.invalidate()
        self._existing_profile = dict(profile) if profile else None
        self._is_new = self._existing_profile is None
        self._existing_profiles = list(existing_profiles or [])
        self._show_error("")
        self.mc_combo.blockSignals(True)
        self.mc_combo.clear()
        self.mc_combo.blockSignals(False)
        self.loader_version_combo.clear()

        title = "New profile" if self._is_new else f"Edit {self._existing_profile.get('name', 'profile')}"
        self.page_title.setText(title)
        self.save_btn.setText("Create profile" if self._is_new else "Save changes")

        self._icon_value = str((self._existing_profile or {}).get("icon") or "grass_block.png")
        self._sync_icon_buttons()
        self._custom_banner = (
            banner_service.get_custom_instance_banner(self._existing_profile, launcher.minecraft_directory) or ""
            if self._existing_profile
            else ""
        )
        self.clear_banner_btn.setVisible(bool(self._custom_banner))

        name = str((self._existing_profile or {}).get("name") or "")
        self._name_customized = bool(name.strip())
        self.name_edit.setText(name)
        self.name_edit.setPlaceholderText("Defaults to the selected version")

        initial_loader = str((self._existing_profile or {}).get("loader") or "Vanilla")
        self._current_loader = initial_loader if initial_loader in LOADERS else "Vanilla"
        for loader_name, btn in self._loader_buttons.items():
            btn.setChecked(loader_name == self._current_loader)

        self.snapshots_switch.blockSignals(True)
        self.snapshots_switch.setChecked(False)
        self.snapshots_switch.blockSignals(False)

        initial_instance = bool((self._existing_profile or {}).get("is_instance", True))
        self.instance_switch.blockSignals(True)
        self.instance_switch.setChecked(initial_instance)
        self.instance_switch.setEnabled(self._is_new)
        self.instance_switch.blockSignals(False)

        self._folder_customized = False
        folder_name = str((self._existing_profile or {}).get("instance_name") or "")
        self.folder_edit.setText(folder_name)
        self.folder_edit.setReadOnly(not self._is_new)
        self.instance_hint.setVisible(not self._is_new)

        mem = (self._existing_profile or {}).get("memory_mb")
        self.memory_edit.setText(str(mem) if mem else "")
        jvm = str((self._existing_profile or {}).get("jvm_args") or "")
        self.jvm_edit.setText(jvm)
        has_advanced = bool(mem or jvm)
        self.advanced_host.setVisible(has_advanced)
        self.advanced_toggle.setText("Advanced options  \u25b4" if has_advanced else "Advanced options  \u25be")

        self._on_instance_toggled(self.instance_switch.isChecked())
        self._update_loader_visibility()
        self._refresh_preview()
        self._load_versions()

    def hideEvent(self, event) -> None:
        self._versions_task.invalidate()
        self._loader_task.invalidate()
        super().hideEvent(event)

    def _sync_icon_buttons(self) -> None:
        self._icon_group.setExclusive(False)
        for name, btn in self._icon_buttons.items():
            btn.setChecked(name == self._icon_value)
        self._icon_group.setExclusive(True)

    def _refresh_preview(self) -> None:
        mc_ver = self.mc_combo.currentText().strip() or str(
            (self._existing_profile or {}).get("minecraft_version") or "Latest"
        )
        display_name = self.name_edit.text().strip() or mc_ver
        details = f"{mc_ver} \u00b7 {self._current_loader}"
        icon_path = resolve_profile_icon_path(self._icon_value)
        if self._custom_banner and Path(self._custom_banner).is_file():
            artwork_path = Path(self._custom_banner)
        else:
            resolved = artwork_service.resolve_background_artwork(
                {"minecraft_version": mc_ver},
                launcher.minecraft_directory,
            )
            artwork_path = Path(resolved.source) if resolved.source else self._preview_artwork
        self._preview_card.set_accent(self._colors["btn_primary"])
        self._preview_card.set_preview(display_name, details, icon_path, artwork_path)

    def _set_icon(self, value: str) -> None:
        self._icon_value = value
        self._sync_icon_buttons()
        self._refresh_preview()

    def _browse_custom_icon(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self, "Select Profile Icon", "", "Images (*.png *.jpg *.jpeg *.webp)",
        )
        if selected:
            self._set_icon(selected)

    def _browse_custom_banner(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self, "Select Profile Banner", "", "Images (*.png *.jpg *.jpeg *.webp)",
        )
        if selected:
            self._custom_banner = selected
            self.clear_banner_btn.setVisible(True)
            self._refresh_preview()

    def _clear_custom_banner(self) -> None:
        self._custom_banner = ""
        self.clear_banner_btn.setVisible(False)
        self._refresh_preview()

    def _on_name_edited(self, text: str) -> None:
        self._name_customized = bool(text.strip())
        if self._is_new and not self._folder_customized and self.instance_switch.isChecked():
            self._suggest_folder_name()
        self._refresh_preview()

    def _on_folder_edited(self, text: str) -> None:
        self._folder_customized = bool(text.strip())

    def _suggest_folder_name(self) -> None:
        raw = self.name_edit.text().strip() or self.mc_combo.currentText().strip() or "instance"
        try:
            suggested = profile_service.instance_folder_name("", raw)
        except ValueError:
            suggested = "instance"
        self.folder_edit.setText(suggested)

    def _on_instance_toggled(self, checked: bool) -> None:
        self.folder_host.setVisible(checked)
        if checked and self._is_new and not self._folder_customized:
            self._suggest_folder_name()

    def _toggle_advanced(self) -> None:
        visible = not self.advanced_host.isVisible()
        self.advanced_host.setVisible(visible)
        self.advanced_toggle.setText("Advanced options  \u25b4" if visible else "Advanced options  \u25be")

    def _select_loader(self, loader_name: str) -> None:
        self._current_loader = loader_name
        self._update_loader_visibility()
        self._refresh_loader_versions()
        self._refresh_preview()

    def _update_loader_visibility(self) -> None:
        self.loader_version_host.setVisible(self._current_loader != "Vanilla")

    def _load_versions(self) -> None:
        local_versions, local_latest = launcher.get_local_version_catalog()
        if local_versions:
            self._catalog = local_versions
            self._latest_release = local_latest
            self._populate_mc_versions()

        self._versions_task.submit(
            launcher.get_version_catalog,
            self._on_versions_loaded,
            lambda err: None,
        )

    def _on_versions_loaded(self, result: tuple[list[dict], str | None, bool]) -> None:
        versions, latest_release, _online = result
        if versions:
            self._catalog = versions
            self._latest_release = latest_release
            self._populate_mc_versions()

    def _populate_mc_versions(self) -> None:
        show_all = self.snapshots_switch.isChecked()
        current = self.mc_combo.currentText() or str((self._existing_profile or {}).get("minecraft_version") or "")
        filtered = [
            v["id"] for v in self._catalog
            if show_all or v.get("type") == "release"
        ]
        if current and current not in filtered:
            filtered.insert(0, current)
        if not filtered and self._latest_release:
            filtered = [self._latest_release]

        self.mc_combo.blockSignals(True)
        self.mc_combo.clear()
        self.mc_combo.addItems(filtered)
        if current and current in filtered:
            self.mc_combo.setCurrentText(current)
        elif self._latest_release and self._latest_release in filtered:
            self.mc_combo.setCurrentText(self._latest_release)
        self.mc_combo.blockSignals(False)
        self._on_mc_version_changed(self.mc_combo.currentText())

    def _on_mc_version_changed(self, mc_version: str) -> None:
        if not self._name_customized and mc_version:
            self.name_edit.setPlaceholderText(mc_version)
            if self._is_new and not self._folder_customized and self.instance_switch.isChecked():
                self._suggest_folder_name()
        self._refresh_loader_versions()
        self._refresh_preview()

    def _refresh_loader_versions(self) -> None:
        self._loader_task.invalidate()
        loader_name = self._current_loader
        mc_version = self.mc_combo.currentText().strip()
        if loader_name == "Vanilla" or not mc_version:
            self.loader_version_combo.clear()
            return

        self.loader_version_combo.clear()
        self.loader_version_combo.addItem("Loading\u2026")
        self.loader_version_combo.setEnabled(False)

        def fetch():
            mod_loader = launcher.get_mod_loader(loader_name)
            return mod_loader.get_loader_versions(mc_version, False)

        self._loader_task.submit(fetch, self._on_loader_versions_loaded, self._on_loader_versions_failed)

    def _on_loader_versions_loaded(self, versions: list[str]) -> None:
        self.loader_version_combo.setEnabled(True)
        self.loader_version_combo.clear()
        existing_lv = str((self._existing_profile or {}).get("loader_version") or "")
        items = list(versions or [])
        if existing_lv and existing_lv not in items:
            items.insert(0, existing_lv)
        if not items:
            self.loader_version_combo.addItem("No versions found")
            self.loader_version_combo.setEnabled(False)
            return
        self.loader_version_combo.addItems(items)
        if existing_lv and existing_lv in items:
            self.loader_version_combo.setCurrentText(existing_lv)

    def _on_loader_versions_failed(self, _error: Exception) -> None:
        self.loader_version_combo.clear()
        existing_lv = str((self._existing_profile or {}).get("loader_version") or "")
        if existing_lv:
            self.loader_version_combo.addItem(existing_lv)
            self.loader_version_combo.setEnabled(True)
        else:
            self.loader_version_combo.addItem("Unavailable offline")
            self.loader_version_combo.setEnabled(False)

    def _show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.setVisible(bool(message))

    def _save(self) -> None:
        self._show_error("")
        mc_version = self.mc_combo.currentText().strip()
        if not mc_version:
            self._show_error("Select a Minecraft version.")
            return

        loader_name = self._current_loader
        loader_version = ""
        if loader_name != "Vanilla":
            lv = self.loader_version_combo.currentText().strip()
            if not lv or lv in ("Loading\u2026", "No versions found", "Unavailable offline"):
                self._show_error(f"Select a valid {loader_name} version.")
                return
            loader_version = lv

        memory_text = self.memory_edit.text().strip()
        memory_mb: int | None = None
        if memory_text:
            try:
                memory_mb = int(memory_text)
                if memory_mb < 512:
                    raise ValueError
            except ValueError:
                self._show_error("Memory override must be an integer of at least 512 MB.")
                return

        name = self.name_edit.text().strip() or mc_version
        is_instance = self.instance_switch.isChecked()
        folder_name = self.folder_edit.text().strip()

        record = dict(self._existing_profile) if self._existing_profile else {
            "id": str(uuid.uuid4()),
        }
        record["name"] = name
        record["minecraft_version"] = mc_version
        record["loader"] = loader_name
        record["loader_version"] = loader_version
        record["icon"] = self._icon_value
        if self._custom_banner and Path(self._custom_banner).is_file():
            cache_dir = banner_service.get_banner_cache_dir()
            if Path(self._custom_banner).parent != cache_dir:
                saved_banner = banner_service.save_custom_banner_image(record["id"], self._custom_banner)
                record["custom_banner"] = saved_banner or self._custom_banner
            else:
                record["custom_banner"] = self._custom_banner
        else:
            record["custom_banner"] = ""
        record["is_instance"] = is_instance
        if loader_name == "Vanilla":
            record["version_id"] = mc_version
        else:
            try:
                record["version_id"] = launcher.get_mod_loader(loader_name).get_installed_version(
                    mc_version, loader_version,
                )
            except Exception:
                record.pop("version_id", None)

        if memory_mb is not None:
            record["memory_mb"] = memory_mb
        else:
            record.pop("memory_mb", None)

        jvm_args = self.jvm_edit.text().strip()
        if jvm_args:
            record["jvm_args"] = jvm_args
        else:
            record.pop("jvm_args", None)

        from wisc.core import storage
        if self._is_new:
            try:
                saved = profile_service.save_new_profile(
                    record, launcher.minecraft_directory, folder_name, storage,
                )
            except Exception as exc:
                self._show_error(str(exc) or "Could not create profile.")
                return
            self.profile_saved.emit(saved, True)
        else:
            installations = storage.load_installations()
            updated = False
            for idx, item in enumerate(installations):
                if item.get("id") == record["id"]:
                    installations[idx] = record
                    updated = True
                    break
            if not updated:
                installations.append(record)
            storage.save_installations(installations)
            self.profile_saved.emit(record, False)


def confirm_delete_profile(
    parent: QWidget,
    profile_name: str,
    is_instance: bool,
    colors: dict[str, str],
) -> tuple[bool, bool]:
    """Prompt the user to confirm deleting a profile and optionally its instance files."""
    dialog = QDialog(parent.window())
    dialog.setPalette(parent.window().palette())
    dialog.setWindowTitle("Delete profile")
    dialog.setWindowModality(Qt.WindowModality.WindowModal)
    dialog.setObjectName("contentReview")
    dialog.setMinimumWidth(420)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(24, 20, 24, 20)
    layout.setSpacing(14)
    layout.addWidget(text_label(f"Delete '{profile_name}'?", theme.FONT_DIALOG_TITLE, bold=True))
    msg = text_label(
        "This removes the profile from your library.",
        theme.FONT_BODY,
        muted=True,
    )
    msg.setWordWrap(True)
    layout.addWidget(msg)

    delete_files_switch: GlassSwitch | None = None
    if is_instance:
        delete_files_switch = GlassSwitch(
            "Also delete instance folder and saves from disk",
            False,
            colors["btn_primary"],
        )
        layout.addWidget(delete_files_switch)

    footer = QHBoxLayout()
    footer.setSpacing(10)
    footer.addStretch(1)
    cancel_btn = GlassButton("Cancel")
    cancel_btn.setFixedHeight(theme.BUTTON_HEIGHT)
    cancel_btn.clicked.connect(dialog.reject)
    footer.addWidget(cancel_btn)
    delete_btn = QPushButton("Delete")
    delete_btn.setProperty("primary", True)
    delete_btn.setFixedHeight(theme.BUTTON_HEIGHT)
    delete_btn.clicked.connect(dialog.accept)
    footer.addWidget(delete_btn)
    layout.addLayout(footer)

    confirmed = dialog.exec() == QDialog.DialogCode.Accepted
    delete_files = bool(delete_files_switch and delete_files_switch.isChecked())
    return confirmed, delete_files
