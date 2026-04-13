from __future__ import annotations

import asyncio
import io
import os

from typing import TYPE_CHECKING

import pytest

from processit.progress import Progress, progress, track_as_completed


if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator


# -----------------------------
# Helpers
# -----------------------------


def _strip_ansi(s: str) -> str:
    # El progreso usa \r y \x1b[2K; limpiamos para aserciones más simples
    s = s.replace('\r', '')
    return s.replace('\x1b[2K', '')


def _last_nonempty_line(buf: str) -> str:
    for line in reversed(buf.splitlines()):
        if line.strip():
            return line
    return ''


class _TTYStringIO(io.StringIO):
    def isatty(self) -> bool:
        return True


class _SizedTTYStringIO(_TTYStringIO):
    def __init__(self, columns: int) -> None:
        super().__init__()
        self.columns = columns

    def get_terminal_size(self):
        return os.terminal_size((self.columns, 24))


def _tty_frames(buf: str) -> list[str]:
    frames: list[str] = []
    for chunk in buf.split('\r\x1b[2K')[1:]:
        if not chunk:
            continue
        frame = chunk.split('\r', 1)[0].split('\n', 1)[0]
        if frame:
            frames.append(frame)
    return frames

def _render_tty_screen(buf: str) -> list[str]:
    lines: list[str] = []
    current: list[str] = []
    cursor = 0
    idx = 0

    while idx < len(buf):
        if buf.startswith('\x1b[2K', idx):
            current = []
            cursor = 0
            idx += 4
            continue

        char = buf[idx]
        idx += 1

        if char == '\r':
            cursor = 0
            continue

        if char == '\n':
            lines.append(''.join(current))
            current = []
            cursor = 0
            continue

        if cursor == len(current):
            current.append(char)
        else:
            current[cursor] = char
        cursor += 1

    if current:
        lines.append(''.join(current))

    return [line for line in lines if line.strip()]


# -----------------------------
# Synchronous iterable cases
# -----------------------------


@pytest.mark.asyncio
async def test_sync_iterable_basic_summary_only_once():
    stream = io.StringIO()

    def numbers() -> Iterator[int]:
        yield from range(5)

    # Consumo como async for (la clase cede el loop con await asyncio.sleep(0))
    async for _ in progress(
        numbers(),
        desc='Numbers',
        total=5,
        stream=stream,
        refresh_interval=1.0,
    ):
        await asyncio.sleep(0)

    out = _strip_ansi(stream.getvalue())
    # Debe haber un único resumen final
    assert out.count('Numbers: 5 it in ') == 1
    assert 'it/s' in out


@pytest.mark.asyncio
async def test_non_tty_respects_refresh_interval():
    stream = io.StringIO()
    expected_bar_frames = 2

    def numbers() -> Iterator[int]:
        yield from range(20)

    async for _ in progress(
        numbers(),
        desc='NonTTY',
        total=20,
        stream=stream,
        refresh_interval=10.0,
    ):
        await asyncio.sleep(0)

    out = _strip_ansi(stream.getvalue())
    assert out.count('NonTTY [') == expected_bar_frames
    assert 'NonTTY [##############################] 100.00% (20/20)' in out
    assert out.count('NonTTY: 20 it in ') == 1


@pytest.mark.asyncio
async def test_non_tty_renders_final_complete_frame_before_summary():
    stream = io.StringIO()
    data = list(range(3))

    async for _ in progress(
        data,
        desc='Final',
        total=3,
        stream=stream,
        refresh_interval=10.0,
    ):
        await asyncio.sleep(0)

    lines = [
        line for line in _strip_ansi(stream.getvalue()).splitlines() if line
    ]
    expected_complete = 'Final [##############################] 100.00% (3/3)'
    assert any(expected_complete in line for line in lines)
    assert lines[-1].startswith('Final: 3 it in ')


@pytest.mark.asyncio
async def test_tty_transient_clears_bar_without_summary():
    stream = _TTYStringIO()

    async for _ in progress(
        [1, 2, 3],
        desc='Transient',
        total=3,
        stream=stream,
        refresh_interval=10.0,
        transient=True,
    ):
        await asyncio.sleep(0)

    out = stream.getvalue()

    assert _render_tty_screen(out) == []
    assert 'Transient: 3 it in ' not in out


