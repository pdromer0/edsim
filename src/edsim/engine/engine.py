"""The engine: arrivals, patients and the horizon, in one SimPy environment.

``run_engine`` is the core: it takes the arrivals as an iterable and the
draws of each patient as an injectable function, so that tests can build exact
scenarios by hand. For each arrival it calls the sampler, in arrival order,
keeps the ground truth of the episode and starts the patient process. The run
stops at ``days * 1440`` minutes: events scheduled at that instant or later do
not happen, and patients still inside have no ``patient_departed``.

``simulate_ed`` is the run with a seed: it derives five independent streams
with ``child_streams(seed, 5)`` (ADR 0007). Stream 0 goes as it is to
``iter_arrivals``, so the arrivals are the same as the arrival generator's
with that stream; streams 1 to 4 go to the ``ProvisionalSampler`` (level,
durations, tests and destination). Adding a stream in milestone 4 will not
change these, because each child depends only on its index.
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
from edsim.engine.events import EventLog, EventSink
from edsim.engine.ground_truth import EpisodeTruth, GroundTruth
from edsim.engine.patient import patient
from edsim.engine.resources import make_pools
from edsim.seeds import child_streams

N_STREAMS = 5
"""Streams of a run: arrivals, then the four of the sampler."""

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
    """

    run_id: str
    ground_truth: GroundTruth
    inside: int


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
    run_id: str | None = None,
    sampler: Sampler | None = None,
) -> EDResult:
    """Simulate the emergency department for ``days`` full days.

    Args:
        center: Staff, boxes and the provisional clinical model.
        profile: Arrival profile; its ``start_date`` is minute 0 of the log.
        days: Horizon in full days, warm-up included; a positive integer.
        seed: Seed of the run: an integer or a ``SeedSequence``, which is not
            modified, so the same object gives the same run.
        sink: Where the events go, such as ``MemorySink`` or ``JsonlSink``.
        run_id: Identifier of the run; ``default_run_id(seed)`` if ``None``.
        sampler: Draws of each patient; a ``ProvisionalSampler`` with streams
            1 to 4 if ``None``. Injected only in tests.

    Returns:
        The run identifier, the ground truth and the patients still inside.

    Raises:
        ValueError: If ``days`` is not a positive integer.
    """
    days = _check_days(days)
    streams = child_streams(seed, N_STREAMS)
    if run_id is None:
        run_id = default_run_id(seed)
    if sampler is None:
        sampler = ProvisionalSampler(center, streams[1:])

    day_records: list[DayRecord] = []
    arrivals = iter_arrivals(profile, days, streams[0], on_day=day_records.append)
    log = EventLog(run_id, profile.start_date, sink)
    run = run_engine(center, arrivals, sampler, log, days)
    return EDResult(
        run_id=run_id,
        ground_truth=GroundTruth(episodes=run.episodes, days=tuple(day_records)),
        inside=run.inside,
    )
