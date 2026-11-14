"""Identifiers that can safely name a persisted run directory.

``validate_run_id`` lives in the neutral ``edsim.identifiers`` (task 7.1); it is
re-exported here so that the imports from ``edsim.runs`` keep working.
"""

from edsim.identifiers import validate_run_id

__all__ = ["validate_run_id"]
