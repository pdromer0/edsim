"""Analysis of a single M/M/1 run: step series and samples of its random times.

``mm1_metrics`` reduces a run to a handful of numbers. The functions here keep
more of the run so it can be inspected and plotted: the number in queue and in
system as step functions of time, averages and samples of those steps, and the
inter-arrival and service times that fed the simulation.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike

from edsim.queueing.mm1 import CustomerRecord


@dataclass(frozen=True)
class Occupancy:
    """Number in queue and in system of one run, as step functions of time.

    Value ``i`` holds from ``times[i]`` until ``times[i + 1]`` (the last one
    until ``horizon``). Simultaneous events are merged, so ``times`` is
    strictly increasing and starts at 0 with the system empty unless a
    customer arrives exactly at 0.

    Attributes:
        times: Instants at which the state changes, starting at 0.
        in_queue: Customers waiting for the server after each change.
        in_system: Customers waiting or in service after each change.
        horizon: End of the run.
    """

    times: np.ndarray
    in_queue: np.ndarray
    in_system: np.ndarray
    horizon: float

    @property
    def busy(self) -> np.ndarray:
        """Customers in service (0 or 1) after each change."""
        return self.in_system - self.in_queue

    @property
    def edges(self) -> np.ndarray:
        """Step edges, ``times`` followed by ``horizon``, as ``ax.stairs`` expects."""
        return np.append(self.times, self.horizon)


def occupancy(records: Sequence[CustomerRecord], horizon: float) -> Occupancy:
    """Build the number-in-queue and number-in-system step series of a run.

    Every arrival adds one customer to the queue and to the system, every
    service start removes one from the queue and every departure removes one
    from the system. Customers still waiting or in service at the end simply
    have no later event.

    Raises:
        ValueError: If an event happens after ``horizon``.
    """
    event_times = [0.0]
    queue_deltas = [0]
    system_deltas = [0]
    for r in records:
        event_times.append(r.arrival)
        queue_deltas.append(1)
        system_deltas.append(1)
        if r.service_start is not None:
            event_times.append(r.service_start)
            queue_deltas.append(-1)
            system_deltas.append(0)
        if r.departure is not None:
            event_times.append(r.departure)
            queue_deltas.append(0)
            system_deltas.append(-1)

    times, group = np.unique(np.array(event_times), return_inverse=True)
    if times[-1] > horizon:
        raise ValueError(f"an event happens at {times[-1]}, after the horizon {horizon}")
    # Add up the changes of each instant, then accumulate them in time order.
    in_queue = np.cumsum(np.bincount(group, weights=queue_deltas)).astype(int)
    in_system = np.cumsum(np.bincount(group, weights=system_deltas)).astype(int)
    return Occupancy(times=times, in_queue=in_queue, in_system=in_system, horizon=float(horizon))


def step_time_average(times: ArrayLike, values: ArrayLike, start: float, end: float) -> float:
    """Average of a step function over ``[start, end]``: its area divided by the length.

    ``values[i]`` holds from ``times[i]`` until ``times[i + 1]``, and the last
    value holds forever. Before ``times[0]`` the function is 0.

    Raises:
        ValueError: If ``start`` is not smaller than ``end``.
    """
    if start >= end:
        raise ValueError(f"start must be smaller than end, got {start=} and {end=}")
    t = np.asarray(times, dtype=float)
    v = np.asarray(values, dtype=float)
    next_t = np.append(t[1:], np.inf)
    covered = np.clip(np.minimum(next_t, end) - np.maximum(t, start), 0.0, None)
    return float(np.sum(covered * v) / (end - start))


def sample_step(times: ArrayLike, values: ArrayLike, grid: ArrayLike) -> np.ndarray:
    """Value of a step function at each instant of ``grid``.

    At a change instant the function already has its new value. Before
    ``times[0]`` it is 0. Sampling several runs on the same grid lets them be
    averaged instant by instant.
    """
    t = np.asarray(times, dtype=float)
    v = np.asarray(values)
    index = np.searchsorted(t, np.asarray(grid, dtype=float), side="right") - 1
    return np.where(index >= 0, v[np.maximum(index, 0)], 0)


def interarrival_times(records: Sequence[CustomerRecord]) -> np.ndarray:
    """Times between consecutive arrivals; the first is measured from 0."""
    return np.diff([r.arrival for r in records], prepend=0.0)


def service_times(records: Sequence[CustomerRecord]) -> np.ndarray:
    """Service times drawn for each customer when they arrived."""
    return np.array([r.service_time for r in records])


def residual_times(samples: ArrayLike, elapsed: float) -> np.ndarray:
    """What is left of the samples that last longer than ``elapsed``.

    For an exponential distribution the residual times have the same
    distribution as the original samples: it has no memory.

    Raises:
        ValueError: If ``elapsed`` is negative.
    """
    if elapsed < 0:
        raise ValueError(f"elapsed must be non-negative, got {elapsed}")
    x = np.asarray(samples, dtype=float)
    return x[x > elapsed] - elapsed
