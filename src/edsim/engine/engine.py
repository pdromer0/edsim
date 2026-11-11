"""The engine: arrivals, patients and the horizon, in one SimPy environment.

``start_engine`` is the core: it takes the arrivals as an iterable and the
draws of each patient as an injectable function, so that tests can build exact
scenarios by hand. It first starts the shifts (``start_shifts``), which set
the staff of minute 0 and change it at each start of a shift. For each arrival
it calls the sampler, in arrival order, keeps the ground truth of the episode
and starts the patient process. The run stops at ``days * 1440`` minutes:
events scheduled at that instant or later do not happen, and patients still
inside have no ``patient_departed``.

**Stepped engine** (task 6.2, H6-4). ``start_engine`` builds the run and
returns a ``SteppedEngine``, which moves forward with SimPy's ``peek()`` and
``step()`` only: one event at a time, or every event before an instant. The
live mode of milestone 6 waits between events with it. ``run_engine`` is
``start_engine`` and ``advance_until`` the horizon, and gives the same log,
bit for bit, as the ``env.run(until=horizon)`` it replaces: ``run`` schedules
a stop event at the horizon with ``URGENT`` priority, before the normal events
of that instant, and SimPy only schedules urgent events with delay 0, so no
event at the horizon can come before the stop. Both run exactly the events
before the horizon, in the same order (docs/specs/hito-6.md, piece 1).

``simulate_ed`` is the run with a seed: it derives five independent streams
with ``child_streams(seed, 5)`` (ADR 0007). Stream 0 goes as it is to
``iter_arrivals``, so the arrivals are the same as the arrival generator's
with that stream; streams 1 to 4 go to the ``ProvisionalSampler`` (level,
durations, tests and destination).

With clinical profiles (task 4.5a), ``simulate_ed`` derives eight streams with
``child_streams(seed, 8)``: the first five are the same five children, because
each child depends only on its index, so the arrivals do not change; streams 1
to 7 go to the ``ClinicalSampler``, and the log is of version 3 of the catalog.
``start_ed`` prepares all that and returns a ``SteppedED``; ``simulate_ed``
advances it to the horizon.
"""

import math
import numbers
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import numpy as np
import simpy

from edsim.arrivals.profile import ArrivalProfile
from edsim.arrivals.rate import MINUTES_PER_DAY
from edsim.arrivals.thinning import ArrivalRecord, DayRecord, arrival_source, iter_arrivals
from edsim.engine.center import CenterConfig
from edsim.engine.clinical import PatientDraws, ProvisionalSampler
from edsim.engine.clinical_sampler import ClinicalSampler, PatientModel, choose_model
from edsim.engine.events import (
    EventLog,
    EventSink,
    episode_id,
)
from edsim.engine.ground_truth import EpisodeTruth, GroundTruth
from edsim.engine.patient import patient
from edsim.engine.resources import make_pools
from edsim.engine.shifts import start_shifts
from edsim.profiles.config import ClinicalProfiles
from edsim.seeds import child_streams

N_STREAMS = PatientModel.PROVISIONAL.n_streams
"""Streams of a run: arrivals, then the four of the sampler."""

N_CLINICAL_STREAMS = PatientModel.MILESTONE_4.n_streams
"""Streams of a run of milestone 4: arrivals, then the seven of the sampler (``PatientModel``)."""

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


def _check_instant(t: object) -> numbers.Real:
    # bool is a subclass of int in Python; NaN would stop nothing without a word.
    if isinstance(t, bool) or not isinstance(t, numbers.Real) or math.isnan(t):
        raise ValueError(f"t must be a number of minutes, got {t!r}")
    return t


