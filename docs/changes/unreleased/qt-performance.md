### Changed

- Open the Qt launcher faster by building Home first, preparing Library in the background, and creating other pages and content details when needed.
- Use less memory by sharing bounded artwork caches, decoding covers in the background, and drawing only visible Library cards.
- Keep navigation and skin rotation responsive by limiting background workers and replacing obsolete render requests with the latest pose.

### Fixed

- Avoid the slow first-use font lookup for profile action menus, and release closed dialogs, finished tasks, and inactive card surfaces.
