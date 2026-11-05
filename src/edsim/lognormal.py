"""The lognormal by its median and 90th percentile, shared by the engine and the profiles.

The configuration files give each duration as ``[mediana, p90]`` in minutes.
``lognormal_params`` turns that pair into the parameters of the normal behind
the lognormal. It lives in a neutral module so that ``edsim.profiles`` can use
it without importing the engine; ``edsim.engine.clinical`` re-exports it.
"""

import math
from statistics import NormalDist

Z90 = NormalDist().inv_cdf(0.9)
"""90th percentile of the standard normal, 1.2815515..."""


def lognormal_params(median: float, p90: float) -> tuple[float, float]:
    """Parameters ``(mu, sigma)`` of the normal behind a lognormal.

    If ``X = exp(Y)`` with ``Y ~ Normal(mu, sigma)``, the median of ``X`` is
    ``exp(mu)`` and its 90th percentile is ``exp(mu + Z90 * sigma)``. Solving
    for both gives ``mu = ln(median)`` and
    ``sigma = (ln(p90) - ln(median)) / Z90``.

    These are what ``numpy.random.Generator.lognormal(mean, sigma)`` expects:
    the mean and the standard deviation of the normal, not of the lognormal.

    Args:
        median: Median of the lognormal; positive.
        p90: 90th percentile; greater than the median.

    Returns:
        ``(mu, sigma)``.

    Raises:
        ValueError: If the median is not positive or ``p90 <= median``.
    """
    if not median > 0:
        raise ValueError(f"median must be positive, got {median!r}")
    if not p90 > median:
        raise ValueError(f"p90 must be greater than the median, got {p90!r} <= {median!r}")
    mu = math.log(median)
    return mu, (math.log(p90) - mu) / Z90
