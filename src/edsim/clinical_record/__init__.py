"""The simulator of the clinical record: what the hospital writes down of the truth.

The engine writes the truth; ``record`` turns it into what was written down,
with the eight slips of a profile, into a derived run with its own ``run_id``
(docs/specs/hito-7.md, decisions 84 to 88). It imports neither SimPy nor the
engine: only the catalog of ``edsim.engine.events``.

- ``records``: ``Record`` and ``record_json``;
- ``record``: the dice, the profile in code and ``record``;
- ``notebook``: ``defectos.csv`` and the account that balances;
- ``schemas``: the JSON Schema of the records, ``schemas/registro-v*.schema.json``.
"""

from edsim.clinical_record.notebook import (
    CORRECTION,
    CORRECTION_PENDING,
    DUPLICATE,
    GOOD,
    KINDS,
    LOST,
    NOTEBOOK_COLUMNS,
    PENDING,
    WITH_SLIPS,
    Account,
    NotebookRow,
    account,
    notebook_csv,
)
from edsim.clinical_record.record import (
    ROLL_SIZE,
    SYSTEMS,
    WRONG_FIELDS,
    Dice,
    Recording,
    RecordProfile,
    Roll,
    Timed,
    derived_run_id,
    record,
)
from edsim.clinical_record.records import RECORD_CORRECTED, Record, record_json

__all__ = [
    "CORRECTION",
    "CORRECTION_PENDING",
    "DUPLICATE",
    "GOOD",
    "KINDS",
    "LOST",
    "NOTEBOOK_COLUMNS",
    "PENDING",
    "RECORD_CORRECTED",
    "ROLL_SIZE",
    "SYSTEMS",
    "WITH_SLIPS",
    "WRONG_FIELDS",
    "Account",
    "Dice",
    "NotebookRow",
    "Record",
    "RecordProfile",
    "Recording",
    "Roll",
    "Timed",
    "account",
    "derived_run_id",
    "notebook_csv",
    "record",
    "record_json",
]