@pytest.mark.asyncio
async def test_tty_keeps_each_frame_within_terminal_width():
    columns = 50
    stream = _SizedTTYStringIO(columns=columns)

    async for _ in progress(
        range(4),
        desc='Migrando dispatches legacy',
        total=4,
        stream=stream,
        refresh_interval=10.0,
    ):
        await asyncio.sleep(0)

    frames = [
        frame for frame in _tty_frames(stream.getvalue()) if '[' in frame
    ]
    assert frames
    assert all(len(frame) <= columns - 1 for frame in frames)


@pytest.mark.asyncio
async def test_tty_narrow_width_preserves_progress_metrics():
    columns = 32
    stream = _SizedTTYStringIO(columns=columns)

    async for _ in progress(
        range(3),
        desc='Migrando dispatches legacy',
        total=3,
        stream=stream,
        refresh_interval=10.0,
    ):
        await asyncio.sleep(0)

    frames = [
        frame for frame in _tty_frames(stream.getvalue()) if '[' in frame
    ]
    assert frames
    assert all(len(frame) <= columns - 1 for frame in frames)
    assert any('3/3' in frame for frame in frames)


@pytest.mark.asyncio
async def test_non_tty_transient_suppresses_summary_but_keeps_snapshots():
    stream = io.StringIO()

    async for _ in progress(
        [1, 2, 3],
        desc='Transient',
        total=3,
        stream=stream,
        refresh_interval=10.0,
        transient=True,
    ):
        await asyncio.sleep(0)

    lines = [
        line for line in _strip_ansi(stream.getvalue()).splitlines() if line
    ]

    assert any(
        'Transient [##############################] 100.00% (3/3)' in line
        for line in lines
    )
    assert all('Transient: 3 it in ' not in line for line in lines)


@pytest.mark.asyncio
async def test_non_tty_async_iterable_does_not_duplicate_periodic_frames():
    stream = io.StringIO()
    expected_lines = 5

    async def agen() -> AsyncIterator[int]:
        for i in range(3):
            await asyncio.sleep(0.01)
            yield i

    async for _ in progress(
        agen(),
        desc='NoDupes',
        total=3,
        stream=stream,
        refresh_interval=0.005,
    ):
        await asyncio.sleep(0)

    lines = [
        line for line in _strip_ansi(stream.getvalue()).splitlines() if line
    ]
    assert len(lines) == expected_lines
    assert sum('(0/3)' in line for line in lines) == 1
    assert sum('(1/3)' in line for line in lines) == 1
    assert sum('(2/3)' in line for line in lines) == 1
    assert sum('(3/3)' in line for line in lines) == 1
    assert lines[-1].startswith('NoDupes: 3 it in ')


@pytest.mark.asyncio
async def test_elapsed_starts_on_first_use_not_object_creation():
    stream = io.StringIO()
    p = progress(
        [1],
        total=1,
        desc='Delay',
        stream=stream,
        refresh_interval=10.0,
    )

    await asyncio.sleep(0.2)

    async for _ in p:
        await asyncio.sleep(0)

    out = _strip_ansi(stream.getvalue())
    expected_initial = (
        'Delay [..............................]   0.00% (0/1) 0.00 it/s 00.0s'
    )
    assert expected_initial in out
    assert 'Delay: 1 it in 00.0s' in out


@pytest.mark.asyncio
async def test_sync_iterable_infers_total_from_len():
    stream = io.StringIO()
    data = list(range(4))  # tiene __len__
    async for _ in progress(
        data,
        desc='Len inf',
        stream=stream,
        refresh_interval=0.001,
    ):
        await asyncio.sleep(0.01)
    out = stream.getvalue()
    # En algún render debe aparecer (4/4)
    assert '(4/4)' in out


# -----------------------------
# Async iterable cases
# -----------------------------


@pytest.mark.asyncio
async def test_async_iterable_basic():
    stream = io.StringIO()

    async def agen() -> AsyncIterator[int]:
        for i in range(6):
            await asyncio.sleep(0.01)
            yield i

    async for _ in progress(
        agen(),
        total=6,
        desc='Agen',
        stream=stream,
        refresh_interval=1.0,
    ):
        await asyncio.sleep(0)

    out = _strip_ansi(stream.getvalue())
    assert out.count('Agen: 6 it in ') == 1
    assert 'it/s' in out


