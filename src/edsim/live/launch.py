"""Prepare and run a live run or a replay: what ``edsim directo lanzar`` and ``reemitir`` do.

The CLI only parses the options, builds the real clock, orders and sink, and prints;
everything else is here, so that a test or a notebook does the same with a fake clock,
scripted orders and a sink in memory (docs/specs/hito-6.md, "Precisiones para la 6.5"):

- ``prepare_live``: the stepped engine of a run with its options, the identity of the run
  and ``W``; anchored to the calendar or with the date of the arrival profile.
- ``prepare_replay``: a run saved in ``resultados/ejecuciones/``, read lazily, with the
  date of its first event and its own ``run_id`` and ``event_id``.
- ``run_prepared``: the pacer, the status and ``run_live``.
- ``live_run_id``: the default identifier of a live run (H6-19).

A live run does not save a run in ``resultados/``: its batch is ``edsim motor simular``
with the same ``--run-id``.
"""

import numbers
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

from edsim.arrivals.profile import ArrivalProfile
from edsim.arrivals.rate import MINUTES_PER_DAY
from edsim.engine.center import CenterConfig
from edsim.engine.engine import check_horizon, start_ed
from edsim.engine.events import (
    CURRENT_CLINICAL_SCHEMA_VERSION,
    PROVISIONAL_SCHEMA_VERSION,
    TIMEZONE,
    Event,
    MemorySink,
    read_events,
)
from edsim.live.clock import Clock
from edsim.live.control import ControlSource
from edsim.live.directo import (
    LIVE,
    REPLAY,
    EngineSource,
    LiveSink,
    LiveSource,
    LogSource,
    RunEnd,
    RunInfo,
    RunStart,
    anchored_start,
    run_live,
)
from edsim.live.pacer import Pacer
from edsim.live.status import STATUS_INTERVAL, LiveStatus, ReportingSink, StatusControl
from edsim.profiles.config import ClinicalProfiles
from edsim.runs.identifiers import validate_run_id
from edsim.runs.store import RunStore

EVENTS_FILE = "eventos.jsonl"


def live_run_id(seed: int, wall: datetime) -> str:
    """The default ``run_id`` of a live run: ``r``, the seed, ``_`` and the time of the start.

    The time is taken in the fixed zone ``+01:00`` of ``event_time``, not in UTC:
    2026-11-06T16:23:00Z with seed 2026 is ``r2026_20261106T172300``. Two live runs with
    the same seed at different times never share an ``event_id``.

    Raises:
        ValueError: If ``seed`` is not an integer >= 0, ``wall`` has no time zone, or the
            identifier is not a valid ``run_id`` (too long).
    """
    if isinstance(seed, bool) or not isinstance(seed, numbers.Integral) or seed < 0:
        raise ValueError(f"seed must be an integer >= 0, got {seed!r}")
    if not isinstance(wall, datetime) or wall.utcoffset() is None:
        raise ValueError(f"wall must be a datetime with time zone, got {wall!r}")
    return validate_run_id(f"r{seed}_{wall.astimezone(TIMEZONE):%Y%m%dT%H%M%S}")


@dataclass(frozen=True, slots=True)
class PreparedRun:
    """A run ready for ``run_prepared``: nothing has been warmed up nor published.

    Attributes:
        source: ``EngineSource`` or ``LogSource``, before any step.
        info: Identity of the run, for the ``inicio``.
        start: Start of the live stream ``W``, in minutes.
        horizon: Horizon in minutes.
    """

    source: LiveSource
    info: RunInfo
    start: float
    horizon: float


def prepare_live(
    center: CenterConfig,
    profile: ArrivalProfile,
    days: int,
    seed: int,
    *,
    warmup_days: int,
    run_id: str,
    profiles: ClinicalProfiles | None = None,
    anchor_wall: datetime | None = None,
) -> PreparedRun:
    """Prepare a live run of the engine.

    Args:
        center: The center.
        profile: The arrival profile; with ``anchor_wall``, only its date changes, without
            normalizing again (``ArrivalProfile.with_start_date``).
        days: Horizon in full days, warm-up included.
        seed: Seed of the run, an integer >= 0.
        warmup_days: Full days of warm-up before ``W``.
        run_id: Identifier of the run.
        profiles: The clinical profiles (catalog 3); ``None`` for the provisional model
            (catalog 1).
        anchor_wall: If given, the run is anchored to the calendar (H6-12): it starts
            ``warmup_days`` before that day at 00:00 and warms up until that moment, in
            ``+01:00``. Otherwise it starts on the date of the profile and ``W`` is
            ``warmup_days`` × 1,440.

    Raises:
        ValueError: If ``days`` and ``warmup_days`` are not valid, ``W`` is not before the
            horizon, or the engine or the identity of the run refuse a value.
    """
    days, warmup_days = check_horizon(days, warmup_days)
    if anchor_wall is not None:
        start_date, start = anchored_start(anchor_wall, warmup_days)
        profile = profile.with_start_date(start_date)
    else:
        start = float(warmup_days * MINUTES_PER_DAY)
    horizon = float(days * MINUTES_PER_DAY)
    # Unreachable after check_horizon (W < (warm-up + 1) days <= days), kept as a guard.
    if not start < horizon:
        raise ValueError(f"the live stream starts at {start} min, not before the horizon {horizon}")
    info = RunInfo(
        run_id=run_id,
        mode=LIVE,
        schema_version=(
            PROVISIONAL_SCHEMA_VERSION if profiles is None else CURRENT_CLINICAL_SCHEMA_VERSION
        ),
        seed=seed,
        start_date=profile.start_date,
        anchored=anchor_wall is not None,
    )
    buffer = MemorySink()
    ed = start_ed(
        center,
        profile,
        days,
        seed,
        sink=buffer,
        warmup_days=warmup_days,
        run_id=run_id,
        profiles=profiles,
    )
    return PreparedRun(EngineSource(ed, buffer), info, start, horizon)


