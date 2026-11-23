"""Offline Minecraft update artwork for the launcher's shared background."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from wisc.core.paths import ASSETS_DIR
from wisc.services.banners import get_custom_instance_banner


_UPDATE_COVERS = {
    12: "world-of-color",
    13: "update-aquatic",
    14: "village-and-pillage",
    15: "buzzy-bees",
    16: "nether-update",
    17: "caves-and-cliffs-1",
    18: "caves-and-cliffs-2",
    19: "the-wild-update",
}
_DROP_COVERS = {
    20: ((0, "trails-and-tales"), (3, "bats-and-pots"), (5, "armored-paws")),
    21: ((0, "tricky-trials"), (2, "bundles-of-bravery"),
         (4, "the-garden-awakens"), (5, "spring-to-life"),
         (6, "chase-the-skies"), (9, "the-copper-age"), (11, "mounts-of-mayhem")),
}
_YEAR_COVERS = {1: "tiny-takeover", 2: "chaos-cubed", 3: "wilderness-bound"}
_RELEASE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?(?:-(?:pre|rc)\d+)?")
_LOADER_VERSION = re.compile(r"(?<![\d.])((?:1|26)\.\d+(?:\.\d+)?(?:-(?:pre|rc)\d+)?)(?![\d.])")


@dataclass(frozen=True)
class BackgroundArtwork:
    source: str
    frosted_source: str | None
    custom_revision: tuple[int, int] | None = None


def minecraft_version(target: dict | None) -> str:
    """Prefer profile metadata; strip common loader wrappers for older profiles."""
    if not target:
        return ""
    explicit = str(target.get("minecraft_version") or "").strip()
    if explicit:
        return explicit
    version_id = str(target.get("version_id") or "").strip()
    if _RELEASE.fullmatch(version_id):
        return version_id
    matches = _LOADER_VERSION.findall(version_id)
    if matches:
        return matches[-1] if version_id.startswith(("fabric-loader-", "quilt-loader-")) else matches[0]
    return version_id


def cover_name(version: str | None) -> str:
    """Patch releases share their update/drop; unknown versions use Java art."""
    cover = "java-edition"
    match = _RELEASE.fullmatch(version or "")
    if match:
        major, minor, patch = (int(part or 0) for part in match.groups())
        if major == 1:
            cover = _UPDATE_COVERS.get(minor, cover)
            for since, drop in _DROP_COVERS.get(minor, ()):
                if patch >= since:
                    cover = drop
        elif major == 26:
            cover = _YEAR_COVERS.get(minor, cover)
    return cover


def resolve_background_artwork(target: dict | None, minecraft_directory: str | None = None,
                               *, assets_dir: Path = ASSETS_DIR) -> BackgroundArtwork:
    """Resolve custom art or a bundled cover without downloading banner images."""
    try:
        custom = get_custom_instance_banner(target, minecraft_directory)
    except OSError:
        custom = None
    if custom:
        try:
            info = Path(custom).stat()
        except OSError:
            pass
        else:
            return BackgroundArtwork(custom, None, (info.st_mtime_ns, info.st_size))

    directory = assets_dir / "version-art"
    cover = cover_name(minecraft_version(target))
    source = directory / f"{cover}.webp"
    if not source.is_file():
        source = directory / "java-edition.webp"
    frosted = directory / "blurred" / source.name
    return BackgroundArtwork(str(source), str(frosted) if frosted.is_file() else None)
