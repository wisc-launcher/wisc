"""Qt launcher update controller, update review dialog, and release notes viewer."""

from __future__ import annotations

from typing import Callable
from urllib.parse import urlparse

from PyQt6.QtCore import QObject, QUrl, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout, QWidget

from wisc.core.storage import load_settings
from wisc.services import updates
from wisc.ui import theme as theme
from wisc.ui.components import GlassButton, GlassPanel, text_label
from wisc.ui.content import ContentMarkdown
from wisc.ui.tasks import ServiceRunner


def open_url(url: str) -> None:
    try:
        raw = str(url).strip()
        parsed = urlparse(raw)
        if parsed.scheme in {"https", "http"}:
            QDesktopServices.openUrl(QUrl(raw))
    except Exception:
        pass


class _UpdateDialog(QDialog):
    """Frosted-glass dialog for reviewing, downloading, or applying a launcher update."""

    def __init__(
        self,
        controller: "UpdateController",
        release: updates.Release,
        *,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._controller = controller
        self._release = release
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(540, 480)
        self.resize(560, 520)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        panel = GlassPanel(radius=theme.RADIUS_PANEL)
        outer.addWidget(panel)

        body = QVBoxLayout(panel)
        body.setContentsMargins(24, 22, 24, 22)
        body.setSpacing(12)

        body.addWidget(text_label("Launcher Update", theme.FONT_DIALOG_TITLE, bold=True))

        version_row = QHBoxLayout()
        version_row.setSpacing(14)
        version_row.addWidget(
            text_label(f"Installed: {updates.version_label()}", theme.FONT_BODY, muted=True)
        )
        version_row.addWidget(text_label("\u2192", theme.FONT_BODY, muted=True))
        version_row.addWidget(
            text_label(f"New: v{release.version}", theme.FONT_BODY, bold=True)
        )
        version_row.addStretch(1)
        body.addLayout(version_row)

        ready = controller.phase == "ready"
        downloading = controller.phase == "downloading"
        can_apply = controller.service.can_apply() or controller.service.mock

        status_text = (
            "The update is verified and ready. Restart the launcher to finish."
            if ready
            else "Downloading the update in the background..."
            if downloading
            else "Download the new release while you continue using the launcher."
        )
        status_lbl = text_label(status_text, theme.FONT_BODY, muted=True)
        status_lbl.setWordWrap(True)
        body.addWidget(status_lbl)

        if not can_apply:
            note = text_label(
                "Running from source. Install the packaged Windows release to use automatic updates.",
                theme.FONT_DETAIL,
                muted=True,
            )
            note.setWordWrap(True)
            body.addWidget(note)
        elif controller.service.scope == "allusers":
            note = text_label(
                "Windows will request administrator approval for setup.",
                theme.FONT_DETAIL,
                muted=True,
            )
            note.setWordWrap(True)
            body.addWidget(note)

        markdown = ContentMarkdown()
        markdown.set_accent(controller.accent)
        markdown.display(release.notes[:10000] if release.notes else "See the release page for full details.")
        body.addWidget(markdown, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        gh_btn = GlassButton("View on GitHub")
        gh_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
        gh_btn.clicked.connect(lambda: open_url(release.page_url))
        actions.addWidget(gh_btn)
        actions.addStretch(1)

        later_btn = GlassButton("Later")
        later_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
        later_btn.clicked.connect(self._later)
        actions.addWidget(later_btn)

        if ready:
            apply_btn = GlassButton("Restart now", accented=True)
            apply_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
            apply_btn.setEnabled(can_apply)
            apply_btn.clicked.connect(self._apply)
            actions.addWidget(apply_btn)
        elif downloading:
            cancel_btn = GlassButton("Cancel download")
            cancel_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
            cancel_btn.clicked.connect(self._cancel_download)
            actions.addWidget(cancel_btn)
        else:
            dl_btn = GlassButton("Download update", accented=True)
            dl_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
            dl_btn.setEnabled(can_apply)
            dl_btn.clicked.connect(self._download)
            actions.addWidget(dl_btn)

        body.addLayout(actions)

    def _later(self) -> None:
        self._controller.later()
        self.reject()

    def _download(self) -> None:
        self.accept()
        self._controller.download()

    def _cancel_download(self) -> None:
        self._controller.cancel_download()
        self.reject()

    def _apply(self) -> None:
        self.accept()
        self._controller.apply()


class _ReleaseNotesDialog(QDialog):
    """Frosted-glass What's New / Release Notes dialog."""

    def __init__(
        self,
        title_version: str,
        notes_text: str,
        page_url: str,
        accent: str,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(520, 440)
        self.resize(540, 480)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        panel = GlassPanel(radius=theme.RADIUS_PANEL)
        outer.addWidget(panel)

        body = QVBoxLayout(panel)
        body.setContentsMargins(24, 22, 24, 22)
        body.setSpacing(12)

        body.addWidget(text_label(f"What's New ({title_version})", theme.FONT_DIALOG_TITLE, bold=True))

        markdown = ContentMarkdown()
        markdown.set_accent(accent)
        markdown.display(notes_text[:10000] or "See the release page for full details.")
        body.addWidget(markdown, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        gh_btn = GlassButton("Release Page")
        gh_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
        gh_btn.clicked.connect(lambda: open_url(page_url))
        actions.addWidget(gh_btn)
        actions.addStretch(1)

        close_btn = GlassButton("Close", accented=True)
        close_btn.setFixedHeight(theme.SEGMENT_HEIGHT)
        close_btn.clicked.connect(self.accept)
        actions.addWidget(close_btn)
        body.addLayout(actions)


class UpdateController(QObject):
    """Coordinates update checks, background downloads, dialogs, and restart handoff."""

    state_changed = pyqtSignal(str, str)  # (phase, status_message)
    progress_changed = pyqtSignal(object, object, object)  # (label_or_none, value_0_1000, detail)

    def __init__(
        self,
        runner: ServiceRunner,
        *,
        parent_widget: Callable[[], QWidget | None],
        notify: Callable[[str, str, str | None], None],
        busy: Callable[[], bool],
        close_window: Callable[[], None],
        accent: str = theme.DEFAULT_ACCENT,
        service: updates.UpdateService | None = None,
    ):
        super().__init__()
        self.runner = runner
        self._parent_widget = parent_widget
        self.notify = notify
        self.busy = busy
        self._close_window = close_window
        self.accent = accent
        self.service = service or updates.UpdateService()
        self.release: updates.Release | None = self.service.prepared_release
        self.phase = "ready" if self.release else "idle"
        self.status_message = (
            f"v{self.release.version} is ready. Restart when convenient."
            if self.release
            else "Check for the latest launcher release."
        )
        self.applying = False
        self._closed = False
        self._notified: set[str] = set()
        self._check_token: int | None = None
        self._dl_token: int | None = None

    def set_accent(self, accent: str) -> None:
        self.accent = accent

    def _set_state(self, phase: str, message: str) -> None:
        self.phase = phase
        self.status_message = message
        self.state_changed.emit(phase, message)

    def startup(self) -> None:
        if self._closed:
            return
        if self.release and self.service.should_notify(self.release.version):
            self._notified.add(self.release.version)
            self.notify(
                f"Wisc v{self.release.version} is ready to install.",
                "info",
                "Launcher update",
            )
        settings = load_settings()
        if settings.get("check_updates_automatically", True) and self.phase == "idle":
            QTimer.singleShot(2500, lambda: self.check(manual=False))

    def check(self, *, manual: bool = False) -> None:
        if self._closed or self.phase in ("checking", "downloading", "handing_off"):
            return
        if self.phase == "ready":
            if manual:
                self.show_dialog()
            return
        self._set_state("checking", "Checking for launcher updates...")

        def run_check():
            return self.service.check(manual=manual)

        def on_done(release: updates.Release | None) -> None:
            self._check_token = None
            if self._closed:
                return
            self.release = release
            if release is not None:
                self._set_state("available", f"Update available: v{release.version}")
                if manual or (release.version not in self._notified and self.service.should_notify(release.version)):
                    self._notified.add(release.version)
                    self.notify(
                        f"Wisc v{release.version} is available.",
                        "info",
                        "Launcher update",
                    )
                if (
                    (self.service.can_apply() or self.service.mock)
                    and load_settings().get("download_updates_automatically", False)
                ):
                    self.download()
            else:
                self._set_state("idle", "You're up to date.")
                if manual:
                    self.notify("You're using the latest stable launcher release.", "success", "Updates")

        def on_fail(error: Exception) -> None:
            self._check_token = None
            if self._closed:
                return
            msg = str(error) if manual else "Update check unavailable. You can try again manually."
            self._set_state("idle", msg)
            if manual:
                self.notify(str(error), "warning", "Could not check for updates")

        self._check_token = self.runner.submit(run_check, on_done, on_fail)

    def download(self) -> None:
        if self._closed or not self.release or self.phase in ("downloading", "ready", "handing_off"):
            return
        if not (self.service.can_apply() or self.service.mock):
            self.notify("Automatic updates are only available in packaged Windows builds.", "info", "Updates")
            return
        release = self.release
        self._set_state("downloading", f"Downloading v{release.version}...")
        self.progress_changed.emit(f"Downloading Wisc v{release.version}...", None, "")

        def on_progress(completed: int, total: int) -> None:
            if total and total > 0:
                pct = max(0, min(1000, int(completed * 1000 / total)))
                mb_done = completed / (1024 * 1024)
                mb_total = total / (1024 * 1024)
                self.progress_changed.emit(
                    f"Downloading Wisc v{release.version}...",
                    pct,
                    f"{mb_done:.1f} / {mb_total:.1f} MB",
                )

        def run_download():
            return self.service.download(release, on_progress)

        def on_done(_path) -> None:
            self._dl_token = None
            self.progress_changed.emit(None, None, "")
            if self._closed:
                return
            self._set_state("ready", f"v{release.version} is ready. Restart when convenient.")
            self.notify(f"Wisc v{release.version} is ready to install.", "success", "Update ready")

        def on_fail(error: Exception) -> None:
            self._dl_token = None
            self.progress_changed.emit(None, None, "")
            if self._closed:
                return
            if isinstance(error, updates.UpdateCancelled):
                self._set_state("available", f"Update available: v{release.version}")
                self.notify("Update download cancelled.", "info", "Updates")
            else:
                self._set_state("available", f"Update download failed: {error}")
                self.notify(str(error), "warning", "Update download failed")

        self._dl_token = self.runner.submit(run_download, on_done, on_fail)

    def cancel_download(self) -> None:
        self.service.cancel.set()

    def later(self) -> None:
        if self.release:
            try:
                self.service.snooze(self.release.version)
            except OSError:
                self.notify("Could not save the update reminder.", "warning", "Updates")

    def apply(self) -> None:
        if self._closed or self.phase != "ready":
            return
        if self.busy():
            self.notify("Wait for Minecraft or mod downloads to finish before restarting.", "warning", "Updates")
            return
        if self.service.mock:
            self.notify("Update preview: packaged builds restart here to apply the update.", "info", "Updates")
            return
        try:
            self.applying = True
            self._set_state("handing_off", "Restarting to apply update...")
            self.service.start_helper()
            self._close_window()
        except Exception as error:
            self.applying = False
            self._set_state("ready", f"Could not start updater: {error}")
            self.notify(str(error), "error", "Update failed")

    def show_dialog(self) -> None:
        if not self.release or self.phase == "handing_off":
            return
        dialog = _UpdateDialog(self, self.release, parent=self._parent_widget())
        dialog.exec()

    def show_release_notes(self) -> None:
        if self.release and self.release.notes:
            version_str = f"v{self.release.version}"
            notes_text = self.release.notes
            page_url = self.release.page_url
        else:
            cache = updates.read_json(self.service.discovery_path)
            doc = cache.get("release") if isinstance(cache, dict) else None
            if isinstance(doc, dict) and doc.get("body"):
                version_str = str(doc.get("name") or doc.get("tag_name") or updates.version_label())
                notes_text = updates.clean_release_notes(str(doc["body"]))
                page_url = str(doc.get("html_url") or f"https://github.com/{updates.REPOSITORY}/releases")
            else:
                version_str = updates.version_label()
                page_url = f"https://github.com/{updates.REPOSITORY}/releases"
                notes_text = (
                    "### What's New in Wisc\n\n"
                    "- **In-Launcher Updater:** Automatic background updates, integrity verification, and one-click restart.\n"
                    "- **Modpacks & Mods:** Browse, download, and install Modrinth & CurseForge content.\n"
                    "- **3D Skin Viewer & Discord Presence:** Live 3D skin preview and Discord Rich Presence.\n"
                    "- **Live Game Logs & Profile Repair:** Stream Minecraft logs in real time and repair installations."
                )
        dialog = _ReleaseNotesDialog(
            version_str,
            notes_text,
            page_url,
            self.accent,
            parent=self._parent_widget(),
        )
        dialog.exec()

    def stop(self) -> None:
        self._closed = True
        self.service.cancel.set()
        if self._check_token is not None:
            self.runner.cancel(self._check_token)
            self._check_token = None
        if self._dl_token is not None:
            self.runner.cancel(self._dl_token)
            self._dl_token = None
