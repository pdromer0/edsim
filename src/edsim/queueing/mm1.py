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

This module only produces per-customer records; metrics are computed from
them elsewhere.
"""

from collections.abc import Generator
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


def simulate_mm1(lam: float, mu: float, horizon: float, seed: int) -> tuple[CustomerRecord, ...]:
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
        seed: Seed of the run. Two independent streams, arrivals and service,
            are derived from it with ``numpy.random.SeedSequence.spawn``.

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

    arrival_seq, service_seq = np.random.SeedSequence(seed).spawn(2)
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
