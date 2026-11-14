"""The notebook of the slips (``defectos.csv``) and the account that must balance.

One row per record written, and one per true fact or correction that was not
written (docs/specs/hito-7.md, «La libreta»). The columns are Spanish, as the
keys of the payload: they are data. ``retraso_min`` has one meaning in every
written row: the ``sim_time`` of the record minus the ``sim_time`` of its true
fact (7.0 for a delayed triage, 0.5 for a duplicate half a minute after an
undelayed original, 142.0 for a correction of that triage 135 minutes later).
Rows that were not written leave it empty.

``account`` checks the three equalities of the specification, plus one for
the resource events, which pass as they are and count as ``bien``.
"""

import csv
import io
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from edsim.clinical_record.records import Record
from edsim.engine.events import CATALOGS, Event

GOOD = "bien"
"""A fact written down without any slip (resource events too)."""
WITH_SLIPS = "con_despistes"
"""A fact written down with a delay, a clock offset, a wrong value or an empty field."""
DUPLICATE = "duplicado"
"""A second record of a fact, with its own ``event_id``."""
CORRECTION = "correccion"
"""A ``record_corrected`` written down."""
LOST = "perdido"
"""A fact that was forgotten: no record, no duplicate, no correction."""
PENDING = "pendiente"
"""A fact that would have been written down at or after the horizon."""
CORRECTION_PENDING = "correccion_pendiente"
"""A correction that would have been written down at or after the horizon."""

KINDS: tuple[str, ...] = (
    GOOD,
    WITH_SLIPS,
    DUPLICATE,
    CORRECTION,
    LOST,
    PENDING,
    CORRECTION_PENDING,
)
"""Every ``clase`` of the notebook."""

NOTEBOOK_COLUMNS: tuple[str, ...] = (
    "registro",
    "hecho",
    "clase",
    "retraso_min",
    "desfase_min",
    "campo_vacio",
    "campo_erroneo",
    "valor_verdadero",
    "valor_registrado",
    "duplicado_de",
    "corrige",
)
"""Header of ``defectos.csv``, in the order of ``NotebookRow``'s fields."""


@dataclass(frozen=True, slots=True)
class NotebookRow:
    """One row of the notebook; ``None`` is an empty cell.

    Attributes:
        record_id: ``registro``, the ``event_id`` written; ``None`` if not written.
        fact_id: ``hecho``, the true ``event_id`` it comes from (in a
            correction, the one of the corrected fact).
        kind: ``clase``, one of ``KINDS``.
        delay_min: ``retraso_min``, ``sim_time`` of the record minus the one
            of its true fact; ``None`` if not written.
        clock_min: ``desfase_min``, the clock offset of its system; ``None`` if
            not written.
        empty_field: ``campo_vacio``, the field left ``null``.
        wrong_field: ``campo_erroneo``, the field with a wrong value (in a
            correction, the field it corrects).
        true_value: ``valor_verdadero``, the true value of ``wrong_field``.
        recorded_value: ``valor_registrado``, the wrong value written down.
        duplicate_of: ``duplicado_de``, the ``event_id`` written of the original.
        corrects: ``corrige``, the ``event_id`` written of the wrong record.
    """

    record_id: str | None
    fact_id: str
    kind: str
    delay_min: float | None = None
    clock_min: float | None = None
    empty_field: str | None = None
    wrong_field: str | None = None
    true_value: object = None
    recorded_value: object = None
    duplicate_of: str | None = None
    corrects: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS!r}, got {self.kind!r}")


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return repr(value)
    return str(value)


