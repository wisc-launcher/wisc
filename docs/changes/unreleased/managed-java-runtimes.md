### Added

- Java is downloaded automatically for each launched version, using the runtime
  Mojang publishes for it, so a correct Java installation is no longer a manual
  setup step. **Download Java** in Options > Java fetches it ahead of time.

### Fixed

- Launching a version that needs a newer Java now explains the mismatch in plain
  language instead of failing with an `UnsupportedClassVersionError`. Options >
  Java shows which Java the selected profile needs and whether it is installed.
