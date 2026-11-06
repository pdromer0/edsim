"""The engine: arrivals, patients and the horizon, in one SimPy environment.

``run_engine`` is the core: it takes the arrivals as an iterable and the
draws of each patient as an injectable function, so that tests can build exact
scenarios by hand. It first starts the shifts (``start_shifts``), which set
the staff of minute 0 and change it at each start of a shift. For each arrival
it calls the sampler, in arrival order, keeps the ground truth of the episode
and starts the patient process. The run stops at ``days * 1440`` minutes:
events scheduled at that instant or later do not happen, and patients still
inside have no ``patient_departed``.

``simulate_ed`` is the run with a seed: it derives five independent streams
with ``child_streams(seed, 5)`` (ADR 0007). Stream 0 goes as it is to
``iter_arrivals``, so the arrivals are the same as the arrival generator's
with that stream; streams 1 to 4 go to the ``ProvisionalSampler`` (level,
durations, tests and destination).

With clinical profiles (task 4.5a), ``simulate_ed`` derives eight streams with
``child_streams(seed, 8)``: the first five are the same five children, because
each child depends only on its index, so the arrivals do not change; streams 1
to 7 go to the ``ClinicalSampler``, and the log is of version 2 of the catalog.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

import numpy as np
import simpy

from edsim.arrivals.profile import ArrivalProfile
from edsim.arrivals.rate import MINUTES_PER_DAY
from edsim.arrivals.thinning import ArrivalRecord, DayRecord, arrival_source, iter_arrivals
from edsim.engine.center import CenterConfig
from edsim.engine.clinical import PatientDraws, ProvisionalSampler
from edsim.engine.clinical_sampler import ClinicalSampler
from edsim.engine.events import CLINICAL_SCHEMA_VERSION, EventLog, EventSink
from edsim.engine.ground_truth import EpisodeTruth, GroundTruth
from edsim.engine.patient import patient
from edsim.engine.resources import make_pools
from edsim.engine.shifts import start_shifts
from edsim.profiles.config import ClinicalProfiles
from edsim.seeds import child_streams

N_STREAMS = 5
"""Streams of a run: arrivals, then the four of the sampler."""

N_CLINICAL_STREAMS = 8
"""Streams of a run with clinical profiles: arrivals, then the seven of the sampler."""

DEFAULT_WARMUP_DAYS = 2
"""Warm-up of a run in full days (docs/specs/hito-3.md: 24-48 h in the design)."""

Sampler = Callable[[ArrivalRecord], PatientDraws]
"""Draws of the patient of an arrival, such as ``ProvisionalSampler``.

