# processit

A lightweight progress utility for Python --- built for both synchronous
and asynchronous iteration.

`processit` provides a simple, dependency-free progress bar for loops
that may be either regular iterables or async iterables.

---

## Installation

```bash
pip install processit
```

---

## Quick Example

### progress (sequential iteration)

```python
import asyncio
import time

from processit import progress

def numbers():
    for i in range(10):
        time.sleep(0.3)
        yield i

async def main():
    async for _ in progress(numbers(), total=10, desc="Numbers"):
        await asyncio.sleep(0)

asyncio.run(main())
```

> ⚠️ `progress` does **not** create concurrency.\
> It simply instruments iteration and renders a progress bar.

---

### Using `progress` with context manager

```python
import asyncio
import time

from processit import progress

def numbers():
    for i in range(10):
        time.sleep(0.3)
        yield i

async def main():
    async with progress(numbers(), total=10, desc='Numbers') as p:
        log = p.log_stream()
        async for n in p:
            print(f'value: {n}', file=log)
            await asyncio.sleep(0.5)

asyncio.run(main())
```

---

## Concurrency & Parallelism

`progress(...)` does **not** parallelize work.

If you want true concurrency (e.g., HTTP calls, async DB operations,
async file IO), you must create tasks yourself and use
`track_as_completed(...)`.

---

### track_as_completed (parallel tasks)

```python
import asyncio
import random

from processit import track_as_completed

async def work(n: int) -> int:
    await asyncio.sleep(1.5 + random.random())
    return n * 2

async def main():
    tasks = [asyncio.create_task(work(i)) for i in range(10)]

    async for task in track_as_completed(tasks, total=len(tasks), desc="Parallel work"):
        result = await task
        print(result)

asyncio.run(main())
```

---

### Limiting concurrency with a semaphore

```python
import asyncio
from processit import track_as_completed

async def fetch(i: int) -> int:
    await asyncio.sleep(1)
    return i * 2

async def main():
    sem = asyncio.Semaphore(5)

    async def bounded(i: int):
        async with sem:
            return await fetch(i)

    tasks = [asyncio.create_task(bounded(i)) for i in range(20)]

    async for task in track_as_completed(tasks, total=len(tasks), desc="HTTP"):
        result = await task
        # process result

asyncio.run(main())
```

---

## Important Notes

### 1. Blocking code

If your iterable performs blocking operations (e.g. `time.sleep`,
synchronous file writes, synchronous DB access), the event loop will
still be blocked.

To avoid blocking:

- Use async libraries (`aiohttp`, async DB drivers, `aiofiles`, etc.)
- Or move blocking work to a thread:

```python
await asyncio.to_thread(blocking_function, arg1, arg2)
```

---

### 2. When to use each utility

Use case Recommended utility

---

Sequential iteration `progress(...)`
Parallel async tasks `track_as_completed(...)`
Need concurrency limit `Semaphore` + `track_as_completed(...)`

---

### 3. TTY vs non-TTY output

When the output stream is a real TTY, `processit` redraws the same line.

When the output stream is not a TTY (for example CI logs, redirected output,
or `StringIO` in tests), `processit` emits line-based snapshots instead:

- It respects `refresh_interval` without periodic duplicate frames
- It prints a final `100%` snapshot before the summary when `total` is known
- Messages written with `p.write(...)` or `file=p.log_stream()` stay above the
  live bar; the bar is re-rendered as the last line in TTY mode

Timing starts when iteration actually begins, not when the `Progress`
instance is created.

If you want the live bar to disappear after completion, use
`transient=True`. In TTY streams the active line is cleared on exit and
the final summary is suppressed. In non-TTY streams previously emitted
snapshots cannot be removed, so `transient=True` only suppresses the
summary line.

If you set `show_summary=False` without `transient=True`, the last
rendered frame remains visible. Use `transient=True` when you want the
TTY line cleared on exit.

---

## More Examples

### Asynchronous iteration over a data source

```python
import asyncio
from processit import progress

async def fetch_items():
    for i in range(20):
        await asyncio.sleep(0.05)
        yield f"item-{i}"

async def main():
    async for item in progress(fetch_items(), total=20, desc="Fetching"):
        await asyncio.sleep(0.02)

asyncio.run(main())
```

---

### Processing without a defined total

```python
import asyncio
from processit import progress

items = [x ** 2 for x in range(100)]

async def main():
    async for value in progress(items, desc="Squaring"):
        await asyncio.sleep(0.01)

asyncio.run(main())
```

---

## Features

- Works with both **async** and **sync** iterables
- Displays **elapsed time**, **rate**, and **ETA** (when total is
  known)
- Can keep the final frame, print a summary, or clear the bar with
  `transient=True`
- No dependencies --- pure Python, fully type-hinted
- Easy to use drop-in function: `progress(iterable, ...)`

---

## API

### progress(iterable, total=None, \*, desc='Processing', width=30, refresh_interval=0.1, show_summary=True, transient=False)

Creates and returns a `Progress` instance.

Name Type Description

---

`iterable` `Iterable[T] \| AsyncIterable[T]` Iterable to track
`total` `int \| None` Total number of iterations
`desc` `str` Text prefix shown before the bar
`width` `int` Width of the progress bar
`refresh_interval` `float` Time between updates
`show_summary` `bool` Whether to print final summary
`transient` `bool` Whether to clear the live TTY bar on exit and suppress the summary

---

### Progress helpers inside `async with progress(...) as p`

- `p.write("message")`: prints a message above the live bar and re-renders it
- `p.log_stream()`: returns a file-like stream for `print(..., file=...)` or
  `logging.StreamHandler`

If a command mixes progress output with logs, prefer one of those two
interfaces instead of calling `print(...)` directly on stdout/stderr.

---

### track_as_completed(tasks, total=None, \*, desc='Processing', width=30, refresh_interval=0.1, show_summary=True, transient=False, cancel_pending=False)

Tracks a collection of awaitables or tasks as they complete.

Name Type Description

---

`tasks` `Iterable[Awaitable[T]]` Tasks or coroutines to monitor
`total` `int \| None` Total number of tasks
`desc` `str` Text prefix shown before the bar
`width` `int` Width of the progress bar
`refresh_interval` `float` Time between updates
`show_summary` `bool` Whether to print final summary
`transient` `bool` Whether to clear the live TTY bar on exit and suppress the summary
`cancel_pending` `bool` Whether to cancel unfinished tasks if iteration stops early

---

## Design Philosophy

`processit` is intentionally minimal:

- No external dependencies\
- No hidden concurrency\
- Clear separation between instrumentation (`progress`) and
  concurrency (`track_as_completed`)

It focuses purely on progress rendering while leaving execution strategy
under your control.
