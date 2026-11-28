### Fixed

- Dynamic text on Home, Settings > Java, and Settings > About no longer wraps or
  reflows its card, so switching profiles or checking for updates moves nothing.
- The Mods notice strip, Settings > About update buttons, and the Logs counter keep
  their space, so messages and log counts no longer resize the surrounding layout.
- Home's library shelf updates cards in place instead of clearing and rebuilding the
  row, so selecting a profile no longer reshuffles the shelf.

### Changed

- The launcher window can shrink to 1000x620 while keeping the title bar and pages
  usable on smaller displays.
- Pages that are built the first time you open them (Skins, Settings, Mods), a mod's
  details view, and the profile editor appear fully drawn instead of playing the
  rise-and-settle wave over content that is still loading, so there is no
  half-animated snap. The wave still plays when you return to a page, reopen a mod's
  details, or reopen the profile editor.
