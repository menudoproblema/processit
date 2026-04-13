from __future__ import annotations

import asyncio
import contextlib
import io
import os
import shutil
import sys
import time

from typing import TYPE_CHECKING, TextIO, cast


if TYPE_CHECKING:
    from collections.abc import (
        AsyncIterable,
        AsyncIterator,
        Awaitable,
        Callable,
        Iterable,
    )


class _ProgressLogStream(io.TextIOBase):
    __slots__ = ('_buffer', '_progress')

    def __init__(self, progress: Progress[object]) -> None:
        self._progress = progress
        self._buffer = ''

    @property
    def encoding(self) -> str | None:
        return getattr(self._progress.stream, 'encoding', None)

    def isatty(self) -> bool:
        return self._progress._is_tty

    def writable(self) -> bool:
        return True

    def write(self, msg: str) -> int:
        if not isinstance(msg, str):
            msg = str(msg)

        if not msg:
            return 0

        self._buffer += msg
        self._flush_complete_lines()
        return len(msg)

    def flush(self) -> None:
        self.flush_pending()

    def close(self) -> None:
        self.flush()

    def flush_pending(self) -> None:
        if not self._buffer:
            return

        pending = self._buffer.removesuffix('\r')
        self._buffer = ''
        self._progress._write_message(pending, allow_blank=True)

    def _flush_complete_lines(self) -> None:
        while '\n' in self._buffer:
            line, self._buffer = self._buffer.split('\n', 1)
            self._progress._write_message(
                line.removesuffix('\r'),
                allow_blank=True,
            )


