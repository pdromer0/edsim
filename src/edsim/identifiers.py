"""Identifiers that can safely name a persisted run directory.

It lives in a neutral module, without the engine, so that
``edsim.clinical_record`` can validate the ``run_id`` of a derived run: importing
``edsim.runs.identifiers`` runs ``edsim/runs/__init__.py``, which loads the
engine and SimPy. ``edsim.runs.identifiers`` re-exports it.
"""

import re

_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def validate_run_id(run_id: str) -> str:
    """Return an ASCII directory identifier, or raise ValueError."""
    if not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None:
        raise ValueError(
            "run_id must contain 1–64 ASCII letters, digits, '.', '-' or '_', "
            "starting with a letter or digit"
        )
    return run_id
