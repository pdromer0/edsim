"""``compare``: what happened to each true fact, and how much the slips bias the indicators.

One comparison, in Python, for files and for bronze alike (docs/specs/hito-7.md, decisions 95
and 96): it takes the truth, the records and the notebook as lists and does not care where they
come from. The CLI, the notebook and the tests use it.

**The reconciliation** counts every ``clase`` of the notebook and checks the account before
giving any number: if it does not balance, ``ReconciliationError`` says every equality that
fails. It also gives the delay of each system (``recorded_time - event_time`` of the records
written for their own fact, in minutes, with its median and 90th percentile) and the
``con_despistes`` rows broken down by kind of slip, because the clock offset alone makes most of
them (a row can have several slips).

**The naive indicators** are what an analyst in a hurry would compute: the first record of each
type of an episode, empty values ignored, corrections never applied (``record_corrected`` is not
read at all). They do not reuse the metrics of ``edsim.runs``, which expect clean data. The same
function runs on the truth and on the records; the difference between the two is the bias.
Records come in emission order (``sim_time``, then ``event_id``), and "the first" is the first
one given: nothing is reordered.

The origin of the clock (minute 0) is read from the truth: the ``event_time`` of an event minus
``floor(sim_time * 60000)`` milliseconds, which is exactly how ``edsim.engine.events.event_time``
writes it.
"""

import math
from bisect import bisect_right
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import median
from types import MappingProxyType
from typing import Protocol

from edsim.clinical_record.notebook import (
    CORRECTION,
    DUPLICATE,
    GOOD,
    KINDS,
    LOST,
    PENDING,
    WITH_SLIPS,
    NotebookRow,
)
from edsim.clinical_record.record import SYSTEMS
from edsim.clinical_record.records import Record
from edsim.engine.events import Event

LEVELS: tuple[int, ...] = (1, 2, 3, 4, 5)
"""The triage levels of the share by level."""

FACT_KINDS: tuple[str, ...] = (GOOD, WITH_SLIPS, LOST, PENDING)
"""The classes of the rows that stand for a true fact, once each."""

MAX_HOURS = 24 * 366 * 10
"""The most hours of the window: a horizon of ten years. A bigger one is a mistake, not a run."""

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MS = timedelta(milliseconds=1)
_MS_PER_MINUTE = 60_000
_MS_PER_HOUR = 3_600_000
_DEPARTURES = ("patient_departed", "patient_left_wbs")


class Logged(Protocol):
    """What the indicators read of an ``Event`` or of a ``Record``: both have it."""

    @property
    def event_id(self) -> str: ...
    @property
    def event_type(self) -> str: ...
    @property
    def episode_id(self) -> str | None: ...
    @property
    def event_time(self) -> str: ...
    @property
    def payload(self) -> Mapping[str, object]: ...


class ReconciliationError(ValueError):
    """The account of the recording does not balance: the sources do not match.

    Attributes:
        problems: Every equality that fails, in Spanish, as ``Account.problems`` writes them.
    """

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("la cuenta no cuadra: " + "; ".join(self.problems))


@dataclass(frozen=True, slots=True)
class DelayStats:
    """The delay of one system, in minutes.

    Attributes:
        count: Records of the system written for their own fact.
        median: Their median delay; ``None`` if there are none.
        p90: Their 90th percentile (linear interpolation); ``None`` if there are none.
    """

    count: int
    median: float | None
    p90: float | None


@dataclass(frozen=True, slots=True)
class SlipCounts:
    """The ``con_despistes`` rows by kind of slip (a row can have several).

    Attributes:
        rows: Rows of class ``con_despistes``.
        clock: With a clock offset (``desfase_min`` other than 0).
        delay: With a delay (``retraso_min`` above 0).
        wrong: With a wrong value.
        empty: With an empty field.
        only_clock: With a clock offset and nothing else: the part of the class that is the clock.
    """

    rows: int
    clock: int
    delay: int
    wrong: int
    empty: int
    only_clock: int


@dataclass(frozen=True, slots=True)
class Reconciliation:
    """What happened to each fact and to each record; the account balanced.

    Attributes:
        facts: Events of the truth; the sum of the rows of a fact (``bien``, ``con_despistes``,
            ``perdido`` and ``pendiente``).
        records: Records written; the sum of ``bien``, ``con_despistes``, ``duplicado`` and
            ``correccion``.
        by_kind: Rows of each class of ``KINDS``, in that order, zeros included.
        slips: The ``con_despistes`` rows broken down.
        delay: The delay of each system of ``SYSTEMS``, in that order.
    """

    facts: int
    records: int
    by_kind: Mapping[str, int]
    slips: SlipCounts
    delay: Mapping[str, DelayStats]