class Progress[T]:
    __slots__ = (
        '_is_tty',
        '_last_line_len',
        '_last_refresh',
        '_last_render_count',
        '_log_stream',
        '_next_render_at',
        '_prefix',
        '_refresh_task',
        '_started',
        '_stopped',
        '_summary_printed',
        'count',
        'desc',
        'iterable',
        'refresh_interval',
        'show_summary',
        'start_time',
        'stream',
        'total',
        'transient',
        'width',
    )

    def __init__(  # noqa: PLR0913
        self,
        iterable: Iterable[T] | AsyncIterable[T],
        total: int | None = None,
        *,
        desc: str = 'Processing',
        width: int = 30,
        stream: TextIO | None = None,
        refresh_interval: float = 0.1,
        show_summary: bool = True,
        transient: bool = False,
    ) -> None:
        self.iterable = iterable
        self.total = total
        self.desc = desc
        self.width = width
        self.stream = stream or sys.stderr
        self.refresh_interval = refresh_interval
        self.show_summary = show_summary
        self.transient = transient

        self.count = 0
        self.start_time = time.perf_counter()
        self._last_refresh = 0.0
        self._next_render_at = 0.0  # render inmediato al inicio
        self._refresh_task: asyncio.Task[None] | None = None
        self._summary_printed = False
        self._last_line_len = 0
        self._last_render_count = 0
        self._started = False
        self._stopped = False
        self._is_tty = bool(getattr(self.stream, 'isatty', lambda: False)())
        self._log_stream: _ProgressLogStream | None = None
        self._prefix = f'{self.desc} '

    def _start_rendering(self) -> None:
        self._started = True
        self._stopped = False
        self.start_time = time.perf_counter()
        self._last_refresh = 0.0
        self._next_render_at = 0.0
        self._last_line_len = 0
        self._last_render_count = -1
        self._render(force=True)
        if self._is_tty:
            self._refresh_task = asyncio.create_task(
                self._refresh_periodically(),
            )

    def write(self, msg: str = '') -> None:
        """Print a message above the live bar and re-render it."""
        self._write_message(msg)

    def log_stream(self) -> TextIO:
        """Return a file-like stream that logs above the live bar."""
        if self._log_stream is None:
            progress = cast('Progress[object]', self)
            self._log_stream = _ProgressLogStream(progress)
        return cast('TextIO', self._log_stream)

    def _write_message(
        self,
        msg: str = '',
        *,
        allow_blank: bool = False,
    ) -> None:
        if self._stopped:
            return
        self._clear_line()
        if msg or allow_blank:
            if not msg.endswith('\n'):
                msg += '\n'
            self.stream.write(msg)
            self.stream.flush()
        self._render(force=True)

    def _flush_log_stream(self) -> None:
        if self._log_stream is not None:
            self._log_stream.flush_pending()

    async def _stop_refresh_task(self) -> None:
        if self._refresh_task is None:
            return

        self._refresh_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._refresh_task
        self._refresh_task = None

    async def amap[R](
        self,
        mapper: Callable[[T], Awaitable[R]],
        *,
        concurrency: int = 10,
        preserve_order: bool = False,
    ) -> AsyncIterator[R]:
        """Apply an async mapper over items with controlled concurrency.

        This method executes `mapper(item)` concurrently for elements in the
        wrapped iterable, up to the specified concurrency limit. It integrates
        with the progress bar, updating progress as tasks complete.

        Parameters
        ----------
        mapper : Callable[[T], Awaitable[R]]
            Asynchronous function applied to each item. Must return an
            awaitable.

        concurrency : int, optional
            Maximum number of concurrent tasks (default: 10). Must be >= 1.

        preserve_order : bool, optional
            Controls result ordering:

            - False (default): yield results as tasks complete (higher
              throughput).
            - True: yield results in input order (may wait for slower tasks).

        Yields:
        ------
        R
            Result of `await mapper(item)` for each element.

        Raises:
        ------
        ValueError
            If `concurrency < 1`.

        Notes:
        -----
        - Intended for IO-bound workloads (e.g., HTTP calls, async DB queries,
          async file operations).
        - With `preserve_order=True`, results are buffered until completion,
          increasing memory usage for large iterables.
        - Blocking operations inside `mapper` will block the event loop unless
          moved to a thread (e.g., via `asyncio.to_thread`).
        """
        if concurrency < 1:
            msg = 'concurrency must be >= 1'
            raise ValueError(msg)

        sem = asyncio.Semaphore(concurrency)

        async def run_one(idx: int, item: T) -> tuple[int, R]:
            async with sem:
                res = await mapper(item)
                return idx, res

        # Start the refresh task if it hasn't been started
        # yet (same as in __aiter__)
        started_here = False
        if not self._started:
            self._start_rendering()
            started_here = True

        try:
            tasks: list[asyncio.Task[tuple[int, R]]] = []
            idx = 0

            async def push(item: T) -> None:
                nonlocal idx
                tasks.append(asyncio.create_task(run_one(idx, item)))
                idx += 1

            # Feed tasks from the underlying iterable (sync or async)
            if hasattr(self.iterable, '__aiter__'):
                async for item in cast('AsyncIterable[T]', self.iterable):
                    await push(item)
            else:
                for item in cast('Iterable[T]', self.iterable):
                    await push(item)
                    # Yield control to the event loop so the refresh
                    # task can run
                    await asyncio.sleep(0)

            if preserve_order:
                # Wait for all tasks, then sort by index to preserve
                # input order
                results = await asyncio.gather(*tasks)
                results.sort(key=lambda x: x[0])
                for _, value in results:
                    self.count += 1
                    self._render()
                    yield value
            else:
                # Yield results as tasks complete
                for fut in asyncio.as_completed(tasks):
                    _, value = await fut
                    self.count += 1
                    self._render()
                    yield value

        finally:
            if started_here:
                await self._stop_refresh_task()
            self._print_summary_if_needed()
            self._started = False

    def _format_elapsed(self, seconds: float) -> str:
        """Return hh:mm:ss, mm:ss or ss.s depending on duration."""
        if seconds < 60:  # noqa: PLR2004
            return f'{seconds:04.1f}s'
        minutes, secs = divmod(int(seconds), 60)
        if minutes < 60:  # noqa: PLR2004
            return f'{minutes:02d}:{secs:02d}'
        hours, minutes = divmod(minutes, 60)
        return f'{hours:02d}:{minutes:02d}:{secs:02d}'

    def _clip_text(self, text: str, max_len: int) -> str:
        if max_len <= 0:
            return ''
        if len(text) <= max_len:
            return text
        if max_len <= 3:  # noqa: PLR2004
            return '.' * max_len
        return text[: max_len - 3] + '...'

    def _terminal_columns(self) -> int | None:
        if not self._is_tty:
            return None

        get_terminal_size = getattr(self.stream, 'get_terminal_size', None)
        if callable(get_terminal_size):
            with contextlib.suppress(OSError, ValueError):
                size = get_terminal_size()
                columns = getattr(size, 'columns', 0)
                if columns > 0:
                    return columns

        fileno = getattr(self.stream, 'fileno', None)
        if callable(fileno):
            with contextlib.suppress(
                OSError,
                ValueError,
                io.UnsupportedOperation,
            ):
                columns = os.get_terminal_size(fileno()).columns
                if columns > 0:
                    return columns

        with contextlib.suppress(OSError, ValueError):
            columns = shutil.get_terminal_size(fallback=(80, 24)).columns
            if columns > 0:
                return columns

        return None

    def _tty_budget(self) -> int | None:
        columns = self._terminal_columns()
        if columns is None:
            return None
        # Evita escribir en la ultima columna para no disparar autowrap
        # en terminales estrechas.
        return max(columns - 1, 1)

    def _render_bar(self, frac: float, width: int) -> str:
        filled = int(width * frac)
        return f'[{"#" * filled}{"." * (width - filled)}]'

    def _fit_render_line(
        self,
        *,
        desc: str,
        tail_parts: list[str],
        budget: int,
        frac: float | None = None,
    ) -> str | None:
        desc_text = desc
        bar_width = self.width if frac is not None else 0

        while True:
            parts = [desc_text] if desc_text else []
            if frac is not None:
                parts.append(self._render_bar(frac, bar_width))
            parts.extend(part for part in tail_parts if part)
            line = ' '.join(parts)

            if len(line) <= budget:
                return line

            overflow = len(line) - budget
            if frac is not None and bar_width > 1:
                bar_width -= min(overflow, bar_width - 1)
                continue

            if desc_text:
                max_desc_len = max(len(desc_text) - overflow, 0)
                clipped = (
                    ''
                    if max_desc_len < 4  # noqa: PLR2004
                    else self._clip_text(desc_text, max_desc_len)
                )
                if clipped != desc_text:
                    desc_text = clipped
                    continue

            return None

    def _build_known_total_line(
        self,
        *,
        frac: float,
        percent: str,
        rate: float,
        elapsed_str: str,
        eta_str: str,
    ) -> str:
        budget = self._tty_budget()
        count_token = f'({self.count}/{self.total})'
        rate_token = f'{rate:.2f} it/s'
        eta_token = eta_str.removeprefix(' ')
        variants = [
            [percent, count_token, rate_token, elapsed_str, eta_token],
            [percent, count_token, rate_token, elapsed_str],
            [percent, count_token, elapsed_str],
            [percent, count_token],
            [f'{self.count}/{self.total}', elapsed_str],
            [f'{self.count}/{self.total}'],
        ]

        if budget is None:
            return self._fit_render_line(
                desc=self.desc,
                tail_parts=variants[0],
                budget=10_000,
                frac=frac,
            ) or ''

        bar_variants = 4
        for index, tail_parts in enumerate(variants):
            line = self._fit_render_line(
                desc=self.desc,
                tail_parts=tail_parts,
                budget=budget,
                frac=frac if index < bar_variants else None,
            )
            if line is not None:
                return line

        fallback = f'{self.desc} {self.count}/{self.total}'
        return self._clip_text(fallback, budget)

    def _build_unknown_total_line(
        self,
        *,
        rate: float,
        elapsed_str: str,
    ) -> str:
        budget = self._tty_budget()
        variants = [
            [f'{self.count} it', f'({rate:.2f} it/s {elapsed_str})'],
            [f'{self.count} it', elapsed_str],
            [f'{self.count} it'],
        ]

        if budget is None:
            return f'{self.desc} {variants[0][0]} {variants[0][1]}'

        for tail_parts in variants:
            line = self._fit_render_line(
                desc=self.desc,
                tail_parts=tail_parts,
                budget=budget,
            )
            if line is not None:
                return line

        return self._clip_text(f'{self.desc} {self.count} it', budget)

    def _write_line(self, text: str) -> None:
        if self._is_tty:
            # \r = return, \x1b[2K = clear whole line (ANSI)
            self.stream.write('\r\x1b[2K' + text)
            self.stream.flush()
            self._last_line_len = len(text)
        else:
            # non-TTY (StringIO/logs): one line per render for deterministic
            # tests/logs
            self.stream.write(text + '\n')
            self.stream.flush()
            self._last_line_len = len(text)

    def _clear_line(self) -> None:
        if self._is_tty:
            self.stream.write('\r\x1b[2K')
            self.stream.flush()
            self._last_line_len = 0
        else:
            # non-TTY: renders are on separate lines; nothing to clear
            pass

    def _should_render_final_state(self) -> bool:
        if self._last_render_count == self.count:
            return False

        # En TTY transient la linea activa se elimina al salir, asi que no
        # merece la pena forzar un ultimo render.
        return not (self.transient and self._is_tty)

    def _should_render(self, now: float) -> bool:
        # Permite render al inicio (_next_render_at=0) o si ha
        # pasado refresh_interval
        return now >= self._next_render_at or self._last_line_len == 0

    def _render(self, *, force: bool = False) -> None:
        if self._stopped:
            return

        now = time.perf_counter()
        if not force and not self._should_render(now):
            return

        elapsed = now - self.start_time
        rate = self.count / elapsed if elapsed > 0 else 0.0
        elapsed_str = self._format_elapsed(elapsed)

        eta_str = ''
        if self.total is not None and self.count > 0 and rate > 0:
            remaining = max(self.total - self.count, 0)
            eta = remaining / rate
            eta_str = f' ETA {self._format_elapsed(eta)}'

        if self.total is not None:
            frac = (
                1.0
                if self.total == 0
                else min(self.count / self.total, 1.0)
            )
            percent = f'{frac * 100:6.2f}%'
            line = self._build_known_total_line(
                frac=frac,
                percent=percent,
                rate=rate,
                elapsed_str=elapsed_str,
                eta_str=eta_str,
            )
        else:
            line = self._build_unknown_total_line(
                rate=rate,
                elapsed_str=elapsed_str,
            )

        self._write_line(line)
        self._last_render_count = self.count
        self._last_refresh = now
        self._next_render_at = now + self.refresh_interval

    def _print_summary_if_needed(self) -> None:
        self._flush_log_stream()
        if self._should_render_final_state():
            self._render(force=True)

        if self.transient:
            self._stopped = True
            self._clear_line()
            self._summary_printed = True
            return

        self._stopped = True
        if self.show_summary and not self._summary_printed:
            self._clear_line()

            elapsed = time.perf_counter() - self.start_time
            rate = self.count / elapsed if elapsed > 0 else 0.0
            elapsed_str = self._format_elapsed(elapsed)

            self.stream.write(
                f'{self.desc}: {self.count} it in {elapsed_str} '
                f'({rate:.2f} it/s)\n',
            )
            self.stream.flush()
            self._summary_printed = True

    async def _refresh_periodically(self) -> None:
        while not self._stopped:
            await asyncio.sleep(self.refresh_interval)
            if self._stopped:
                break
            self._render()

    async def __aenter__(self) -> Progress[T]:
        if not self._started:
            self._start_rendering()  # feedback inmediato
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._stop_refresh_task()
        self._print_summary_if_needed()
        self._started = False

    async def __aiter__(self) -> AsyncIterator[T]:
        started_here = False

        if not self._started:
            # feedback inmediato fuera de context manager
            self._start_rendering()
            started_here = True

        try:
            if hasattr(self.iterable, '__aiter__'):
                async for item in cast('AsyncIterable[T]', self.iterable):
                    self.count += 1
                    self._render()
                    yield item
            else:
                for item in cast('Iterable[T]', self.iterable):
                    self.count += 1
                    self._render()
                    yield item
                    # cede el loop para no bloquear el refresco
                    await asyncio.sleep(0)
        finally:
            if started_here:
                await self._stop_refresh_task()
            self._print_summary_if_needed()
            self._started = False


