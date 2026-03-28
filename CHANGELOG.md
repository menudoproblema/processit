# Changelog

All notable changes to this project will be documented in this file.

The format follows Keep a Changelog, and this project adheres to
Semantic Versioning.

## [0.2.1] - 2026-03-28

### Fixed

- Made non-TTY rendering respect `refresh_interval` during iteration without
  flooding logs with duplicate periodic frames.
- Forced a final `100%` progress snapshot before the summary when `total` is
  known and the last completed frame had not been rendered yet.
- Started elapsed time, rate, and ETA measurement when iteration actually
  begins instead of when the `Progress` object is instantiated.

### Changed

- Documented the TTY vs non-TTY rendering behavior in the README.
- Expanded the regression test suite for non-TTY rendering, final frame
  emission, and delayed-start timing.
