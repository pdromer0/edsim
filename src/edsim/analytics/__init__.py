"""The analytics of milestone 8 seen from the core: the micro-batches of dbt (task 8.7).

dbt lives in its own environment (``analitica/``, with its own ``uv.lock``): the core never
imports it, and ``refresh`` launches it as a subprocess. The loop gets the build and the clock
injected, so its tests run without dbt, Postgres or waiting.
"""

from edsim.analytics.refresh import (
    DBT_BUILD,
    DEFAULT_EVERY,
    BuildResult,
    Clock,
    RefreshSummary,
    dbt_builder,
    dbt_command,
    dbt_environment,
    refresh,
)

__all__ = [
    "DBT_BUILD",
    "DEFAULT_EVERY",
    "BuildResult",
    "Clock",
    "RefreshSummary",
    "dbt_builder",
    "dbt_command",
    "dbt_environment",
    "refresh",
]