def progress[T](  # noqa: PLR0913
    iterable: Iterable[T] | AsyncIterable[T],
    total: int | None = None,
    *,
    desc: str = 'Processing',
    width: int = 30,
    refresh_interval: float = 0.1,
    show_summary: bool = True,
    transient: bool = False,
    stream: TextIO | None = None,
) -> Progress[T]:
    """Wrap an iterable or async iterable with a progress bar.

    Parameters
    ----------
    iterable: Iterable[T] | AsyncIterable[T]
        The iterable or async iterable to iterate over.
    total: int | None, optional
        Total number of elements. If not provided and `iterable` has
        `__len__`, it will be inferred automatically. Otherwise, ETA
        will not be displayed.
    desc: str, optional
        A short description displayed before the progress bar.
    width: int, optional
        The width (in characters) of the progress bar (default: 30).
    refresh_interval: float, optional
        Minimum time interval in seconds between display refreshes.
    show_summary: bool, optional
        Whether to print a final summary line showing total iterations,
        total time, and iteration rate (default: True).
    transient: bool, optional
        Whether to remove the live bar when the iteration finishes. When
        enabled, it also suppresses the final summary line. This only
        clears the terminal in TTY streams; non-TTY streams keep the
        already emitted snapshots (default: False).
    stream: TextIO | None, optional
        Output stream to render the bar (default: sys.stderr).

    Yields:
    ------
    T
        Each element from the iterable or async iterable, in order.
    """
    # Infer total if possible
    if total is None and hasattr(iterable, '__len__'):
        try:
            total = len(iterable)  # type: ignore[arg-type]
        except Exception:
            total = None

    return Progress(
        iterable,
        total,
        desc=desc,
        width=width,
        refresh_interval=refresh_interval,
        show_summary=show_summary,
        transient=transient,
        stream=stream,
    )