@dataclass(frozen=True, slots=True)
class Indicators:
    """The naive indicators of a list of events or records.

    Attributes:
        time_to_triage: Median minutes from the first arrival to the first triage of each
            episode with both; ``None`` if there is none.
        time_to_doctor: The same, to the first initial assessment.
        in_department: Patients in the department at each hour on the dot of the window, by
            hour since minute 0 (``20`` is 20:00 of the first day).
        mean_in_department: The mean of ``in_department``; ``None`` if the window has no hour.
        arrivals: ``patient_arrived`` records.
        level_shares: Percentage of each level of ``LEVELS`` among the ``triage_completed``
            with a readable level; ``None`` for each if there is none.
    """

    time_to_triage: float | None
    time_to_doctor: float | None
    in_department: Mapping[int, int]
    mean_in_department: float | None
    arrivals: int
    level_shares: Mapping[int, float | None]


@dataclass(frozen=True, slots=True)
class IndicatorRow:
    """One row of the table «indicador, verdad, registrado, diferencia».

    Attributes:
        key: ``time_to_triage``, ``time_to_doctor``, ``mean_in_department``, ``arrivals`` or
            ``level_<n>``.
        truth: The value on the truth; ``None`` if it cannot be computed.
        recorded: The value on the records.
    """

    key: str
    truth: float | None
    recorded: float | None

    @property
    def difference(self) -> float | None:
        """Recorded minus truth; ``None`` if either is missing."""
        if self.truth is None or self.recorded is None:
            return None
        return self.recorded - self.truth


@dataclass(frozen=True, slots=True)
class Comparison:
    """The reconciliation and the indicators on the truth and on the records."""

    reconciliation: Reconciliation
    truth: Indicators
    recorded: Indicators

    def rows(self) -> tuple[IndicatorRow, ...]:
        """The table of indicators, one row each; the level shares, one row per level."""
        t, r = self.truth, self.recorded
        rows = [
            IndicatorRow("time_to_triage", t.time_to_triage, r.time_to_triage),
            IndicatorRow("time_to_doctor", t.time_to_doctor, r.time_to_doctor),
            IndicatorRow("mean_in_department", t.mean_in_department, r.mean_in_department),
            IndicatorRow("arrivals", t.arrivals, r.arrivals),
        ]
        rows += [
            IndicatorRow(f"level_{level}", t.level_shares[level], r.level_shares[level])
            for level in LEVELS
        ]
        return tuple(rows)


# --- Times and statistics ----------------------------------------------------------------------


def _ms(item: Logged, name: str) -> int:
    """``item.<name>`` (an ISO 8601 time with a zone) as integer milliseconds since 1970.

    Integer arithmetic: no float is added to a ``timedelta``.
    """
    text = getattr(item, name)
    try:
        when = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        raise ValueError(f"{item.event_id}: {name} is not an ISO 8601 time: {text!r}") from None
    if when.tzinfo is None:
        raise ValueError(f"{item.event_id}: {name} has no time zone: {text!r}")
    return (when - _EPOCH) // _MS


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    """The quantile ``q`` by linear interpolation between the closest ranks (numpy's default)."""
    position = (len(sorted_values) - 1) * q
    low = math.floor(position)
    high = min(low + 1, len(sorted_values) - 1)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (position - low)


def _median_minutes(milliseconds: Sequence[int]) -> float | None:
    return median(milliseconds) / _MS_PER_MINUTE if milliseconds else None


def _hours(horizon: object, warmup: object) -> range:
    """The hours on the dot of the window: ``k`` with ``warmup <= 60 k < horizon``."""
    values = []
    for name, value in (("horizon", horizon), ("warmup", warmup)):
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"{name} must be a number of minutes, got {value!r}")
        try:
            number = float(value)
        except OverflowError:  # an integer of 10**400 has no float
            raise ValueError(f"{name} must be a finite number, got {value!r}") from None
        if not math.isfinite(number):
            raise ValueError(f"{name} must be a finite number, got {value!r}")
        values.append(number)
    horizon_min, warmup_min = values
    if not 0 <= warmup_min < horizon_min:
        raise ValueError(f"need 0 <= warmup < horizon, got warmup={warmup!r} horizon={horizon!r}")
    hours = range(math.ceil(warmup_min / 60), math.ceil(horizon_min / 60))
    if len(hours) > MAX_HOURS:
        raise ValueError(f"the window has {len(hours)} hours, more than the {MAX_HOURS} allowed")
    return hours


