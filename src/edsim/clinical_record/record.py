"""``record``: the true log turned into what the hospital wrote down, with its slips.

The function is pure: the same log, profile and dice give the same records,
the same notebook and the same counts, byte for byte. It does not import SimPy
nor the engine; only the catalog and ``event_time`` of ``edsim.engine.events``
(docs/specs/hito-7.md, «Especificación: el registro clínico»).

**The dice.** Every true patient event rolls once, before anything is decided:
13 numbers, always the same and in the same order, whether the profile is
clean or the slip happens (fixed consumption). A slip happens when its uniform
is below its rate, so the same roll gives every slip of a realistic profile in
a hostile one too. A ``Dice`` is anything with ``roll() -> Roll``: the tests
force the numbers by hand; task 7.2 connects the stream of the seed.

The 13 numbers of ``Roll``, with the names of the specification:

==================  ==================  =========================================
Field               Specification       Use
==================  ==================  =========================================
``u_forget``        ``u_olvido``        1, forgetting
``u_delay``         ``u_retraso``       2, delay of its system
``z_delay``         ``z_retraso``       2, quantile of the delay
``u_wrong``         ``u_erroneo``       4, wrong value
``u_wrong_field``   ``u_campo_erroneo`` 4, which field
``u_wrong_value``   ``u_valor_erroneo`` 4, which value
``u_empty``         ``u_vacio``         5, empty field
``u_empty_field``   ``u_campo_vacio``   5, which field
``u_correction``    ``u_correccion``    6, late correction
``z_correction``    ``z_correccion``    6, quantile of the correction
``u_duplicate``     ``u_duplicado``     7, duplicate
``z_duplicate``     ``z_duplicado``     7, quantile of the duplicate
``spare``           reserva             Unused, kept for a future slip
==================  ==================  =========================================

The order and the number do not change: changing them changes every slip of
every recording.

**The slips**, in this order, for each true patient event:

1. forgetting: no record, nor delay, duplicate or correction for it;
2. delay: the lognormal of its system, added to ``sim_time``;
3. clock: the fixed offset of its system, added to ``event_time`` and
   ``recorded_time``, never to ``sim_time``;
4. wrong value, only in ``nivel``, ``edad``, ``motivo`` and ``destino``;
5. empty field, among the fields not changed by 4;
6. late correction, only of a wrong value: a ``record_corrected``;
7. duplicate: a copy of the record as written down, with its own number.

The disorder has no rule: it comes from the delay. Resource events do not roll:
they pass as they are, renumbered.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields
from datetime import date, datetime, time, timedelta
from types import MappingProxyType
from typing import Protocol

from edsim.clinical_record.notebook import (
    CORRECTION,
    CORRECTION_PENDING,
    DUPLICATE,
    GOOD,
    LOST,
    PENDING,
    WITH_SLIPS,
    NotebookRow,
    account,
)
from edsim.clinical_record.records import RECORD_CORRECTED, Record
from edsim.engine.events import CATALOGS, TIMEZONE, Event, event_time
from edsim.identifiers import validate_run_id
from edsim.lognormal import lognormal_params

SYSTEMS: tuple[str, ...] = ("admision", "triaje", "his", "lab")
"""The systems with their own delay and clock; ``rrhh`` (resources) has neither."""

WRONG_FIELDS: tuple[str, ...] = ("nivel", "edad", "motivo", "destino")
"""The only payload fields that can get a wrong value."""

ROLL_SIZE = 13
"""Numbers per true patient event."""

_MAX_RECORDS = 10**9 - 1
"""Records that fit the nine digits of ``event_id``, numbered from 1."""


def _check_unit(name: str, value: object) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or not 0 <= value < 1
    ):
        raise ValueError(f"{name} must be a number in [0, 1), got {value!r}")
    return float(value)


def _check_finite(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return float(value)


@dataclass(frozen=True, slots=True)
class Roll:
    """The 13 numbers of one true patient event (see the module docstring).

    The ``u_*`` are uniforms in [0, 1), the ``z_*`` standard normals, finite;
    ``spare`` is any finite number.
    """

    u_forget: float
    u_delay: float
    z_delay: float
    u_wrong: float
    u_wrong_field: float
    u_wrong_value: float
    u_empty: float
    u_empty_field: float
    u_correction: float
    z_correction: float
    u_duplicate: float
    z_duplicate: float
    spare: float

    def __post_init__(self) -> None:
        for f in fields(self):
            value = getattr(self, f.name)
            check = _check_unit if f.name.startswith("u_") else _check_finite
            object.__setattr__(self, f.name, check(f.name, value))

    @classmethod
    def from_numbers(cls, numbers: Sequence[float]) -> "Roll":
        """A roll from its 13 numbers, in the order of the fields."""
        numbers = tuple(numbers)
        if len(numbers) != ROLL_SIZE:
            raise ValueError(f"a roll has {ROLL_SIZE} numbers, got {len(numbers)}")
        return cls(*numbers)


class Dice(Protocol):
    """Where ``record`` gets its numbers: one ``Roll`` per true patient event."""

    def roll(self) -> Roll: ...


@dataclass(frozen=True, slots=True)
class Timed:
    """A rate and a time: ``{ tasa, minutos = [mediana, p90] }`` of the profile.

    Attributes:
        rate: Probability per event, in [0, 1].
        minutes: ``(median, p90)`` of a lognormal, in minutes; 0 < median < p90.
    """

    rate: float
    minutes: tuple[float, float]
    _sigma: float = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        rate = _check_finite("rate", self.rate)
        if not 0 <= rate <= 1:
            raise ValueError(f"rate must be in [0, 1], got {self.rate!r}")
        minutes = tuple(self.minutes)
        if len(minutes) != 2:
            raise ValueError(f"minutes must be [median, p90], got {self.minutes!r}")
        median, p90 = (_check_finite("minutes", m) for m in minutes)
        _, sigma = lognormal_params(median, p90)
        object.__setattr__(self, "rate", rate)
        object.__setattr__(self, "minutes", (median, p90))
        object.__setattr__(self, "_sigma", sigma)

    def quantile(self, z: float) -> float:
        """The lognormal at the standard normal ``z``: ``median · exp(sigma · z)``.

        Written so, and not ``exp(mu + sigma · z)``, so that ``z = 0`` gives the
        median exactly: ``exp(log(7))`` is 6.999999999999999.
        """
        return self.minutes[0] * math.exp(self._sigma * z)


def _check_systems(name: str, mapping: object) -> Mapping[str, object]:
    if not isinstance(mapping, Mapping) or set(mapping) != set(SYSTEMS):
        keys = sorted(mapping) if isinstance(mapping, Mapping) else mapping
        raise ValueError(f"{name} must have exactly the systems {SYSTEMS!r}, got {keys!r}")
    return mapping


@dataclass(frozen=True, slots=True)
class RecordProfile:
    """How much the hospital gets wrong when it writes down: one table of the profiles.

    Built in code until task 7.2 loads ``config/registro_clinico.toml``; the
    attributes are its keys in English.

    Attributes:
        name: Name of the profile, such as ``realista``; part of the derived ``run_id``.
        forget: ``olvido``, rate of forgotten events.
        empty: ``vacio``, rate of an empty field.
        wrong: ``erroneo``, rate of a wrong value.
        duplicate: ``duplicado``, rate and minutes after the original.
        correction: ``correccion``, rate (over the wrong values) and minutes
            after the wrong record.
        delay: ``retraso``, rate and minutes of each system of ``SYSTEMS``.
        clock: ``reloj``, fixed offset in minutes of each system, of any sign.
    """

    name: str
    forget: float
    empty: float
    wrong: float
    duplicate: Timed
    correction: Timed
    delay: Mapping[str, Timed]
    clock: Mapping[str, float]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError(f"name must be a non-empty string, got {self.name!r}")
        for name in ("forget", "empty", "wrong"):
            value = _check_finite(name, getattr(self, name))
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be in [0, 1], got {value!r}")
            object.__setattr__(self, name, value)
        for name in ("duplicate", "correction"):
            if not isinstance(getattr(self, name), Timed):
                raise ValueError(f"{name} must be a Timed, got {getattr(self, name)!r}")
        delay = _check_systems("delay", self.delay)
        for system in SYSTEMS:
            if not isinstance(delay[system], Timed):
                raise ValueError(f"delay of {system} must be a Timed, got {delay[system]!r}")
        clock = _check_systems("clock", self.clock)
        object.__setattr__(self, "delay", MappingProxyType({s: delay[s] for s in SYSTEMS}))
        object.__setattr__(
            self,
            "clock",
            MappingProxyType({s: _check_finite(f"clock of {s}", clock[s]) for s in SYSTEMS}),
        )


@dataclass(frozen=True, slots=True)
class Recording:
    """What ``record`` returns.

    Attributes:
        run_id: The derived run, ``<run_id>_<perfil>_s<semilla>``.
        records: The records, in emission order, numbered from 1.
        notebook: The rows of ``defectos.csv``: those of the records in
            emission order, then those not written, by true event and class.
        info: The data of ``registro.json``: ``run_id``, ``run_id_origen``,
            ``perfil``, ``semilla``, ``horizonte`` and ``cuenta``.
    """

    run_id: str
    records: tuple[Record, ...]
    notebook: tuple[NotebookRow, ...]
    info: Mapping[str, object]


def derived_run_id(run_id: str, profile_name: str, seed: int) -> str:
    """``<run_id>_<perfil>_s<semilla>``, such as ``r2026_realista_s2026``.

    Raises:
        ValueError: If ``seed`` is not an integer >= 0, or the result is not a
            valid ``run_id`` (up to 64 characters).
    """
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError(f"seed must be an integer >= 0, got {seed!r}")
    derived = f"{run_id}_{profile_name}_s{seed}"
    try:
        return validate_run_id(derived)
    except ValueError as e:
        raise ValueError(f"derived run_id {derived!r}: {e}") from None


def _check_horizon(horizon: object) -> float:
    value = _check_finite("horizon", horizon)
    if not value > 0:
        raise ValueError(f"horizon must be positive, got {horizon!r}")
    return value


def _log_start(events: Sequence[Event]) -> date | None:
    """The date of minute 0, from the log; every event must agree with it.

    ``event_time`` is ``start + floor(sim_time · 60000)`` milliseconds, so the
    first event gives the start exactly. ``None`` for an empty log.

    Raises:
        ValueError: If the start is not midnight at +01:00, or an event's
            ``event_time`` is not the one of its ``sim_time``.
    """
    if not events:
        return None
    first = events[0]
    moment = datetime.fromisoformat(first.event_time) - timedelta(
        milliseconds=math.floor(first.sim_time * 60_000)
    )
    if (
        moment.utcoffset() != TIMEZONE.utcoffset(None)
        or moment.timetz().replace(tzinfo=None) != time()
    ):
        raise ValueError(
            f"{first.event_id}: event_time {first.event_time!r} does not start a log at "
            "midnight, +01:00"
        )
    start = moment.date()
    for event in events:
        if event.event_time != event_time(start, event.sim_time):
            raise ValueError(
                f"{event.event_id}: event_time {event.event_time!r} is not the one of "
                f"sim_time {event.sim_time!r} from {start.isoformat()}"
            )
    return start


def _shift(clock: str, offset_ms: int) -> str:
    """An ISO 8601 time moved by a whole number of milliseconds."""
    if offset_ms == 0:
        return clock
    moved = datetime.fromisoformat(clock) + timedelta(milliseconds=offset_ms)
    return moved.isoformat(timespec="milliseconds")


def _pick(u: float, n: int) -> int:
    """``floor(u · n)``, kept below ``n`` even if the product rounds up."""
    return min(math.floor(u * n), n - 1)


def _wrong_value(key: str, value: object, u: float, choices: Sequence[object]) -> object:
    """The wrong value of a field (docs/specs/hito-7.md, despiste 4)."""
    if key == "nivel":
        if value <= 1:
            return 2
        if value >= 5:
            return 4
        return value - 1 if u < 0.5 else value + 1
    if key == "edad":
        flipped = int(str(value)[::-1])
        return value + 1 if flipped == value else flipped
    others = [c for c in choices if c != value]
    return others[_pick(u, len(others))]


def _choices(event: Event, key: str) -> Sequence[object]:
    """The values the catalog allows for ``key``: the ``enum`` of its JSON Schema."""
    check = CATALOGS[event.schema_version][event.event_type].payload[key]
    return check.json_schema().get("enum", ())


def _wrong_cells(wrong: tuple[str, object, object] | None) -> dict[str, object]:
    """``campo_erroneo``, ``valor_verdadero`` and ``valor_registrado`` of a fact's row."""
    if wrong is None:
        return {}
    key, true_value, recorded_value = wrong
    return {"wrong_field": key, "true_value": true_value, "recorded_value": recorded_value}


