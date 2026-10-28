"""Summary statistics and confidence intervals for simulation outputs."""

import math
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
from scipy import stats


@dataclass(frozen=True, slots=True)
class Summary:
    """Sample statistics of a set of independent values, such as replications.

    Attributes:
        n: Number of values.
        mean: Sample mean.
        std: Sample standard deviation, with ``n - 1`` in the denominator.
        sem: Standard error of the mean, ``std / sqrt(n)``.
        ci_low: Lower bound of the confidence interval for the mean.
        ci_high: Upper bound of the confidence interval for the mean.
        confidence: Confidence level of the interval, e.g. ``0.95``.
    """

    n: int
    mean: float
    std: float
    sem: float
    ci_low: float
    ci_high: float
    confidence: float


def summarize(values: Iterable[float], confidence: float = 0.95) -> Summary:
    """Summarize values with a Student's t confidence interval for the mean.

    The interval is ``mean ± t * sem``, where ``t`` is the ``(1 + confidence)
    / 2`` quantile of Student's t distribution with ``n - 1`` degrees of
    freedom. The t distribution, rather than the normal, accounts for the
    standard deviation being estimated from few values; it assumes the values
    are independent and roughly normal, which holds for means of long
    replications.

    Args:
        values: Independent observations, typically one per replication.
        confidence: Confidence level, strictly between 0 and 1.

    Returns:
        The summary of the values.

    Raises:
        ValueError: If there are fewer than 2 values or ``confidence`` is not
            strictly between 0 and 1.
    """
    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be strictly between 0 and 1, got {confidence}")
    x = np.asarray(list(values), dtype=float)
    n = x.size
    if n < 2:
        raise ValueError(f"at least 2 values are needed for a confidence interval, got {n}")

    mean = float(x.mean())
    std = float(x.std(ddof=1))
    sem = std / math.sqrt(n)
    t = float(stats.t.ppf((1 + confidence) / 2, df=n - 1))
    half_width = t * sem

    return Summary(
        n=n,
        mean=mean,
        std=std,
        sem=sem,
        ci_low=mean - half_width,
        ci_high=mean + half_width,
        confidence=confidence,
    )
