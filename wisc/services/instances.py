"""Launcher services shared by the current interface."""

import queue
import shutil
import socket
import threading
import time
from pathlib import Path

from wisc.core.credentials import redact_credentials


def remove_profile_record(profile_id: str, *, delete_files: bool = False) -> dict:
    """Remove a profile, preserving game files unless its own folder is selected."""
    from wisc.core import storage
    from wisc.services.launcher import minecraft_directory, get_profile_game_directory, delete_external_profile
    from wisc.services.profiles import folder_is_referenced

    profiles = storage.load_installations()
    profile = next((item for item in profiles if item["id"] == profile_id), None)
    if profile is None:
        raise ValueError("This profile no longer exists.")
    folder = None
    if delete_files:
        if not profile.get("is_instance"):
            raise ValueError("Shared Minecraft files cannot be deleted with a profile.")
        folder = get_profile_game_directory(profile)
        root = (Path(minecraft_directory) / "instances").resolve()
        original = Path(profile.get("game_directory") or root / profile.get("instance_name", ""))
        linked = original.is_symlink() or (hasattr(original, "is_junction") and original.is_junction())
        if linked:
            raise ValueError("Linked instance folders must be removed manually.")
        if folder.parent != root or folder_is_referenced(folder, profiles, minecraft_directory, exclude_id=profile_id):
            raise ValueError("Only this profile's own, unshared instance folder can be deleted.")
    original_handled = storage.load_handled_external_profile_ids()
    handled = original_handled.copy()
    external_id = str(profile.get("external_profile_id") or "")
    if external_id:
        handled.add(external_id)
    remaining = [item for item in profiles if item["id"] != profile_id]
    if not storage.save_installations(remaining, handled):
        raise OSError("Could not save profile changes. The game files were preserved.")
    if folder and folder.is_dir():
        try:
            shutil.rmtree(folder)
        except OSError as error:
            # Preserve the profile as well as the remaining files if cleanup fails.
            storage.save_installations(profiles, original_handled)
            raise OSError("Could not remove all instance files. The profile was restored.") from error
    if external_id:
        delete_external_profile(external_id)
    return profile


def remove_installed_version(version_id: str) -> bool:
    """Remove only the selected runtime's files inside Minecraft's versions folder."""
    from wisc.services.launcher import minecraft_directory, invalidate_installed_versions_cache

    if (not version_id or version_id in (".", "..") or version_id.rstrip(". ") != version_id
            or Path(version_id).name != version_id or any(char in version_id for char in '/\\:')):
        return False
    root = (Path(minecraft_directory) / "versions").resolve()
    paths = [root / version_id, root / f"{version_id}.json", root / f"{version_id}.jar"]
    try:
        if any(path.resolve().parent != root or path.is_symlink() for path in paths):
            return False
        for path in paths:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
    except OSError:
        return False
    invalidate_installed_versions_cache()
    return True


def check_internet_connection(timeout=2.0):
    """Probe connectivity independently of the selected account type."""
    try:
        with socket.create_connection(("1.1.1.1", 443), timeout=timeout):
            return True
    except OSError:
        return False


def read_game_output(process, log_file, emit_lines, batch_size=20, flush_interval=0.1, sensitive_values=()):
    """Batch game output without delaying quiet streams until their next line."""
    if process.stdout is None:
        return
    messages = queue.Queue(maxsize=batch_size * 10)
    finished = object()
    stopped = threading.Event()

    def enqueue(value):
        while not stopped.is_set():
            try:
                messages.put(value, timeout=flush_interval)
                return
            except queue.Full:
                continue

    def read_lines():
        try:
            for line in process.stdout:
                if stopped.is_set():
                    break
                enqueue(line)
        except (OSError, ValueError):
            pass
        finally:
            enqueue(finished)

    reader = threading.Thread(target=read_lines, daemon=True)
    reader.start()
    pending = []
    deadline = None

    def flush():
        if not pending:
            return
        lines = pending.copy()
        pending.clear()
        if log_file is not None:
            try:
                log_file.writelines(lines)
                log_file.flush()
            except (OSError, ValueError):
                pass
        emit_lines(lines)

    try:
        while True:
            timeout = max(0.0, deadline - time.monotonic()) if deadline else None
            try:
                item = messages.get(timeout=timeout)
            except queue.Empty:
                flush()
                deadline = None
                continue
            if item is finished:
                flush()
                break
            pending.append(redact_credentials(item, sensitive_values))
            if deadline is None:
                deadline = time.monotonic() + flush_interval
            if len(pending) >= batch_size:
                flush()
                deadline = None
    finally:
        stopped.set()
        reader.join(timeout=1.0)


def sync_local_installations():
    """Add new local profiles while preserving existing installation settings."""
    from wisc.core import storage
    from wisc.services.launcher import (
        discover_local_instances,
        get_external_installations,
        get_installed_versions,
        get_local_version_catalog,
        import_external_installations,
        minecraft_directory,
    )
    from wisc.services.profiles import recover_prepared_profiles

    recover_prepared_profiles(minecraft_directory, storage)

    installations = storage.load_installations()
    external = get_external_installations()
    external_ids = {str(profile["id"]) for profile in external}
    handled = storage.load_handled_external_profile_ids().intersection(external_ids)
    installed = get_installed_versions(force_refresh=True)
    catalog, _ = get_local_version_catalog()
    installations, handled, imported = import_external_installations(
        installations, handled, installed, external, catalog
    )
    installations, discovered = discover_local_instances(
        minecraft_directory, installations, installed, catalog
    )
    changed = imported or discovered
    if changed and not storage.save_installations(installations, handled):
        raise OSError("Could not save imported Minecraft installations.")

    return changed


def installation_sources_stamp(mc_dir):
    """Watch profile files and instance metadata without rescanning their contents."""
    root = Path(mc_dir)
    instances = root / "instances"
    paths = [root / "launcher_profiles.json", instances]
    try:
        for folder in sorted(instances.iterdir()):
            if folder.is_dir():
                paths.append(folder)
                paths.extend(folder / name for name in (
                    "instance.json", "profile.json", "minecraft_instance.json", "logs/latest.log"
                ))
    except OSError:
        pass
    stamp = []
    for path in paths:
        try:
            stat = path.stat()
            stamp.append((str(path), stat.st_mtime_ns, stat.st_size))
        except OSError:
            stamp.append((str(path), None, None))
    return tuple(stamp)
