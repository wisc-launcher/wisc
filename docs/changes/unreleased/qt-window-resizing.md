### Fixed

- Eliminate resize lag and white border trailing artifacts during window resizing by enabling Windows DWM immersive dark mode, setting dark window class backgrounds, intercepting background erasure, and preserving client buffers in non-client calculations without redundant synchronous repaints.
