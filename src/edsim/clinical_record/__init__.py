"""The simulator of the clinical record: what the hospital writes down of the truth.

The engine writes the truth; ``record`` turns it into what was written down,
with the eight slips of a profile, into a derived run with its own ``run_id``
(docs/specs/hito-7.md, decisions 84 to 88). It imports neither SimPy nor the
engine: only the catalog of ``edsim.engine.events``.

- ``records``: ``Record`` and ``record_json``;
- ``record``: the dice (``Roll``, ``StreamDice``), the profile in code, ``record`` and
  its waiting room for the live run, ``RecordStream``;
- ``profiles``: the load and the validation of ``config/registro_clinico.toml``;
- ``notebook``: ``defectos.csv`` and the account that balances;
- ``compare``: the reconciliation with the truth and the naive indicators;
- ``schemas``: the JSON Schema of the records, ``schemas/registro-v*.schema.json``.
"""

from edsim.clinical_record.compare import (
    Comparison,
    DelayStats,
    IndicatorRow,
    Indicators,
    Reconciliation,
    ReconciliationError,
    SlipCounts,
    compare,
)
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
    read_notebook_csv,
)
from edsim.clinical_record.profiles import (
    DEFAULT_PROFILES_FILE,
    PROFILE_NAMES,
    RecordProfiles,
    load_record_profiles,
)
from edsim.clinical_record.record import (
    ROLL_SIZE,
    SYSTEMS,
    WRONG_FIELDS,
    Dice,
    Recording,
    RecordProfile,
    RecordStream,
    Roll,
    StreamDice,
    Timed,
    derived_run_id,
    record,
)
from edsim.clinical_record.records import (
    RECORD_CORRECTED,
    Record,
    record_from_json,
    record_json,
)

__all__ = [
    "CORRECTION",
    "DEFAULT_PROFILES_FILE",
    "CORRECTION_PENDING",
    "DUPLICATE",
    "GOOD",
    "KINDS",
    "LOST",
    "NOTEBOOK_COLUMNS",
    "PENDING",
    "PROFILE_NAMES",
    "RECORD_CORRECTED",
    "ROLL_SIZE",
    "SYSTEMS",
    "WITH_SLIPS",
    "WRONG_FIELDS",
    "Account",
    "Comparison",
    "DelayStats",
    "Dice",
    "IndicatorRow",
    "Indicators",
    "NotebookRow",
    "Record",
    "RecordProfile",
    "RecordProfiles",
    "RecordStream",
    "Reconciliation",
    "ReconciliationError",
    "Recording",
    "Roll",
    "SlipCounts",
    "StreamDice",
    "Timed",
    "account",
    "compare",
    "derived_run_id",
    "load_record_profiles",
    "notebook_csv",
    "read_notebook_csv",
    "record",
    "record_from_json",
    "record_json",
]
