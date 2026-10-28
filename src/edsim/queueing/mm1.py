"""Discrete-event simulation of an M/M/1 queue with SimPy.

The model has three parts:

- An arrival generator that waits an exponential inter-arrival time with
  mean ``1 / lam`` and then creates a customer process.
- Customer processes that request the server, wait for their turn (FIFO),
  hold the server for their service time and release it.
- The server, a ``simpy.Resource`` with capacity 1.

Waiting times are never sampled: they emerge from the queue. All randomness
comes from two independent streams derived from the seed, one for arrivals
and one for service, so the same seed reproduces the run exactly.

The simulation produces per-customer records; ``mm1_metrics`` turns the
records of one run into the metrics that are compared with the theory.
"""

from collections.abc import Generator, Sequence
from dataclasses import dataclass

import numpy as np
import simpy

from edsim.queueing.theory import validate_mm1_rates


@dataclass(frozen=True, slots=True)
class CustomerRecord:
    """What happened to one customer during a simulation run.

    Times are in the same unit as the rates. ``None`` means the event did not
    happen before the end of the run: no value is made up for it.

    Attributes:
        customer_id: Arrival order, starting at 0.
        arrival: Time the customer joined the system.
        service_time: Service duration drawn when the customer arrived. It is
            known even if service never started or did not finish.
        service_start: Time service began, or ``None`` if still waiting.
        departure: Time service ended, or ``None`` if not finished.
    """

    customer_id: int
    arrival: float
    service_time: float
    service_start: float | None
    departure: float | None

    @property
    def is_complete(self) -> bool:
        """Whether the customer finished service before the end of the run."""
        return self.departure is not None


def simulate_mm1(
    lam: float, mu: float, horizon: float, seed: int | np.random.SeedSequence
) -> tuple[CustomerRecord, ...]:
    """Simulate one replication of an M/M/1 queue that starts empty.

    The service time is drawn when the customer arrives, not when service
    starts. Customer number ``k`` therefore always gets the ``k``-th draw of
    the service stream, whatever happens to the rest of the system. This is
    what makes common random numbers work when comparing experiments.

    Args:
        lam: Arrival rate (customers per unit of time).
        mu: Service rate (customers per unit of time).
        horizon: Total simulated time. Events scheduled at or after this time
            do not happen.
        seed: Seed of the run: an integer or a ``numpy.random.SeedSequence``,
            such as one child of ``SeedSequence(master).spawn(R)`` per
            replication. An integer is equivalent to ``SeedSequence(seed)``.
            Two independent streams, arrivals and service, are derived from it
            with ``SeedSequence.spawn``.

    Returns:
        One record per customer who arrived before ``horizon``, in arrival
        order. Customers still waiting or in service at the end are included
        with ``service_start`` and/or ``departure`` set to ``None``.

    Raises:
        ValueError: If the rates are not valid for a stable M/M/1 queue or
            ``horizon`` is not positive.
    """
    validate_mm1_rates(lam, mu)
    if horizon <= 0:
        raise ValueError(f"horizon must be positive, got {horizon}")

    seed_seq = seed if isinstance(seed, np.random.SeedSequence) else np.random.SeedSequence(seed)
    arrival_seq, service_seq = seed_seq.spawn(2)
    arrival_rng = np.random.default_rng(arrival_seq)
    service_rng = np.random.default_rng(service_seq)

    env = simpy.Environment()
    server = simpy.Resource(env, capacity=1)

    # Mutable notes while the simulation runs; frozen into records at the end.
    arrivals: list[float] = []
    service_times: list[float] = []
    starts: dict[int, float] = {}
    departures: dict[int, float] = {}

    def customer(customer_id: int, service_time: float) -> Generator[simpy.Event]:
        with server.request() as request:
            yield request
            starts[customer_id] = env.now
            yield env.timeout(service_time)
            departures[customer_id] = env.now

    def arrival_generator() -> Generator[simpy.Event]:
        customer_id = 0
        while True:
            # numpy's exponential takes the scale (mean = 1 / rate), not the rate.
            yield env.timeout(arrival_rng.exponential(1 / lam))
            service_time = service_rng.exponential(1 / mu)
            arrivals.append(env.now)
            service_times.append(service_time)
            env.process(customer(customer_id, service_time))
            customer_id += 1

    env.process(arrival_generator())
    env.run(until=horizon)

    return tuple(
        CustomerRecord(
            customer_id=i,
            arrival=arrivals[i],
            service_time=service_times[i],
            service_start=starts.get(i),
            departure=departures.get(i),
        )
        for i in range(len(arrivals))
    )


