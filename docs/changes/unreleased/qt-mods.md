### Added

- Browse Mods, Modpacks, Shaders, and Texture Packs in the Qt launcher, with Modrinth and CurseForge search, sorting, pagination, documentation, galleries, and version history.
- Manage mods in saved instances: add local JARs, enable or disable files, remove with Undo, check updates, and review dependencies or update batches before installing.
- Import modpacks into separate instances and install compatible shader and texture packs, including verified manual CurseForge downloads.

### Changed

- Mod rows stay neutral when clicked, with borderless controls and clean on/off switches for enabling and disabling mods. Button focus uses a subtle fill instead of an outline.
- Content lists render visible rows and load artwork through bounded caches. Background searches keep only the latest pending request, preserving queries and scroll position across navigation.
- Confirmed content downloads show progress and cancellation across Qt tabs, retaining the existing compatibility, backup, and rollback safeguards.