Called once per arrival, in arrival order, at the instant of the arrival.
"""


@dataclass(frozen=True, slots=True)
class EngineRun:
    """What ``run_engine`` returns besides the log.

    Attributes:
        episodes: Ground truth of every arrival before the horizon, in arrival
            order.
        inside: Patient processes still alive in SimPy at the horizon. It is
            counted from SimPy, not from the log, so that the invariants can
            compare both.
    """

    episodes: tuple[EpisodeTruth, ...]
    inside: int


def _check_days(days: object) -> int:
    # bool is a subclass of int in Python: True must not pass as 1 day.
    if isinstance(days, bool) or not isinstance(days, int) or days < 1:
        raise ValueError(f"days must be a positive integer, got {days!r}")
    return days


def _check_warmup(warmup_days: object, days: int) -> int:
    if isinstance(warmup_days, bool) or not isinstance(warmup_days, int):
        raise ValueError(f"warmup_days must be an integer, got {warmup_days!r}")
    if not 0 <= warmup_days < days:
        raise ValueError(
            f"warmup_days must be at least 0 and less than days ({days}), got {warmup_days!r}"
        )
    return warmup_days


def check_horizon(days: object, warmup_days: object) -> tuple[int, int]:
    """Check the horizon and the warm-up of a run, as ``simulate_ed`` does.

    The CLI calls it before creating any file, so that a usage error leaves
    nothing half written.

    Returns:
        ``(days, warmup_days)``.

    Raises:
        ValueError: If ``days`` is not a positive integer (checked first), or
            ``warmup_days`` is not an integer in [0, ``days``).
    """
    days = _check_days(days)
    return days, _check_warmup(warmup_days, days)


def run_engine(
    center: CenterConfig,
    arrivals: Iterable[ArrivalRecord],
    sampler: Sampler,
    log: EventLog,
    days: int,
) -> EngineRun:
    """Simulate the center for ``days`` full days with the given arrivals.

    Args:
        center: Staff, boxes and the rest of the configuration.
        arrivals: Arrival records in time order, such as ``iter_arrivals``.
            Arrivals at or after the horizon do not happen.
        sampler: Draws of each patient, called on arrival.
        log: Where the events go.
        days: Horizon in full days; a positive integer.

    Returns:
        The ground truth of the episodes and the patients still inside.

    Raises:
        ValueError: If ``days`` is not a positive integer.
    """
    days = _check_days(days)
    env = simpy.Environment()
    pools = make_pools(env, center)
    # Before any other process: the staffing_changed of minute 0 go first in the
    # log, and each change of shift is the first event of its instant.
    start_shifts(env, log, pools, center, days)
    episodes: list[EpisodeTruth] = []
    processes: list[simpy.Process] = []

    def on_arrival(arrival: ArrivalRecord) -> None:
        draws = sampler(arrival)
        episodes.append(EpisodeTruth.from_draws(arrival, draws))
        processes.append(env.process(patient(env, log, pools, arrival.arrival_id, draws)))

    env.process(arrival_source(env, arrivals, on_arrival))
    env.run(until=days * MINUTES_PER_DAY)
    return EngineRun(
        episodes=tuple(episodes), inside=sum(process.is_alive for process in processes)
    )


@dataclass(frozen=True, slots=True)
class EDResult:
    """What ``simulate_ed`` returns; the events went to the sink.

    Attributes:
        run_id: Identifier of the run, in every event of the log.
        ground_truth: Episodes and days of the run.
        inside: Patient processes still alive in SimPy at the horizon.
        warmup_days: Full days of warm-up. The log is complete, warm-up
            included; the metrics use the window [warm-up, horizon].
    """

    run_id: str
    ground_truth: GroundTruth
    inside: int
    warmup_days: int


def default_run_id(seed: int | np.random.SeedSequence) -> str:
    """``r`` and the seed, such as ``r2026``.

    A ``SeedSequence`` gives ``r``, its entropy and each number of its
    ``spawn_key`` after a dot: ``SeedSequence(2026)`` is ``r2026``, the same as
    the integer 2026, because both are the same run; child 1 of it is
    ``r2026.1``, and child 0 of that one ``r2026.1.0``. An entropy given as a
    list of integers is joined with ``_``. The dot keeps the identifier apart
    from the hyphen of ``event_id``.
    """
    if not isinstance(seed, np.random.SeedSequence):
        return f"r{seed}"
    entropy = seed.entropy
    if isinstance(entropy, int):
        base = str(entropy)
    else:
        base = "_".join(str(int(x)) for x in entropy)
    return "r" + base + "".join(f".{k}" for k in seed.spawn_key)


def simulate_ed(
    center: CenterConfig,
    profile: ArrivalProfile,
    days: int,
    seed: int | np.random.SeedSequence,
    *,
    sink: EventSink,
    warmup_days: int = DEFAULT_WARMUP_DAYS,
    run_id: str | None = None,
    sampler: Sampler | None = None,
    profiles: ClinicalProfiles | None = None,
) -> EDResult:
    """Simulate the emergency department for ``days`` full days.

    Args:
        center: Staff, boxes and the provisional clinical model.
        profile: Arrival profile; its ``start_date`` is minute 0 of the log.
        days: Horizon in full days, warm-up included; a positive integer.
        seed: Seed of the run: an integer or a ``SeedSequence``, which is not
            modified, so the same object gives the same run.
        sink: Where the events go, such as ``MemorySink`` or ``JsonlSink``.
        warmup_days: Full days of warm-up, at least 0 and less than ``days``.
            It does not cut the log: in batch the log is complete, so the
            invariants hold in the whole file, and the metrics use the window
            [warm-up, horizon] (docs/specs/hito-3.md).
        run_id: Identifier of the run; ``default_run_id(seed)`` if ``None``.
        sampler: Draws of each patient; a ``ProvisionalSampler`` with streams
            1 to 4 if ``None``. Injected only in tests.
        profiles: Clinical profiles. With them, the patients come from a
            ``ClinicalSampler`` with streams 1 to 7 of ``child_streams(seed,
            8)`` and the log is of version 2; without them, the provisional
            model, exactly as before (ADR candidate 44).

    Returns:
        The run identifier, the ground truth, the patients still inside and
        the warm-up.

    Raises:
        ValueError: If ``days`` is not a positive integer, ``warmup_days`` is
            not an integer in [0, ``days``), or both ``sampler`` and
            ``profiles`` are given.
    """
    days, warmup_days = check_horizon(days, warmup_days)
    if sampler is not None and profiles is not None:
        raise ValueError("give sampler or profiles, not both: the profiles choose the sampler")
    if run_id is None:
        run_id = default_run_id(seed)

    day_records: list[DayRecord] = []
    if profiles is None:
        streams = child_streams(seed, N_STREAMS)
        if sampler is None:
            sampler = ProvisionalSampler(center, streams[1:])
        log = EventLog(run_id, profile.start_date, sink)
    else:
        streams = child_streams(seed, N_CLINICAL_STREAMS)
        sampler = ClinicalSampler(profiles, profile.start_date, center, streams[1:])
        log = EventLog(run_id, profile.start_date, sink, schema_version=CLINICAL_SCHEMA_VERSION)
    arrivals = iter_arrivals(profile, days, streams[0], on_day=day_records.append)
    run = run_engine(center, arrivals, sampler, log, days)
    return EDResult(
        run_id=run_id,
        ground_truth=GroundTruth(episodes=run.episodes, days=tuple(day_records)),
        inside=run.inside,
        warmup_days=warmup_days,
    )