class SteppedEngine:
    """A run of the engine that moves forward one event at a time, up to the horizon.

    Built by ``start_engine``. It only uses ``env.peek()`` and ``env.step()``:
    ``env.run`` would schedule a stop event of its own in the queue each time
    it is called. Events at the horizon or later never happen, as with
    ``env.run(until=horizon)``.

    Attributes:
        horizon: ``days * 1440`` minutes.
    """

    def __init__(
        self,
        center: CenterConfig,
        arrivals: Iterable[ArrivalRecord],
        sampler: Sampler,
        log: EventLog,
        days: int,
    ) -> None:
        self.horizon = days * MINUTES_PER_DAY
        self._env = env = simpy.Environment()
        self._pools = make_pools(env, center)
        self._log = log
        self._sampler = sampler
        # Before any other process: the staffing_changed of minute 0 go first in the
        # log, and each change of shift is the first event of its instant.
        start_shifts(env, log, self._pools, center, days)
        self._episodes: list[EpisodeTruth] = []
        self._patients: list[tuple[int, simpy.Process]] = []
        # Only the clinical patients use it (leaves_for_results): the provisional
        # model ignores espera_resultados_fuera.
        self._wait_outside = frozenset(center.results_wait_outside)
        env.process(arrival_source(env, arrivals, self._on_arrival))

    def _on_arrival(self, arrival: ArrivalRecord) -> None:
        draws = self._sampler(arrival)
        self._episodes.append(EpisodeTruth.from_draws(arrival, draws))
        process = self._env.process(
            patient(
                self._env, self._log, self._pools, arrival.arrival_id, draws, self._wait_outside
            )
        )
        self._patients.append((arrival.arrival_id, process))

    def peek(self) -> float:
        """Instant of the next event; ``math.inf`` at the horizon or later, or if none is left."""
        t = self._env.peek()
        return t if t < self.horizon else math.inf

    def step(self) -> None:
        """Run the next event: one SimPy event, which may emit several events of the log.

        Raises:
            RuntimeError: If no event is left before the horizon (``peek()`` is
                infinite).
        """
        if self.peek() == math.inf:
            raise RuntimeError(f"no event left before the horizon ({self.horizon} min)")
        self._env.step()

    def advance_until(self, t: float) -> None:
        """Run every event before ``t``, and none at ``t`` or later.

        Never goes past the horizon: with ``t`` above it, it stops there. A
        ``t`` before the next event does nothing.

        Raises:
            ValueError: If ``t`` is not a number or is NaN.
        """
        limit = min(_check_instant(t), self.horizon)
        peek, step = self._env.peek, self._env.step
        while peek() < limit:
            step()

    def alive_episodes(self) -> frozenset[str]:
        """Episodes whose patient process is still alive in SimPy now.

        A process ends in the same step that emits its ``patient_departed``,
        and starts in the instant of its arrival; so, after ``advance_until(t)``,
        these are the episodes with events before ``t`` and no departure
        before ``t``. Counted from SimPy, not from the log.
        """
        return frozenset(episode_id(i) for i, process in self._patients if process.is_alive)

    def finish(self) -> EngineRun:
        """The ground truth of the episodes and the patients still inside, at the horizon.

        Raises:
            RuntimeError: If some event before the horizon has not run yet.
        """
        if self.peek() != math.inf:
            raise RuntimeError(
                f"the run has not reached the horizon ({self.horizon} min): "
                f"next event at {self.peek()!r}; call advance_until(horizon) first"
            )
        return EngineRun(
            episodes=tuple(self._episodes),
            inside=sum(process.is_alive for _, process in self._patients),
        )


def start_engine(
    center: CenterConfig,
    arrivals: Iterable[ArrivalRecord],
    sampler: Sampler,
    log: EventLog,
    days: int,
) -> SteppedEngine:
    """Build a run of the center for ``days`` full days, without running any event.

    Creates the environment and the pools, starts the shifts (the
    ``staffing_changed`` of minute 0 are emitted now) and the arrival source.
    The arguments are those of ``run_engine``.

    Raises:
        ValueError: If ``days`` is not a positive integer.
    """
    return SteppedEngine(center, arrivals, sampler, log, _check_days(days))