def track_as_completed[T](  # noqa: PLR0913
    tasks: Iterable[Awaitable[T]],
    *,
    total: int | None = None,
    desc: str = 'Processing',
    width: int = 30,
    refresh_interval: float = 0.1,
    show_summary: bool = True,
    transient: bool = False,
    cancel_pending: bool = False,
    stream: TextIO | None = None,
) -> Progress[asyncio.Future[T]]:
    """Iterate results as tasks complete, with a progress bar.

    Parameters
    ----------
    tasks: Iterable[Awaitable[T]]
        Awaitables or tasks to run/track.
    total: int | None, optional
        Total number of tasks. If not provided and `tasks` has `__len__`,
        it will be inferred. Otherwise, ETA will not be shown.
    desc: str
        Short description prefix for the bar.
    width: int
        Progress bar width (characters).
    refresh_interval: float
        Seconds between refreshes.
    show_summary: bool
        Whether to print a final summary line.
    transient: bool
        Whether to remove the live bar when all tasks complete. When
        enabled, it also suppresses the final summary line.
    cancel_pending: bool
        Whether to cancel unfinished tasks if the consumer stops
        iterating before all results have been yielded.
    stream: TextIO | None, optional
        Output stream to render the bar (default: sys.stderr).

    Returns:
    -------
    Progress[Future[T]]
        An async-iterable of **futures** (await them in the loop).

    Notes:
    -----
    We *avoid* passing the synchronous iterator from
    `asyncio.as_completed(...)` directly to `Progress`, since its `next()` can
    block the event loop. Instead, we drive completion asynchronously using
    `asyncio.wait(FIRST_COMPLETED)`.

    Pending tasks are left running by default if the consumer stops early.
    Set `cancel_pending=True` to cancel them during generator cleanup.
    """
    # Infer total if possible
    if total is None and hasattr(tasks, '__len__'):
        try:
            total = len(tasks)  # type: ignore[arg-type]
        except Exception:
            total = None

    async def _as_completed_async() -> AsyncIterable[asyncio.Future[T]]:
        pending: set[asyncio.Future[T]] = {
            asyncio.ensure_future(t)
            for t in tasks  # type: ignore[arg-type]
        }
        try:
            while pending:
                done, pending = await asyncio.wait(
                    pending,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for fut in done:
                    yield fut
        finally:
            if cancel_pending and pending:
                for fut in pending:
                    fut.cancel()
                await asyncio.gather(*pending, return_exceptions=True)

    return progress(
        _as_completed_async(),
        total=total,
        desc=desc,
        width=width,
        refresh_interval=refresh_interval,
        show_summary=show_summary,
        transient=transient,
        stream=stream,
    )