@dataclass(frozen=True, slots=True)
class MM1Metrics:
    """Metrics of one M/M/1 run over an observation window.

    Attributes:
        wq: Mean waiting time in queue of the customers that arrived inside the
            window and finished before its end (a per-customer average).
        w: Mean time in system of the same customers.
        lq: Time-average number of customers waiting in queue.
        l: Time-average number of customers in the system.
        rho: Fraction of the window during which the server was busy.
        n_customers: Number of customers averaged for ``wq`` and ``w``.
        lam_obs: Observed arrival rate, arrivals inside the window divided by
            its length. Used to check Little's law, ``l ≈ lam_obs * w``.
    """

    wq: float
    w: float
    lq: float
    # `l` is the standard queueing notation for the mean number in system.
    l: float  # noqa: E741
    rho: float
    n_customers: int
    lam_obs: float


def _time_in_window(start: float, end: float, window_start: float, window_end: float) -> float:
    """Length of the interval ``[start, end]`` that falls inside the window."""
    return max(0.0, min(end, window_end) - max(start, window_start))


def mm1_metrics(records: Sequence[CustomerRecord], warmup: float, horizon: float) -> MM1Metrics:
    """Compute the metrics of one run over the window ``[warmup, horizon]``.

    The first ``warmup`` time units are discarded because the queue starts
    empty, which is not representative of the steady state.

    - ``wq`` and ``w`` average over customers who arrived at or after
      ``warmup`` and completed service. Customers still in the system at the
      end are left out, because their times are unknown.
    - ``lq``, ``l`` and ``rho`` are time averages: the area under the
      number-in-queue, number-in-system and busy-server curves, divided by the
      window length. Each customer's stay is clipped to the window, and
      customers still waiting or in service at the end count until
      ``horizon``, since they are in the system up to then. With these
      definitions ``l == lq + rho`` exactly.

    Args:
        records: Records of one run, as returned by ``simulate_mm1``.
        warmup: Start of the observation window.
        horizon: End of the observation window; the simulated horizon.

    Returns:
        The metrics of the window.

    Raises:
        ValueError: If ``warmup`` is negative or not smaller than ``horizon``,
            or if no customer arrived and completed inside the window.
    """
    if warmup < 0 or warmup >= horizon:
        raise ValueError(f"warmup must satisfy 0 <= warmup < horizon, got {warmup=} and {horizon=}")
    length = horizon - warmup

    area_queue = area_system = area_busy = 0.0
    waits: list[float] = []
    sojourns: list[float] = []
    arrivals_in_window = 0

    for r in records:
        # Customers still in the system at the end stay until the horizon.
        start = r.service_start if r.service_start is not None else horizon
        end = r.departure if r.departure is not None else horizon

        area_queue += _time_in_window(r.arrival, start, warmup, horizon)
        area_system += _time_in_window(r.arrival, end, warmup, horizon)
        if r.service_start is not None:
            area_busy += _time_in_window(r.service_start, end, warmup, horizon)

        if warmup <= r.arrival < horizon:
            arrivals_in_window += 1
            if r.is_complete:
                waits.append(r.service_start - r.arrival)
                sojourns.append(r.departure - r.arrival)

    if not waits:
        raise ValueError("no customer arrived and completed inside the window")

    return MM1Metrics(
        wq=sum(waits) / len(waits),
        w=sum(sojourns) / len(sojourns),
        lq=area_queue / length,
        l=area_system / length,
        rho=area_busy / length,
        n_customers=len(waits),
        lam_obs=arrivals_in_window / length,
    )
