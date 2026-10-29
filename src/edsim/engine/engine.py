"""The engine: arrivals, patients and the horizon, in one SimPy environment.

``run_engine`` is the core: it takes the arrivals as an iterable and the
draws of each patient as an injectable function, so that tests can build exact
scenarios by hand. For each arrival it calls the sampler, in arrival order,
keeps the ground truth of the episode and starts the patient process. The run
stops at ``days * 1440`` minutes: events scheduled at that instant or later do
not happen, and patients still inside have no ``patient_departed``.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

import simpy

from edsim.arrivals.rate import MINUTES_PER_DAY
from edsim.arrivals.thinning import ArrivalRecord, arrival_source
from edsim.engine.center import CenterConfig
from edsim.engine.clinical import PatientDraws
from edsim.engine.events import EventLog
from edsim.engine.ground_truth import EpisodeTruth
from edsim.engine.patient import patient
from edsim.engine.resources import make_pools

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