@pytest.mark.asyncio
async def test_async_iterable_without_total():
    stream = io.StringIO()

    async def agen() -> AsyncIterator[int]:
        for i in range(3):
            await asyncio.sleep(0.005)
            yield i

    # Sin total explícito; el resumen siempre debe estar
    async for _ in progress(
        agen(),
        desc='No total',
        stream=stream,
        refresh_interval=1.0,
    ):
        await asyncio.sleep(0)

    out = _strip_ansi(stream.getvalue())
    assert 'No total: 3 it in ' in out
    # No forzamos presencia de '%' porque sin total no hay porcentaje en barra


# -----------------------------
# Context manager + write()
# -----------------------------


@pytest.mark.asyncio
async def test_async_with_and_write_no_extra_bar_at_end():
    stream = io.StringIO()

    def numbers() -> Iterator[int]:
        yield from range(5)

    async with progress(
        numbers(),
        total=5,
        desc='With',
        stream=stream,
        refresh_interval=1.0,
    ) as p:
        async for n in p:
            p.write(f'value: {n}')
            await asyncio.sleep(0)

    out = _strip_ansi(stream.getvalue())
    # El último renglón no debe ser una barra, sino el resumen
    last = _last_nonempty_line(out)
    assert last.startswith('With: 5 it in ')
    # Y que no haya texto de barra después del resumen
    assert 'With [' not in last


@pytest.mark.asyncio
async def test_log_stream_flushes_partial_output_before_summary_non_tty():
    stream = io.StringIO()

    async with progress(
        [1, 2],
        total=2,
        desc='Stream',
        stream=stream,
        refresh_interval=10.0,
    ) as p:
        log = p.log_stream()
        print('alpha', file=log)
        log.write('beta')

        async for _ in p:
            await asyncio.sleep(0)

    lines = [
        line for line in _strip_ansi(stream.getvalue()).splitlines() if line
    ]
    assert 'alpha' in lines
    assert 'beta' in lines
    assert lines[-1].startswith('Stream: 2 it in ')
    assert lines.index('alpha') < lines.index('beta') < len(lines) - 1


@pytest.mark.asyncio
async def test_log_stream_keeps_messages_above_bar_in_tty():
    stream = _TTYStringIO()

    async with progress(
        [1, 2],
        total=2,
        desc='TTY',
        stream=stream,
        refresh_interval=10.0,
    ) as p:
        log = p.log_stream()
        print('alpha', file=log)
        log.write('beta')

        async for _ in p:
            await asyncio.sleep(0)

    raw = stream.getvalue()
    screen = _render_tty_screen(raw)

    assert 'alpha\n\r\x1b[2KTTY [' in raw
    assert 'beta\n\r\x1b[2KTTY [' in raw
    assert screen[:-1] == ['alpha', 'beta']
    assert screen[-1].startswith('TTY: 2 it in ')


# -----------------------------
# track_as_completed cases
# -----------------------------


@pytest.mark.asyncio
async def test_track_as_completed_varied_durations():
    stream = io.StringIO()

    async def work(n: int) -> int:
        # Duraciones variadas: 0.01..0.06
        await asyncio.sleep(0.01 * (n % 6 + 1))
        return n

    tasks = [work(i) for i in range(10)]

    # Itera devolviendo futuros; hacemos await dentro del bucle
    async for fut in track_as_completed(
        tasks,
        desc='Parallel',
        stream=stream,
        refresh_interval=0.02,
    ):
        _ = await fut  # procesar resultado

    out = _strip_ansi(stream.getvalue())
    assert 'Parallel: 10 it in ' in out


@pytest.mark.asyncio
async def test_track_as_completed_equal_durations_still_counts():
    stream = io.StringIO()

    async def work(n: int) -> int:
        await asyncio.sleep(0.02)  # todas igual
        return n

    tasks = [work(i) for i in range(8)]
    async for fut in track_as_completed(
        tasks,
        desc='Equal',
        stream=stream,
        refresh_interval=0.02,
    ):
        _ = await fut

    out = _strip_ansi(stream.getvalue())
    assert 'Equal: 8 it in ' in out


