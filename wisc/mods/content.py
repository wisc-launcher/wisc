"""Verified shader and resource pack ZIPs installed in a profile's game folder."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import tempfile
from typing import Callable
import zipfile

from wisc.core.paths import launcher_data_dir
from wisc.mods.manager import _atomic_write, _directory_lock, _digest, primary_content_file, safe_archive_name
from wisc.mods.modpacks import PackInstaller


CONTENT_FOLDERS = {"shader": "shaderpacks", "resourcepack": "resourcepacks"}


@dataclass(frozen=True)
class LocalContentPack:
    filename: str
    title: str
    size: int
    modified_ns: int
    project_id: str = ""
    version: str = ""


class ContentPackManager:
    def __init__(self, game_directory: Path, kind: str):
        if kind not in CONTENT_FOLDERS:
            raise ValueError("Choose shaders or texture packs.")
        self.game_directory = Path(game_directory).resolve()
        self.kind = kind
        self.directory = self.game_directory / CONTENT_FOLDERS[kind]
        self.data_directory = launcher_data_dir(self.game_directory)
        self.index_path = self.data_directory / f"{kind}-downloads.json"
        self._lock = _directory_lock(self.directory)

    def _check_directory(self) -> None:
        if not self.game_directory.is_dir():
            raise ValueError("This profile's game folder is missing. Restore it before installing packs.")
        if self.directory.is_symlink() or self.directory.resolve().parent != self.game_directory:
            raise ValueError("The content folder points outside this profile.")

    def _records(self) -> dict:
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except (ValueError, UnicodeError) as error:
            raise ValueError("The downloaded pack records could not be read.") from error

    def scan(self) -> list[LocalContentPack]:
        with self._lock:
            self._check_directory()
            records = self._records()
            items = []
            if not self.directory.is_dir():
                return items
            for path in self.directory.iterdir():
                if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".zip":
                    continue
                try:
                    safe_archive_name(path.name, ("zip",))
                except ValueError:
                    continue
                info = path.stat()
                record = records.get(path.name, {})
                if not isinstance(record, dict) or record.get("size") != info.st_size or record.get("modified_ns") != info.st_mtime_ns:
                    record = {}
                items.append(LocalContentPack(path.name, str(record.get("title") or path.stem), info.st_size,
                                              info.st_mtime_ns, str(record.get("project_id") or ""),
                                              str(record.get("version") or "")))
            return sorted(items, key=lambda item: item.title.casefold())

    def install(self, client, project: dict, version: dict, minecraft_version: str,
                progress: Callable = lambda message: None, *, can_commit: Callable[[], bool] = lambda: True) -> Path:
        project_id = project.get("project_id") or project.get("id")
        if (not project_id or project.get("project_type") != self.kind or version.get("project_id") != project_id
                or minecraft_version not in version.get("game_versions", [])):
            raise ValueError("Choose a pack version compatible with this profile.")
        file = {**primary_content_file(version), "content_type": self.kind}
        filename = safe_archive_name(file.get("filename"), ("zip",))
        with self._lock:
            self._check_directory()
            self.data_directory.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="content-download-", dir=self.data_directory) as temporary:
                staged = Path(temporary) / filename
                checksum = PackInstaller(self.game_directory, client=client).download_file(file, staged, progress)
                with zipfile.ZipFile(staged) as archive:
                    names = archive.namelist()
                    valid = "pack.mcmeta" in names if self.kind == "resourcepack" else any(name.startswith("shaders/") and not name.endswith("/") for name in names)
                    if not valid:
                        raise ValueError("This ZIP does not contain a usable shader or texture pack.")
                if not can_commit():
                    raise ValueError("Close Minecraft before installing packs.")
                self._check_directory()
                self.directory.mkdir(exist_ok=True)
                destination = self.directory / filename
                if destination.exists() or destination.is_symlink():
                    raise ValueError(f"{filename} already exists. Remove it before installing this version.")
                records = self._records()
                staged.replace(destination)
                try:
                    info = destination.stat()
                    records[filename] = {"title": project.get("title") or filename, "project_id": project_id,
                                         "version": version.get("version_number") or version.get("name", ""),
                                         "version_id": version.get("id"), "sha512": checksum,
                                         "size": info.st_size, "modified_ns": info.st_mtime_ns}
                    _atomic_write(self.index_path, json.dumps(records, ensure_ascii=False, indent=2).encode("utf-8"))
                except BaseException:
                    destination.unlink(missing_ok=True)
                    raise
                return destination

    def remove(self, item: LocalContentPack, *, can_commit: Callable[[], bool] = lambda: True) -> None:
        with self._lock:
            self._check_directory()
            path = self.directory / safe_archive_name(item.filename, ("zip",))
            if path.is_symlink() or not path.is_file():
                raise ValueError("This pack file is missing or has moved.")
            info = path.stat()
            if info.st_size != item.size or info.st_mtime_ns != item.modified_ns:
                raise ValueError("This pack changed. Refresh the list before removing it.")
            records = self._records()
            record = records.get(item.filename, {})
            if isinstance(record, dict) and record.get("sha512") and _digest(path) != record["sha512"]:
                raise ValueError("This pack changed. Refresh the list before removing it.")
            if not can_commit():
                raise ValueError("Close Minecraft before removing packs.")
            path.unlink()
            # Missing files are ignored by scan; a stale record never recreates one.
            records.pop(item.filename, None)
            self.data_directory.mkdir(parents=True, exist_ok=True)
            _atomic_write(self.index_path, json.dumps(records, ensure_ascii=False, indent=2).encode("utf-8"))