def _origin(truth: Sequence[Event]) -> int:
    """Minute 0 of the run in milliseconds since 1970, from the first event of the truth."""
    if not truth:
        return 0  # no event, no episode: no hour has anybody, whatever the origin
    first = truth[0]
    return _ms(first, "event_time") - math.floor(first.sim_time * _MS_PER_MINUTE)


# --- The naive indicators ----------------------------------------------------------------------


def _naive_indicators(items: Iterable[Logged], origin: int, hours: range) -> Indicators:
    """The five indicators of a list, the first record of each type of each episode."""
    arrival: dict[str, int] = {}
    triage: dict[str, int] = {}
    doctor: dict[str, int] = {}
    departure: dict[str, int] = {}
    arrivals = 0
    levels: Counter[int] = Counter()
    for item in items:
        kind = item.event_type
        episode = item.episode_id
        if kind == "patient_arrived":
            arrivals += 1
            if episode is not None and episode not in arrival:
                arrival[episode] = _ms(item, "event_time")
        elif kind == "triage_completed":
            level = item.payload.get("nivel")
            if isinstance(level, int) and not isinstance(level, bool) and level in LEVELS:
                levels[level] += 1
            if episode is not None and episode not in triage:
                triage[episode] = _ms(item, "event_time")
        elif kind == "assessment_started":
            if item.payload.get("tipo") == "inicial" and episode is not None:
                if episode not in doctor:
                    doctor[episode] = _ms(item, "event_time")
        elif kind in _DEPARTURES and episode is not None and episode not in departure:
            departure[episode] = _ms(item, "event_time")

    starts = sorted(arrival.values())
    # An episode that leaves before it arrives (by the clocks) is never in: it ends where it starts.
    ends = sorted(max(departure[e], a) for e, a in arrival.items() if e in departure)
    census = {}
    for k in hours:
        mark = origin + k * _MS_PER_HOUR
        census[k] = bisect_right(starts, mark) - bisect_right(ends, mark)

    total = sum(levels.values())
    return Indicators(
        time_to_triage=_median_minutes([triage[e] - a for e, a in arrival.items() if e in triage]),
        time_to_doctor=_median_minutes([doctor[e] - a for e, a in arrival.items() if e in doctor]),
        in_department=MappingProxyType(census),
        mean_in_department=sum(census.values()) / len(census) if census else None,
        arrivals=arrivals,
        level_shares=MappingProxyType(
            {level: 100 * levels[level] / total if total else None for level in LEVELS}
        ),
    )


# --- The reconciliation ------------------------------------------------------------------------


def _examples(ids: Iterable[str]) -> str:
    ids = sorted(ids)
    shown = ", ".join(ids[:3])
    return f"{len(ids)} ({shown}{', …' if len(ids) > 3 else ''})"


def _check_account(
    truth: Sequence[Event],
    records: Sequence[Record],
    notebook: Sequence[NotebookRow],
    by_kind: Mapping[str, int],
) -> list[str]:
    """Every equality of the account that fails, as sentences in Spanish."""
    problems = []
    truth_ids = {e.event_id for e in truth}
    if len(truth_ids) != len(truth):
        problems.append("la verdad repite algún event_id")
    record_counts = Counter(r.event_id for r in records)
    repeated = [i for i, n in record_counts.items() if n > 1]
    if repeated:
        problems.append(f"registros con el mismo event_id: {_examples(repeated)}")

    written = Counter(r.record_id for r in notebook if r.record_id is not None)
    repeated = [i for i, n in written.items() if n > 1]
    if repeated:
        problems.append(f"filas de la libreta con el mismo registro: {_examples(repeated)}")
    if missing := set(record_counts) - set(written):
        problems.append(f"registros que la libreta no tiene: {_examples(missing)}")
    if missing := set(written) - set(record_counts):
        problems.append(f"filas de la libreta sin su registro: {_examples(missing)}")

    if unknown := {r.fact_id for r in notebook} - truth_ids:
        problems.append(f"hechos de la libreta que no están en la verdad: {_examples(unknown)}")
    facts = Counter(r.fact_id for r in notebook if r.kind in FACT_KINDS)
    if missing := truth_ids - set(facts):
        problems.append(f"hechos de la verdad sin fila en la libreta: {_examples(missing)}")
    repeated = [i for i, n in facts.items() if n > 1]
    if repeated:
        problems.append(f"hechos con más de una fila de hecho: {_examples(repeated)}")

    fact_rows = sum(by_kind[kind] for kind in FACT_KINDS)
    if fact_rows != len(truth):
        problems.append(
            f"hechos de la verdad = bien + con_despistes + perdido + pendiente: "
            f"{len(truth)} != {fact_rows}"
        )
    written_kinds = (GOOD, WITH_SLIPS, DUPLICATE, CORRECTION)
    expected = sum(by_kind[kind] for kind in written_kinds)
    if expected != len(records):
        problems.append(
            "registros = bien + con_despistes + duplicado + correccion: "
            f"{len(records)} != {expected}"
        )
    return problems


