"""Resolve source and packaged resources without depending on the working directory."""

import json
import os
from pathlib import Path
import sys
import tempfile
import threading


# PyInstaller gives packaged modules paths below _internal/wisc/ too.
RESOURCE_ROOT = Path(__file__).resolve().parents[2]
ASSETS_DIR = RESOURCE_ROOT / ".assets"
DATA_DIRECTORY_NAMES = ("wisc", "gr8launcher")
_DATA_MIGRATION_LOCK = threading.RLock()


def _rebase_data_paths(value, legacy: Path, current: Path):
    """Rewrite only absolute references into the old launcher data directory."""
    if isinstance(value, str):
        old, new = str(legacy.resolve()), str(current.resolve())
        if os.path.normcase(value) == os.path.normcase(old):
            return new
        for separator in ("/", "\\"):
            prefix = old + separator
            if os.path.normcase(value[:len(prefix)]) == os.path.normcase(prefix):
                return new + value[len(old):]
        return value
    if isinstance(value, list):
        return [_rebase_data_paths(item, legacy, current) for item in value]
    if isinstance(value, dict):
        return {key: _rebase_data_paths(item, legacy, current) for key, item in value.items()}
    return value


def _write_migration_file(path: Path, data: bytes) -> None:
    """Replace a JSON file atomically, keeping original files for rollback."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix="wisc-migration-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _migrate_launcher_directory(legacy: Path, current: Path) -> bool:
    """Move data on the same volume after preparing all path changes.

    Existing Wisc directories win. Failed rewrites leave the original directory
    usable; no profile, cache, credential reference, or unknown file is deleted.
    """
    prepared = []
    written = []
    try:
        for path in legacy.rglob("*.json"):
            if path.is_symlink() or not path.is_file():
                continue
            original = path.read_bytes()
            try:
                data = json.loads(original)
            except (ValueError, UnicodeError):
                continue
            rebased = _rebase_data_paths(data, legacy, current)
            if rebased != data:
                prepared.append((path, original, json.dumps(rebased, ensure_ascii=False, indent=2).encode("utf-8")))
        for path, original, updated in prepared:
            _write_migration_file(path, updated)
            written.append((path, original))
        if current.exists():
            raise FileExistsError("Wisc data already exists.")
        legacy.rename(current)
        return True
    except OSError:
        for path, original in reversed(written):
            try:
                _write_migration_file(path, original)
            except OSError:
                pass
        return False


def launcher_data_dir(minecraft_directory: str | Path) -> Path:
    """Use Wisc data and migrate an existing Gr8 folder without losing files."""
    root = Path(minecraft_directory)
    current, legacy = (root / name for name in DATA_DIRECTORY_NAMES)
    with _DATA_MIGRATION_LOCK:
        if current.is_dir():
            return current
        if legacy.is_dir():
            if not legacy.is_symlink() and _migrate_launcher_directory(legacy, current):
                return current
            # Keep existing data usable if a lock or permission blocks migration.
            return legacy
        return current


def application_root() -> Path:
    """Return the install directory for a frozen app, or the source root."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent.resolve()
    return RESOURCE_ROOT
