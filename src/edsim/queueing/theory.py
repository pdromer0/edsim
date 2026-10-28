"""Steady-state theory of the M/M/1 queue.

In Kendall notation, M/M/1 means Markovian (Poisson) arrivals with rate
``lam``, Markovian (exponential) service times with rate ``mu`` and a single
server with a FIFO queue.

The formulas below describe the long-run (steady-state) behaviour of the
queue. A steady state exists only when the utilisation ``rho = lam / mu`` is
strictly less than 1: otherwise customers arrive faster than they can be
served and the queue grows without bound.

These values are the reference against which the SimPy model is validated.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MM1Theory:
    """Steady-state metrics of an M/M/1 queue.

    Time-based metrics are in the same time unit as the rates; counts are
    numbers of customers.

    Attributes:
        rho: Server utilisation, ``rho = lam / mu``. Long-run fraction of time
            the server is busy, and the probability that an arriving customer
            has to wait.
        wq: Mean waiting time in the queue, before service starts,
            ``wq = rho / (mu - lam)``.
        w: Mean time in the system (waiting plus service),
            ``w = 1 / (mu - lam)``. Equivalently ``w = wq + 1 / mu``.
        lq: Mean number of customers waiting in the queue,
            ``lq = rho**2 / (1 - rho)``.
        l: Mean number of customers in the system (waiting plus in service),
            ``l = rho / (1 - rho)``.

    The four metrics satisfy Little's law, ``l = lam * w`` and
    ``lq = lam * wq``. All of them grow like ``1 / (1 - rho)``, which is why
    waits explode as utilisation approaches 100 %.
    """

    rho: float
    wq: float
    w: float
    lq: float
    # `l` is the standard queueing notation for the mean number in system.
    l: float  # noqa: E741


def mm1_theory(lam: float, mu: float) -> MM1Theory:
    """Compute the steady-state metrics of an M/M/1 queue.

    Args:
        lam: Arrival rate (customers per unit of time). Named ``lam`` because
            ``lambda`` is a reserved word in Python.
        mu: Service rate of the single server (customers per unit of time).

    Returns:
        The steady-state metrics ``rho``, ``wq``, ``w``, ``lq`` and ``l``.

    Raises:
        ValueError: If ``lam`` or ``mu`` is not positive, or if
            ``rho = lam / mu >= 1``, in which case no steady state exists.
    """
    if lam <= 0 or mu <= 0:
        raise ValueError(f"rates must be positive, got lam={lam} and mu={mu}")

    rho = lam / mu
    if rho >= 1:
        raise ValueError(f"unstable queue: rho = lam / mu = {rho} must be < 1 for a steady state")

    return MM1Theory(
        rho=rho,
        wq=rho / (mu - lam),
        w=1 / (mu - lam),
        lq=rho**2 / (1 - rho),
        l=rho / (1 - rho),
    )