def _delays(records: Sequence[Record], notebook: Sequence[NotebookRow]) -> Mapping[str, DelayStats]:
    kinds = {r.record_id: r.kind for r in notebook if r.record_id is not None}
    minutes: dict[str, list[float]] = {system: [] for system in SYSTEMS}
    for record in records:
        if kinds[record.event_id] in (GOOD, WITH_SLIPS) and record.source_system in minutes:
            delay = _ms(record, "recorded_time") - _ms(record, "event_time")
            minutes[record.source_system].append(delay / _MS_PER_MINUTE)
    stats = {}
    for system in SYSTEMS:
        values = sorted(minutes[system])
        stats[system] = DelayStats(
            len(values),
            median(values) if values else None,
            _quantile(values, 0.9) if values else None,
        )
    return MappingProxyType(stats)


def _slips(notebook: Sequence[NotebookRow]) -> SlipCounts:
    rows = [r for r in notebook if r.kind == WITH_SLIPS]
    clock = [(r.clock_min or 0) != 0 for r in rows]
    delay = [(r.delay_min or 0) > 0 for r in rows]
    wrong = [r.wrong_field is not None for r in rows]
    empty = [r.empty_field is not None for r in rows]
    only_clock = [
        c and not (d or w or e) for c, d, w, e in zip(clock, delay, wrong, empty, strict=True)
    ]
    return SlipCounts(
        rows=len(rows),
        clock=sum(clock),
        delay=sum(delay),
        wrong=sum(wrong),
        empty=sum(empty),
        only_clock=sum(only_clock),
    )


def _reconcile(
    truth: Sequence[Event], records: Sequence[Record], notebook: Sequence[NotebookRow]
) -> Reconciliation:
    counts = Counter(r.kind for r in notebook)
    by_kind = {kind: counts[kind] for kind in KINDS}
    problems = _check_account(truth, records, notebook, by_kind)
    if problems:
        raise ReconciliationError(problems)
    return Reconciliation(
        facts=sum(by_kind[kind] for kind in FACT_KINDS),
        records=len(records),
        by_kind=MappingProxyType(by_kind),
        slips=_slips(notebook),
        delay=_delays(records, notebook),
    )


def compare(
    truth: Sequence[Event],
    records: Sequence[Record],
    notebook: Sequence[NotebookRow],
    *,
    horizon: float,
    warmup: float = 0.0,
) -> Comparison:
    """Reconcile the records with the truth and compare the naive indicators on both.

    Args:
        truth: The true log of the run, in order.
        records: What was written down, in emission order (from the files of the recording or
            from bronze: it does not matter).
        notebook: The rows of ``defectos.csv``.
        horizon: The horizon of the run in minutes.
        warmup: The warm-up in minutes; the hours on the dot of the window start at it.

    Returns:
        The reconciliation, with the account checked, and the indicators on each side.

    Raises:
        ReconciliationError: If the account does not balance (a ``ValueError``, but of the data).
        ValueError: If ``horizon`` or ``warmup`` is not a finite number with
            ``0 <= warmup < horizon``, the window has more than ``MAX_HOURS`` hours, or a time
            that the indicators read is not an ISO 8601 time with a zone.
    """
    hours = _hours(horizon, warmup)
    reconciliation = _reconcile(truth, records, notebook)
    origin = _origin(truth)
    return Comparison(
        reconciliation=reconciliation,
        truth=_naive_indicators(truth, origin, hours),
        recorded=_naive_indicators(records, origin, hours),
    )
