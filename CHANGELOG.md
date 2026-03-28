# Changelog

All notable changes to this project will be documented in this file.

The format follows Keep a Changelog, and this project adheres to
Semantic Versioning.

## [0.2.2] - 2026-03-28

### Added

- Added `Progress.log_stream()`, a file-like adapter for routing `print(...)`
  and logger output through the progress bar without breaking the live TTY
  layout.

### Fixed

- Made non-TTY rendering respect `refresh_interval` during iteration without
  flooding logs with duplicate periodic frames.
- Forced a final `100%` progress snapshot before the summary when `total` is
  known and the last completed frame had not been rendered yet.
- Started elapsed time, rate, and ETA measurement when iteration actually
  begins instead of when the `Progress` object is instantiated.
- Flushed pending partial writes from the progress log stream before printing
  the final summary, so intermediate logs remain above the summary and no
  orphaned bar is left behind.

### Changed

- Documented the TTY vs non-TTY rendering behavior in the README.
- Expanded the regression test suite for non-TTY rendering, final frame
  emission, and delayed-start timing.
- Clarified and documented the recommended way to emit logs while a live
  progress bar is active: `p.write(...)` or `file=p.log_stream()`.