@dataclass(slots=True)
class _Draft:
    """A record before numbering, with what its notebook row needs."""

    sim_time: float
    position: int
    order: int  # 0 original, 1 duplicate, 2 correction
    fields: dict[str, object]
    row: dict[str, object]
    link: "_Draft | None" = None  # the original of a duplicate, the wrong record of a correction
    offset: int | None = None  # ms of the clock of its system; None keeps the times (resources)
    event_id: str | None = None

    @property
    def key(self) -> tuple[float, int, int]:
        return (self.sim_time, self.position, self.order)


def record(
    events: Sequence[Event],
    profile: RecordProfile,
    seed: int,
    *,
    horizon: float,
    run_id: str,
    dice: Dice,
) -> Recording:
    """What the hospital writes down of a true log, with the slips of a profile.

    Args:
        events: The whole true log of a run, in its order.
        profile: The profile of the slips.
        seed: The seed of the recording; it names the derived run.
        horizon: The horizon in minutes (days × 1440): nothing written at or
            after it is written.
        run_id: The ``run_id`` of the true run.
        dice: One ``Roll`` per true patient event, in the order of the log.

    Returns:
        The derived ``run_id``, the records, the notebook and ``registro.json``.

    Raises:
        ValueError: If the derived ``run_id`` is not valid, ``seed`` or
            ``horizon`` are not valid, an event is not of ``run_id``, or the log
            does not start at midnight; all before rolling any dice.
        RuntimeError: If there are more records than nine digits, or the
            account does not balance (a broken internal rule).
    """
    derived = derived_run_id(run_id, profile.name, seed)
    horizon = _check_horizon(horizon)
    events = tuple(events)
    foreign = sorted({e.run_id for e in events} - {run_id})
    if foreign:
        raise ValueError(f"the log is not of run {run_id!r}: it has events of {foreign!r}")
    start = _log_start(events)
    offsets = {s: round(profile.clock[s] * 60_000) for s in SYSTEMS}

    drafts: list[_Draft] = []
    lost: list[tuple[int, NotebookRow]] = []
    corrections_drawn = 0
    for position, event in enumerate(events):
        spec = CATALOGS[event.schema_version][event.event_type]
        envelope = {
            "event_type": event.event_type,
            "schema_version": event.schema_version,
            "episode_id": event.episode_id,
            "patient_id": event.patient_id,
            "source_system": event.source_system,
        }
        if not spec.patient:
            drafts.append(
                _Draft(
                    event.sim_time,
                    position,
                    0,
                    {
                        **envelope,
                        "sim_time": event.sim_time,
                        "event_time": event.event_time,
                        "recorded_time": event.event_time,
                        "payload": dict(event.payload),
                    },
                    {"fact_id": event.event_id, "kind": GOOD, "delay_min": 0.0, "clock_min": 0.0},
                )
            )
            continue

        roll = dice.roll()
        if not isinstance(roll, Roll):
            raise TypeError(f"dice.roll() must return a Roll, got {roll!r}")
        if roll.u_forget < profile.forget:
            lost.append((position, NotebookRow(None, event.event_id, LOST)))
            continue

        system = event.source_system
        offset = offsets[system]
        clock_min = profile.clock[system]
        delay = profile.delay[system]
        delay_min = delay.quantile(roll.z_delay) if roll.u_delay < delay.rate else 0.0
        sim_time = event.sim_time + delay_min

        payload = dict(event.payload)
        wrong = None
        candidates = [k for k in payload if k in WRONG_FIELDS]
        if candidates and roll.u_wrong < profile.wrong:
            key = candidates[_pick(roll.u_wrong_field, len(candidates))]
            value = _wrong_value(key, payload[key], roll.u_wrong_value, _choices(event, key))
            wrong = (key, payload[key], value)
            payload[key] = value
        empty = None
        candidates = [k for k in payload if wrong is None or k != wrong[0]]
        if candidates and roll.u_empty < profile.empty:
            empty = candidates[_pick(roll.u_empty_field, len(candidates))]
            payload[empty] = None

        # The class comes from what is written, not from what was drawn: a delay that
        # does not move sim_time, or an offset that rounds to 0 ms, is no slip.
        slipped = (
            sim_time != event.sim_time or offset != 0 or wrong is not None or empty is not None
        )
        stamp = _shift(event.event_time, offset)
        original = _Draft(
            sim_time,
            position,
            0,
            {
                **envelope,
                "sim_time": sim_time,
                "event_time": stamp,
                "payload": payload,
            },
            {
                "fact_id": event.event_id,
                "kind": WITH_SLIPS if slipped else GOOD,
                "delay_min": sim_time - event.sim_time,
                "clock_min": clock_min,
                "empty_field": empty,
                **(_wrong_cells(wrong)),
            },
            offset=offset,
        )
        drafts.append(original)

        if wrong is not None and roll.u_correction < profile.correction.rate:
            corrections_drawn += 1
            when = sim_time + profile.correction.quantile(roll.z_correction)
            drafts.append(
                _Draft(
                    when,
                    position,
                    2,
                    {
                        **envelope,
                        "event_type": RECORD_CORRECTED,
                        "sim_time": when,
                        "payload": {"corrige": None, "campos": {wrong[0]: wrong[1]}},
                    },
                    {
                        "fact_id": event.event_id,
                        "kind": CORRECTION,
                        "delay_min": when - event.sim_time,
                        "clock_min": clock_min,
                        "wrong_field": wrong[0],
                        "true_value": wrong[1],
                    },
                    link=original,
                    offset=offset,
                )
            )

        if roll.u_duplicate < profile.duplicate.rate:
            when = sim_time + profile.duplicate.quantile(roll.z_duplicate)
            drafts.append(
                _Draft(
                    when,
                    position,
                    1,
                    {
                        **envelope,
                        "sim_time": when,
                        "event_time": stamp,
                        "payload": dict(payload),
                    },
                    {
                        "fact_id": event.event_id,
                        "kind": DUPLICATE,
                        "delay_min": when - event.sim_time,
                        "clock_min": clock_min,
                    },
                    link=original,
                    offset=offset,
                )
            )

    drafts.sort(key=lambda d: d.key)
    written = [d for d in drafts if d.sim_time < horizon]
    if len(written) > _MAX_RECORDS:
        raise RuntimeError(f"no event_id left: a recording has at most {_MAX_RECORDS} records")
    for number, draft in enumerate(written, start=1):
        draft.event_id = f"{derived}-{number:09d}"

    records = []
    rows = []
    for draft in written:
        values = draft.fields
        if draft.offset is not None:
            # Only now, for what is written: a draft past the horizon may lie beyond any date.
            clock = _shift(event_time(start, draft.sim_time), draft.offset)
            values = {**values, "recorded_time": clock}
            if draft.order == 2:
                values["event_time"] = clock
        row = dict(draft.row)
        if draft.order == 2:
            values = {**values, "payload": {**values["payload"], "corrige": draft.link.event_id}}
            row["corrects"] = draft.link.event_id
        elif draft.order == 1:
            row["duplicate_of"] = draft.link.event_id
        records.append(Record(event_id=draft.event_id, run_id=derived, ingest_time=None, **values))
        rows.append(NotebookRow(record_id=draft.event_id, **row))

    unwritten = [(d.position, d.order, d) for d in drafts if d.sim_time >= horizon]
    unwritten += [(pos, 0, row) for pos, row in lost]
    for _, _, item in sorted(unwritten, key=lambda t: t[:2]):
        if isinstance(item, NotebookRow):
            rows.append(item)
        elif item.order == 0:
            rows.append(NotebookRow(None, item.row["fact_id"], PENDING))
        elif item.order == 2:
            rows.append(
                NotebookRow(
                    None,
                    item.row["fact_id"],
                    CORRECTION_PENDING,
                    wrong_field=item.row["wrong_field"],
                    true_value=item.row["true_value"],
                    corrects=item.link.event_id,
                )
            )
        # A duplicate at or after the horizon is neither a fact nor a correction: no row.

    counts = account(events, records, rows, corrections_drawn=corrections_drawn)
    if problems := counts.problems():
        raise RuntimeError("the account does not balance: " + "; ".join(problems))
    info = {
        "run_id": derived,
        "run_id_origen": run_id,
        "perfil": profile.name,
        "semilla": seed,
        "horizonte": horizon,
        "cuenta": counts.as_dict(),
    }
    return Recording(derived, tuple(records), tuple(rows), MappingProxyType(info))
