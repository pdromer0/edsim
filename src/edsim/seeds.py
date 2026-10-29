"""Independent random streams derived from one seed (ADR 0007).

Each source of randomness in a run (arrivals, daily effect, services...) gets
its own child of the run's ``numpy.random.SeedSequence``, so that drawing more
or fewer numbers from one source never shifts the numbers of another.

``SeedSequence.spawn`` is not suitable for this when the seed is passed in by
the caller: it advances a counter inside the object, so spawning twice from
the same object gives different children, and a run repeated with the same
``SeedSequence`` would not reproduce. ``child_streams`` builds the same
children as ``spawn`` on a fresh object, without changing the one it gets.
"""

import numpy as np


def child_streams(seed: int | np.random.SeedSequence, n: int) -> list[np.random.SeedSequence]:
    """The first ``n`` children of a seed, without modifying it.

    The result is exactly ``SeedSequence(seed).spawn(n)`` for an integer, and
    what ``spawn(n)`` gives on a fresh copy of a ``SeedSequence``: child ``i``
    has the parent's ``spawn_key`` followed by ``i``. Calling it twice with
    the same object gives the same children.

    Args:
        seed: An integer or a ``numpy.random.SeedSequence``, such as one child
            of ``SeedSequence(master).spawn(R)`` per replication. An integer is
            equivalent to ``SeedSequence(seed)``.
        n: Number of children; a positive integer.

    Returns:
        The ``n`` children, one per source of randomness.

    Raises:
        ValueError: If ``n`` is not a positive integer.
    """
    # bool is a subclass of int in Python: True must not pass as 1.
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValueError(f"n must be a positive integer, got {n!r}")
    parent = seed if isinstance(seed, np.random.SeedSequence) else np.random.SeedSequence(seed)
    return [
        np.random.SeedSequence(
            parent.entropy, spawn_key=(*parent.spawn_key, i), pool_size=parent.pool_size
        )
        for i in range(n)
    ]
