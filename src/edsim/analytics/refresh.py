"""The micro-batches: build the hospital sheet every ``every`` seconds until Ctrl+C (H8-10).

Plata and oro are tables: they only change when someone builds them. ``refresh`` launches the
build of the hospital sheet over and over (docs/specs/hito-8.md, «Especificación: tiempo
real»):

- the interval counts from the start of each round: a round of 10 s waits 50 s with
  ``every = 60``;
- a round longer than ``every`` is reported, and the next one starts as soon as it ends;
- a round that fails is reported with its exit code and the end of the output of dbt, and the
  next one runs as usual (D3 of the chat notes): a passing failure does not stop the live run;
- Ctrl+C, inside a round or while waiting, ends the loop with a summary.

The build is ``dbt build`` without tests (D2 of the chat notes), not ``dbt run``: it also loads
the seeds, so it works on a database just created, and the data tests stay for the full builds.

The texts are in Spanish, as the rest of the CLI.
"""

import os
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

DEFAULT_EVERY = 60.0
"""Seconds between the starts of two rounds (decision 109, H8-10)."""

DBT_BUILD = (
    "build",
    "--vars",
    "{hoja: hospital}",
    "--exclude",
    "tag:laboratorio",
    "--exclude-resource-type",
    "test",
    "unit_test",
)
"""The arguments of dbt: the hospital sheet with its seeds, without the table of three columns
(built apart, with the three sheets) and without data tests or unit tests."""

TAIL_LINES = 20
"""Lines of the output of dbt shown when a round fails: the error is at the end."""


@dataclass(frozen=True)
class BuildResult:
    """What one build left: the exit code of dbt and its output."""

    returncode: int
    output: str


class Clock(Protocol):
    """The time of the loop: the part of ``edsim.live.clock.Clock`` it needs, so that
    ``edsim.live.clock.SystemClock`` is the real one."""

    def monotonic(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


@dataclass(frozen=True)
class RefreshSummary:
    """The rounds that ended (one cut by Ctrl+C does not count), how many failed and the
    longest, in seconds (``None`` if none ended)."""

    rounds: int
    failures: int
    longest: float | None


def dbt_command(uv: str, folder: Path) -> list[str]:
    """``uv run --locked --project <folder> dbt build …``: dbt in its own environment.

    ``--locked`` fails if ``analitica/uv.lock`` is out of date instead of locking again.
    """
    return [uv, "run", "--locked", "--project", str(folder), "dbt", *DBT_BUILD]


def dbt_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """The environment of dbt: ``environ`` without ``VIRTUAL_ENV``.

    ``uv run edsim`` sets it to the environment of the core; ``uv run --project analitica``
    would ignore it with a warning. The ``EDSIM_PG_*`` of ``profiles.yml`` pass through: they
    choose the database.
    """
    return {key: value for key, value in environ.items() if key != "VIRTUAL_ENV"}


def dbt_builder(uv: str, folder: Path) -> Callable[[], BuildResult]:
    """One build of the hospital sheet per call, with ``folder`` as working directory.

    dbt looks there for ``dbt_project.yml`` and ``profiles.yml``. Its output and the one of uv
    go to one pipe, in the order they were written: the error of dbt stays in the tail.

    On Ctrl+C, the build waits for dbt to end before raising ``KeyboardInterrupt``, reading its
    output so that it never blocks on a full pipe. From a terminal, dbt gets the signal too,
    cancels its queries and cleans up; ``subprocess.run`` would kill ``uv`` after 0.25 s and
    leave dbt without its pipe, halfway through swapping a table. A second Ctrl+C ends the wait.
    """
    command = dbt_command(uv, folder)

    def build() -> BuildResult:
        with subprocess.Popen(
            command,
            cwd=folder,
            env=dbt_environment(os.environ),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        ) as process:
            try:
                output, _ = process.communicate()
            except KeyboardInterrupt:
                process.communicate()
                raise
        return BuildResult(process.returncode, output)

    return build


def _seconds(value: float) -> str:
    return f"{value:.1f} s"


def format_round(number: int, seconds: float, result: BuildResult) -> str:
    """One line per round; a failed one, with its code and the end of the output of dbt."""
    if result.returncode == 0:
        return f"Vuelta {number}: {_seconds(seconds)}"
    tail = result.output.rstrip("\n").splitlines()[-TAIL_LINES:]
    lines = [
        f"Vuelta {number}: falló con código {result.returncode} en {_seconds(seconds)}; "
        "se intenta en la siguiente. Lo último de dbt:",
        *(f"  {line}" for line in tail),
    ]
    return "\n".join(lines)


def format_slow(number: int, seconds: float, every: float) -> str:
    """The warning of a round longer than the interval."""
    return (
        f"Aviso: la vuelta {number} tardó {_seconds(seconds)}, más que el intervalo de "
        f"{every:g} s; la siguiente empieza ya"
    )


def format_summary(summary: RefreshSummary) -> str:
    """The summary after Ctrl+C."""
    if summary.rounds == 0:
        return "Parado con Ctrl+C antes de acabar la primera vuelta"
    rounds = "1 vuelta" if summary.rounds == 1 else f"{summary.rounds} vueltas"
    errors = f", {summary.failures} con error" if summary.failures else ", ninguna con error"
    return f"Parado con Ctrl+C: {rounds}{errors}; la más larga, {_seconds(summary.longest)}"


def refresh(
    build: Callable[[], BuildResult],
    clock: Clock,
    every: float,
    emit: Callable[[str], None],
) -> RefreshSummary:
    """Build every ``every`` seconds until Ctrl+C, and return the summary it also emits.

    Each round starts ``every`` seconds after the previous one started or, if that one took
    longer, as soon as it ends: a round of exactly ``every`` neither warns nor waits.
    """
    if not every > 0 or every == float("inf"):
        raise ValueError(f"every must be a positive number of seconds, got {every!r}")
    rounds = failures = 0
    longest: float | None = None
    try:
        while True:
            start = clock.monotonic()
            result = build()
            seconds = clock.monotonic() - start
            rounds += 1
            failures += result.returncode != 0
            longest = seconds if longest is None else max(longest, seconds)
            emit(format_round(rounds, seconds, result))
            if seconds > every:
                emit(format_slow(rounds, seconds, every))
            wait = start + every - clock.monotonic()
            if wait > 0:
                clock.sleep(wait)
    except KeyboardInterrupt:
        pass
    summary = RefreshSummary(rounds, failures, longest)
    emit(format_summary(summary))
    return summary
