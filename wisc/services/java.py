"""Managed Mojang Java runtimes for Minecraft versions.

The launcher library already prefers ``<minecraft>/runtime/<component>`` when it
builds a launch command, so this module only reports what a version needs and
installs the matching runtime when it is missing.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Callable

import minecraft_launcher_lib
from minecraft_launcher_lib import runtime as mc_runtime

# Loader profiles inherit their Java requirement from the parent version JSON.
_MAX_INHERIT_DEPTH = 4
_RELEASE_VERSION = re.compile(r'^JAVA_VERSION="([^"]+)"', re.MULTILINE)
_PROBE_VERSION = re.compile(r'version "([^"]+)"')

_major_cache: dict[str, int | None] = {}


class RuntimeDownloadCancelled(Exception):
    """Raised when a Java runtime download is cancelled."""


def _minecraft_root(mc_dir: str | os.PathLike | None) -> Path:
    if mc_dir:
        return Path(mc_dir)
    return Path(minecraft_launcher_lib.utils.get_minecraft_directory())


def _version_document(version_id: str, mc_dir: Path) -> dict | None:
    if not version_id:
        return None
    path = mc_dir / "versions" / version_id / f"{version_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def runtime_for_version(
    version_id: str,
    mc_dir: str | os.PathLike | None = None,
) -> tuple[str | None, int | None]:
    """Return the Mojang runtime component and Java major that a version needs."""
    root = _minecraft_root(mc_dir)
    current = str(version_id or "")
    seen: set[str] = set()
    for _ in range(_MAX_INHERIT_DEPTH):
        if not current or current in seen:
            break
        seen.add(current)
        document = _version_document(current, root)
        if document is None:
            break
        info = document.get("javaVersion")
        if isinstance(info, dict):
            component = info.get("component")
            major = info.get("majorVersion")
            if isinstance(component, str) and component and isinstance(major, int):
                return component, major
        parent = document.get("inheritsFrom")
        current = parent if isinstance(parent, str) else ""
    try:
        fallback = mc_runtime.get_version_runtime_information(str(version_id or ""), root)
    except Exception:
        fallback = None
    if fallback:
        return fallback.get("name"), fallback.get("javaMajorVersion")
    return None, None


def runtime_executable(
    component: str | None,
    mc_dir: str | os.PathLike | None = None,
) -> str | None:
    """Return the installed executable for a managed runtime, if any."""
    if not component:
        return None
    try:
        path = mc_runtime.get_executable_path(component, _minecraft_root(mc_dir))
    except Exception:
        return None
    return str(path) if path else None


def installed_runtimes(mc_dir: str | os.PathLike | None = None) -> list[str]:
    """Return the managed runtime component names stored in the game directory."""
    try:
        return list(mc_runtime.get_installed_jvm_runtimes(_minecraft_root(mc_dir)))
    except Exception:
        return []


def _raise_if_cancelled(cancel_event) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeDownloadCancelled("Java runtime download cancelled.")


def ensure_runtime(
    component: str | None,
    mc_dir: str | os.PathLike | None = None,
    callback: dict | None = None,
    cancel_event=None,
) -> str | None:
    """Install ``component`` when missing and return its executable path."""
    if not component:
        return None
    root = _minecraft_root(mc_dir)
    existing = runtime_executable(component, root)
    if existing:
        return existing
    progress = dict(callback or {})

    def guarded(handler: Callable[..., None]) -> Callable[..., None]:
        def run(*args) -> None:
            _raise_if_cancelled(cancel_event)
            handler(*args)
            _raise_if_cancelled(cancel_event)

        return run

    wrapped = {
        name: guarded(progress.get(name, lambda *_: None))
        for name in ("setStatus", "setProgress", "setMax")
    }
    try:
        mc_runtime.install_jvm_runtime(component, root, wrapped)
    except RuntimeDownloadCancelled:
        raise
    except Exception as error:
        detail = str(error) or error.__class__.__name__
        raise RuntimeError(
            f"Could not download the Java runtime {component}: {detail}"
        ) from error
    return runtime_executable(component, root)


def _parse_major(version: str) -> int | None:
    cleaned = version.strip().strip('"')
    if not cleaned:
        return None
    if cleaned.startswith("1."):
        parts = cleaned.split(".")
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
        return None
    match = re.match(r"^(\d+)", cleaned)
    return int(match.group(1)) if match else None


def _release_version(java_path: str) -> str | None:
    candidate = Path(java_path)
    for folder in (candidate.parent.parent, candidate.parent):
        try:
            text = (folder / "release").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        match = _RELEASE_VERSION.search(text)
        if match:
            return match.group(1)
    return None


def _probe_version(java_path: str) -> str | None:
    try:
        result = subprocess.run(
            [java_path, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = _PROBE_VERSION.search(f"{result.stdout}\n{result.stderr}")
    return match.group(1) if match else None


def java_major(java_path: str | os.PathLike | None) -> int | None:
    """Return the Java feature version, e.g. 8 for 1.8.0_402 and 21 for 21.0.5."""
    text = str(java_path or "").strip()
    if not text:
        return None
    try:
        key = str(Path(text).resolve())
    except OSError:
        key = text
    if key in _major_cache:
        return _major_cache[key]
    major = _parse_major(_release_version(key) or _probe_version(key) or "")
    _major_cache[key] = major
    return major
