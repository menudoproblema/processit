# Changelog

All notable changes to this project will be documented in this file.

The format follows Keep a Changelog, and this project adheres to
Semantic Versioning.

## [Unreleased]

### Added

- Added a GitHub Actions CI workflow to run Ruff, the progress test suite,
  and package build validation on pushes and pull requests.

### Fixed

- Kept live TTY renders within the available terminal width by shrinking the
  bar and clipping the description when needed, avoiding wrapped fragments
  after resizes or in narrow terminals.

### Changed

- Documented the narrow-terminal TTY behavior in the README.
- Expanded regression coverage for narrow TTY rendering so frames stay within
  the available columns while preserving progress metrics.

## [0.3.0] - 2026-04-12

### Added

- Added a `transient` option to `progress(...)`, `track_as_completed(...)`,
  and `Progress` to remove the live bar on completion in TTY streams while
  suppressing the final summary.
- Added `cancel_pending=False` to `track_as_completed(...)` so callers can
  opt into cancelling unfinished tasks when they stop consuming results
  early.

### Fixed

- Decoupled progress shutdown from summary emission so the internal stopped
  state is always finalized even when `show_summary=False`.
- Preserved the final completed snapshot when summaries are disabled, while
  still clearing the active line for transient TTY runs.
- Treated `total=0` as a known completed total, rendering a final `100%`
  `(0/0)` frame instead of falling back to the unknown-total format.

### Changed

- Documented `transient=True` behavior in the README for TTY and non-TTY
  streams.
- Clarified in the README that `show_summary=False` preserves the final
  frame unless `transient=True` is also set.
- Expanded regression coverage for transient mode, optional cancellation of
  pending tasks, `total=0`, and the `show_summary=False` completion path.

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