def run_engine(
    center: CenterConfig,
    arrivals: Iterable[ArrivalRecord],
    sampler: Sampler,
    log: EventLog,
    days: int,
) -> EngineRun:
    """Simulate the center for ``days`` full days with the given arrivals.

    ``start_engine`` and ``advance_until`` the horizon: the same events, in the
    same order, as ``env.run(until=horizon)``.

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
    engine = start_engine(center, arrivals, sampler, log, days)
    engine.advance_until(engine.horizon)
    return engine.finish()


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


class SteppedED:
    """A run of ``simulate_ed`` that moves forward one event at a time.

    Built by ``start_ed``. ``peek``, ``step``, ``advance_until`` and
    ``alive_episodes`` are those of its ``SteppedEngine``; ``finish`` gives the
    ``EDResult`` that ``simulate_ed`` returns.

    Attributes:
        run_id: Identifier of the run, in every event of the log.
        warmup_days: Full days of warm-up.
        horizon: ``days * 1440`` minutes.
    """

    def __init__(
        self,
        engine: SteppedEngine,
        run_id: str,
        warmup_days: int,
        day_records: list[DayRecord],
    ) -> None:
        self._engine = engine
        self.run_id = run_id
        self.warmup_days = warmup_days
        # Filled by iter_arrivals (on_day) as the days close: the last one, when
        # the last arrival has been handed over, before the horizon.
        self._day_records = day_records

    @property
    def horizon(self) -> int:
        """``days * 1440`` minutes."""
        return self._engine.horizon

    def peek(self) -> float:
        """See ``SteppedEngine.peek``."""
        return self._engine.peek()

    def step(self) -> None:
        """See ``SteppedEngine.step``."""
        self._engine.step()

    def advance_until(self, t: float) -> None:
        """See ``SteppedEngine.advance_until``."""
        self._engine.advance_until(t)

    def alive_episodes(self) -> frozenset[str]:
        """See ``SteppedEngine.alive_episodes``."""
        return self._engine.alive_episodes()

    def finish(self) -> EDResult:
        """What ``simulate_ed`` returns, at the horizon.

        Raises:
            RuntimeError: If some event before the horizon has not run yet.
        """
        run = self._engine.finish()
        return EDResult(
            run_id=self.run_id,
            ground_truth=GroundTruth(episodes=run.episodes, days=tuple(self._day_records)),
            inside=run.inside,
            warmup_days=self.warmup_days,
        )


def start_ed(
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
) -> SteppedED:
    """Prepare a run of ``simulate_ed`` without running any event.

    The same arguments as ``simulate_ed``, checked in the same way: it derives
    the streams, builds the sampler and the ``EventLog`` and starts the engine.
    The live mode uses it to warm up and then go on at its own pace.

    Returns:
        The run, at minute 0; ``finish()`` at the horizon gives the
        ``EDResult``.

    Raises:
        ValueError: As ``simulate_ed``.
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
        # The blocks of the two files choose milestone 4 or 5 (decision 68): its streams
        # and its version of the catalog. Children 0 to 7 are the same in both.
        model = choose_model(center, profiles)
        streams = child_streams(seed, model.n_streams)
        sampler = ClinicalSampler(profiles, profile.start_date, center, streams[1:])
        log = EventLog(run_id, profile.start_date, sink, schema_version=model.schema_version)
    arrivals = iter_arrivals(profile, days, streams[0], on_day=day_records.append)
    engine = start_engine(center, arrivals, sampler, log, days)
    return SteppedED(engine, run_id, warmup_days, day_records)


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

    ``start_ed`` with the same arguments, ``advance_until`` the horizon and
    ``finish``.

    Args:
        center: Shifts, staff, boxes and destination. Without ``profiles``,
            also the provisional block (``[triaje]``, ``[duraciones]`` and
            ``[pruebas]``), which the provisional model needs, as
            ``tests/data/centro_ejemplo.toml``.
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
            8)`` and the log is of version 3; without them, the provisional
            model, exactly as before (ADR 0044). The CLI uses the clinical
            model by default since task 4.9; this function keeps the
            profiles explicit.

    Returns:
        The run identifier, the ground truth, the patients still inside and
        the warm-up.

    Raises:
        ValueError: If ``days`` is not a positive integer, ``warmup_days`` is
            not an integer in [0, ``days``), both ``sampler`` and
            ``profiles`` are given, or the provisional model gets a center
            without the provisional block.
    """
    ed = start_ed(
        center,
        profile,
        days,
        seed,
        sink=sink,
        warmup_days=warmup_days,
        run_id=run_id,
        sampler=sampler,
        profiles=profiles,
    )
    ed.advance_until(ed.horizon)
    return ed.finish()