@pytest.mark.asyncio
async def test_track_as_completed_accepts_transient():
    stream = _TTYStringIO()

    async def work(n: int) -> int:
        await asyncio.sleep(0.001)
        return n

    tasks = [work(1), work(2)]
    async for fut in track_as_completed(
        tasks,
        total=2,
        desc='Parallel',
        stream=stream,
        refresh_interval=10.0,
        transient=True,
    ):
        _ = await fut

    out = stream.getvalue()
    assert _render_tty_screen(out) == []
    assert 'Parallel: 2 it in ' not in out


@pytest.mark.asyncio
async def test_track_as_completed_can_cancel_pending_tasks_on_early_exit():
    release = asyncio.Event()

    async def fast() -> int:
        await asyncio.sleep(0)
        return 1

    async def slow() -> int:
        try:
            await release.wait()
            return 2
        finally:
            release.set()

    slow_one = asyncio.create_task(slow())
    slow_two = asyncio.create_task(slow())
    tasks = [asyncio.create_task(fast()), slow_one, slow_two]

    async for fut in track_as_completed(
        tasks,
        total=3,
        cancel_pending=True,
        refresh_interval=10.0,
    ):
        await fut
        break

    await asyncio.gather(slow_one, slow_two, return_exceptions=True)

    assert slow_one.cancelled()
    assert slow_two.cancelled()


# -----------------------------
# show_summary flag
# -----------------------------


@pytest.mark.asyncio
async def test_show_summary_false():
    stream = io.StringIO()
    data = [1, 2, 3]
    p = progress(
        data,
        desc='NoSum',
        total=3,
        show_summary=False,
        stream=stream,
        refresh_interval=10.0,
    )
    async for _ in p:
        await asyncio.sleep(0)

    out = _strip_ansi(stream.getvalue())
    assert 'NoSum [##############################] 100.00% (3/3)' in out
    # No debe haber resumen
    assert 'NoSum: 3 it in ' not in out

    before_write = stream.getvalue()
    p.write('after')
    assert stream.getvalue() == before_write


@pytest.mark.asyncio
async def test_total_zero_renders_as_completed_bar():
    stream = io.StringIO()

    async for _ in progress(
        [],
        total=0,
        desc='Empty',
        stream=stream,
        refresh_interval=10.0,
    ):
        await asyncio.sleep(0)

    out = _strip_ansi(stream.getvalue())
    assert 'Empty [##############################] 100.00% (0/0)' in out
    assert 'Empty: 0 it in ' in out


# -----------------------------
# stream wiring & basic type use
# -----------------------------


@pytest.mark.asyncio
async def test_progress_stream_stdout_like():
    # Simulamos sys.stdout con StringIO
    stream = io.StringIO()

    async def agen():
        for i in range(2):
            await asyncio.sleep(0.005)
            yield i

    async for _ in progress(
        agen(),
        total=2,
        desc='Stdout',
        stream=stream,
        refresh_interval=1.0,
    ):
        pass
    out = _strip_ansi(stream.getvalue())
    assert 'Stdout: 2 it in ' in out


# -----------------------------
# smoke test: Progress usable directamente
# -----------------------------


@pytest.mark.asyncio
async def test_progress_class_direct_use():
    stream = io.StringIO()

    async def agen():
        for i in range(3):
            await asyncio.sleep(0.003)
            yield i

    p = Progress(
        agen(),
        total=3,
        desc='Class',
        stream=stream,
        refresh_interval=1.0,
    )
    async with p:
        async for _ in p:
            await asyncio.sleep(0)
    out = _strip_ansi(stream.getvalue())
    assert 'Class: 3 it in ' in out


# -----------------------------
# ETA presence only when total is known (heurística simple)
# -----------------------------


@pytest.mark.asyncio
async def test_eta_only_when_total_known():
    stream1 = io.StringIO()
    stream2 = io.StringIO()

    async def agen():
        for i in range(3):
            await asyncio.sleep(0.005)
            yield i

    # Con total -> debería haber "ETA"
    async for _ in progress(
        agen(),
        total=3,
        desc='HasTotal',
        stream=stream1,
        refresh_interval=0.001,
    ):
        await asyncio.sleep(0.01)

    # Sin total -> preferimos que no aparezca "ETA" en la salida
    async for _ in progress(
        agen(),
        desc='NoTotal',
        stream=stream2,
        refresh_interval=0.001,
    ):
        await asyncio.sleep(0.01)

    out1 = stream1.getvalue()
    out2 = stream2.getvalue()
    assert 'ETA' in out1
    assert 'ETA' not in out2