def log_start_date(event: Event) -> date:
    """The date of minute 0 of a log, from one of its events: ``event_time`` − ``sim_time``.

    In ``+01:00``, rounded to the minute: ``event_time`` is truncated to the millisecond.

    Raises:
        ValueError: If that moment is not at 00:00.
    """
    moment = datetime.fromisoformat(event.event_time).astimezone(TIMEZONE)
    moment -= timedelta(minutes=event.sim_time)
    rounded = (moment + timedelta(seconds=30)).replace(second=0, microsecond=0)
    if rounded.time() != time(0):
        raise ValueError(
            f"the log does not start at 00:00: {event.event_id} at {event.event_time} is minute "
            f"{event.sim_time}"
        )
    return rounded.date()


def prepare_replay(root: str | Path, run_id: str, *, warmup_days: int | None = None) -> PreparedRun:
    """Prepare the replay of a saved run (H6-13).

    The horizon is the ``days`` of its ``run.json``, ``W`` is ``warmup_days`` or its own
    warm-up, the seed is its own, and the start date and the catalog version are those of
    its first event. It keeps the ``run_id`` and the ``event_id``: it publishes the same
    bytes. The log is read lazily.

    Args:
        root: Directory of the runs, such as ``resultados/ejecuciones``.
        run_id: The run.
        warmup_days: Full days before ``W``; the saved warm-up if ``None``.

    Raises:
        OSError: If the run or its files cannot be read.
        ValueError: If the run is not valid, ``warmup_days`` is not less than its days, or
            its log is empty, is of another run or does not start at 00:00.
    """
    saved = RunStore(root).open(run_id)
    days, warmup = check_horizon(
        saved.days, saved.warmup_days if warmup_days is None else warmup_days
    )
    path = Path(root) / run_id / EVENTS_FILE
    first = next(read_events(path), None)
    if first is None:
        raise ValueError(f"the log of {run_id} is empty: {path}")
    if first.run_id != run_id:
        raise ValueError(f"the log of {run_id} is of run {first.run_id!r}: {path}")
    info = RunInfo(
        run_id=run_id,
        mode=REPLAY,
        schema_version=first.schema_version,
        seed=saved.seed,
        start_date=log_start_date(first),
        anchored=False,
    )
    horizon = float(days * MINUTES_PER_DAY)
    return PreparedRun(
        LogSource(read_events(path), horizon), info, float(warmup * MINUTES_PER_DAY), horizon
    )


def run_prepared(
    prepared: PreparedRun,
    *,
    clock: Clock,
    speed: float | str,
    control: ControlSource,
    sink: LiveSink,
    on_start: Callable[[RunStart], None] | None = None,
    on_end: Callable[[RunStart | None, RunEnd], None] | None = None,
    on_status: Callable[[LiveStatus], None] | None = None,
    pending: Callable[[], int] | None = None,
    status_interval: float = STATUS_INTERVAL,
) -> RunEnd:
    """Run a prepared run with ``run_live``: warm-up, census, live stream and end.

    Args:
        prepared: From ``prepare_live`` or ``prepare_replay``.
        clock: The clock of the pacer.
        speed: Speed at the start, a positive number or ``"max"``.
        control: Where the orders come from.
        sink: Where the run publishes.
        on_start: Called with the ``RunStart`` once published (the census).
        on_end: Called with the ``RunStart`` and the ``RunEnd`` once the end is published,
            also before a ``KeyboardInterrupt`` or a ``SinkError`` goes on.
        on_status: If given, called with a ``LiveStatus`` every ``status_interval`` real
            seconds from the anchor of the live stream.
        pending: Messages waiting for their confirmation, for the status.
        status_interval: Real seconds between two statuses.

    Returns:
        The ``RunEnd`` published.

    Raises:
        As ``run_live``.
    """
    pacer = Pacer(clock, speed, (clock.monotonic(), prepared.start))
    reporting = ReportingSink(sink, on_start=on_start, on_end=on_end)
    if on_status is not None:
        control = StatusControl(
            control,
            clock=clock,
            pacer=pacer,
            start_date=prepared.info.start_date,
            horizon=prepared.horizon,
            published=lambda: reporting.published,
            on_status=on_status,
            pending=pending,
            interval=status_interval,
        )
    return run_live(
        prepared.source,
        pacer,
        control,
        reporting,
        start=prepared.start,
        horizon=prepared.horizon,
        run_info=prepared.info,
    )