def notebook_csv(rows: Sequence[NotebookRow]) -> str:
    """The text of ``defectos.csv``: the header and one line per row, ``\\n`` at the end of each."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(NOTEBOOK_COLUMNS)
    for row in rows:
        writer.writerow(_cell(getattr(row, name)) for name in NotebookRow.__dataclass_fields__)
    return out.getvalue()


@dataclass(frozen=True, slots=True)
class Account:
    """The counts of a recording, from the truth, the records and the notebook.

    Attributes:
        patient_facts: Patient events in the truth.
        good, with_slips, lost, pending: Rows of patient facts of each class.
        resource_facts: Resource events in the truth.
        resource_good, resource_pending: Rows of resource facts of each class.
        records: Records written, counted by distinct ``event_id``.
        record_rows: Rows with a ``registro``.
        duplicates, corrections: Rows of those classes.
        corrections_drawn: Wrong values whose correction was drawn.
        corrections_pending: Rows ``correccion_pendiente``.
    """

    patient_facts: int
    good: int
    with_slips: int
    lost: int
    pending: int
    resource_facts: int
    resource_good: int
    resource_pending: int
    records: int
    record_rows: int
    duplicates: int
    corrections: int
    corrections_drawn: int
    corrections_pending: int

    def problems(self) -> list[str]:
        """The equalities that do not hold; empty if the account balances."""
        checks = {
            "hechos de pacientes = bien + con_despistes + perdido + pendiente": (
                self.patient_facts,
                self.good + self.with_slips + self.lost + self.pending,
            ),
            "hechos de recursos = bien + pendiente de recursos": (
                self.resource_facts,
                self.resource_good + self.resource_pending,
            ),
            "registros = bien + con_despistes + duplicado + correccion": (
                self.records,
                self.good
                + self.with_slips
                + self.resource_good
                + self.duplicates
                + self.corrections,
            ),
            "registros = filas con registro": (self.records, self.record_rows),
            "correcciones escritas + correccion_pendiente = erróneos con corrección": (
                self.corrections + self.corrections_pending,
                self.corrections_drawn,
            ),
        }
        return [f"{name}: {a} != {b}" for name, (a, b) in checks.items() if a != b]

    def as_dict(self) -> Mapping[str, int]:
        """The counts for ``registro.json``, with Spanish keys."""
        return {
            "hechos_pacientes": self.patient_facts,
            "bien": self.good,
            "con_despistes": self.with_slips,
            "perdido": self.lost,
            "pendiente": self.pending,
            "hechos_recursos": self.resource_facts,
            "recursos_bien": self.resource_good,
            "recursos_pendiente": self.resource_pending,
            "registros": self.records,
            "duplicado": self.duplicates,
            "correccion": self.corrections,
            "correccion_pendiente": self.corrections_pending,
            "erroneos_con_correccion": self.corrections_drawn,
        }


def account(
    events: Sequence[Event],
    records: Sequence[Record],
    rows: Sequence[NotebookRow],
    *,
    corrections_drawn: int,
) -> Account:
    """Count a recording: facts from the truth, records by ``event_id``, classes from the notebook.

    Args:
        events: The true log.
        records: The records written.
        rows: The notebook.
        corrections_drawn: How many wrong values drew a correction.
    """
    patient = {e.event_id: CATALOGS[e.schema_version][e.event_type].patient for e in events}
    fact_kinds = (GOOD, WITH_SLIPS, LOST, PENDING)
    by_patient = Counter(r.kind for r in rows if r.kind in fact_kinds and patient[r.fact_id])
    by_resource = Counter(r.kind for r in rows if r.kind in fact_kinds and not patient[r.fact_id])
    kinds = Counter(r.kind for r in rows)
    return Account(
        patient_facts=sum(patient.values()),
        good=by_patient[GOOD],
        with_slips=by_patient[WITH_SLIPS],
        lost=by_patient[LOST],
        pending=by_patient[PENDING],
        resource_facts=len(patient) - sum(patient.values()),
        resource_good=by_resource[GOOD],
        resource_pending=by_resource[PENDING],
        records=len({r.event_id for r in records}),
        record_rows=sum(r.record_id is not None for r in rows),
        duplicates=kinds[DUPLICATE],
        corrections=kinds[CORRECTION],
        corrections_drawn=corrections_drawn,
        corrections_pending=kinds[CORRECTION_PENDING],
    )
