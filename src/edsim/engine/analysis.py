"""State and metrics derived from the event log (event sourcing).

The engine writes facts; everything here folds them back into state and
metrics, with pure functions that take the events in file order
(docs/specs/hito-3.md, "Estado y métricas derivados del log"). The CLI and the
notebook only call them (decision 16).

- ``episode_table``: one row per episode, with the instants of its milestones
  and its waits.
- ``step_curves``: census, queues, busy staff and boxes, and the staff in
  force, as step functions of time that change only at events.

The waits of an episode follow the same rules as the invariant "nobody jumps
the queue" (``check_nobody_jumps_the_queue``):

- waiting for a box: from ``triage_completed`` and from every
  ``patient_displaced`` to the next ``box_assigned``;
- waiting for a doctor: holding a box with an assessment to do, from
  ``box_assigned`` or ``test_resulted`` to ``assessment_started`` or
  ``patient_displaced``.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

from edsim.engine.events import Event
from edsim.queueing.analysis import sample_step, step_time_average

# --- Episode table ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EpisodeRecord:
    """What happened to one episode, from its events.

    ``None`` means it did not happen before the end of the log: nothing is made
    up for the episodes the horizon cuts.

    Attributes:
        episode_id: Such as ``EP-000137``.
        arrival: ``sim_time`` of ``patient_arrived``.
        triage_start: Start of the triage.
        triage_end: End of the triage (``triage_completed``).
        level: Triage level, 1 to 5.
        first_box: First ``box_assigned``; later ones, after a displacement,
            do not change it.
        first_assessment: First ``assessment_started``.
        decision: ``disposition_decided``.
        departure: ``patient_departed``.
        destination: ``alta`` or ``ingreso``.
        displacements: Times the episode was displaced from a box.
        triage_wait: From the arrival to the start of the triage.
        box_wait: Total time waiting for a box: after the triage and after
            each displacement. Final only at the departure, ``None`` before.
        doctor_wait: Total time holding a box and waiting for a doctor, for
            the first assessment, the reassessment and the resumptions after
            a displacement. Final only at the departure, ``None`` before.
        initial_doctor_wait: Time holding a box and waiting for a doctor
            before the first ``assessment_started``, from the first
            ``box_assigned`` on.
        door_to_doctor: From the arrival to the first ``assessment_started``,
            the KPI of the Manchester maximum times.
    """

    episode_id: str
    arrival: float
    triage_start: float | None
    triage_end: float | None
    level: int | None
    first_box: float | None
    first_assessment: float | None
    decision: float | None
    departure: float | None
    destination: str | None
    displacements: int
    triage_wait: float | None
    box_wait: float | None
    doctor_wait: float | None
    initial_doctor_wait: float | None
    door_to_doctor: float | None

    @property
    def stay(self) -> float | None:
        """From the arrival to the departure; ``None`` if still inside."""
        return None if self.departure is None else self.departure - self.arrival


@dataclass(slots=True)
class _Episode:
    """What ``episode_table`` knows of one episode while reading the log."""

    episode_id: str
    arrival: float
    triage_start: float | None = None
    triage_end: float | None = None
    level: int | None = None
    first_box: float | None = None
    first_assessment: float | None = None
    decision: float | None = None
    departure: float | None = None
    destination: str | None = None
    displacements: int = 0
    box_wait: float = 0.0
    doctor_wait: float = 0.0
    initial_doctor_wait: float | None = None
    waiting_box_since: float | None = None
    waiting_doctor_since: float | None = None
    has_box: bool = False
    to_assess: bool = False  # an assessment is next once in a box

    def close_doctor_wait(self, now: float) -> None:
        if self.waiting_doctor_since is not None:
            self.doctor_wait += now - self.waiting_doctor_since
            self.waiting_doctor_since = None

    def record(self) -> EpisodeRecord:
        departed = self.departure is not None
        return EpisodeRecord(
            episode_id=self.episode_id,
            arrival=self.arrival,
            triage_start=self.triage_start,
            triage_end=self.triage_end,
            level=self.level,
            first_box=self.first_box,
            first_assessment=self.first_assessment,
            decision=self.decision,
            departure=self.departure,
            destination=self.destination,
            displacements=self.displacements,
            triage_wait=None if self.triage_start is None else self.triage_start - self.arrival,
            box_wait=self.box_wait if departed else None,
            doctor_wait=self.doctor_wait if departed else None,
            initial_doctor_wait=self.initial_doctor_wait,
            door_to_doctor=(
                None if self.first_assessment is None else self.first_assessment - self.arrival
            ),
        )


def episode_table(events: Sequence[Event]) -> tuple[EpisodeRecord, ...]:
    """One record per episode of the log, in arrival order.

    Args:
        events: The events in file order, such as ``MemorySink.events``.

    Returns:
        The records, in the order of the ``patient_arrived`` events.
    """
    episodes: dict[str, _Episode] = {}
    for e in events:
        if e.episode_id is None:
            continue
        now = e.sim_time
        if e.event_type == "patient_arrived":
            episodes[e.episode_id] = _Episode(e.episode_id, now)
            continue
        ep = episodes[e.episode_id]
        match e.event_type:
            case "triage_started":
                ep.triage_start = now
            case "triage_completed":
                ep.triage_end = now
                ep.level = e.payload["nivel"]
                ep.waiting_box_since = now
                ep.to_assess = True
            case "box_assigned":
                if ep.first_box is None:
                    ep.first_box = now
                if ep.waiting_box_since is not None:
                    ep.box_wait += now - ep.waiting_box_since
                    ep.waiting_box_since = None
                ep.has_box = True
                if ep.to_assess:
                    ep.waiting_doctor_since = now
            case "assessment_started":
                ep.close_doctor_wait(now)
                if ep.first_assessment is None:
                    ep.first_assessment = now
                    ep.initial_doctor_wait = ep.doctor_wait
                ep.to_assess = False
            case "assessment_ended" if e.payload["interrumpida"]:
                ep.to_assess = True  # resumed when back in a box
            case "test_resulted":
                ep.to_assess = True
                if ep.has_box:
                    ep.waiting_doctor_since = now
            case "patient_displaced":
                ep.close_doctor_wait(now)
                ep.has_box = False
                ep.displacements += 1
                ep.waiting_box_since = now
            case "disposition_decided":
                ep.decision = now
            case "patient_departed":
                ep.departure = now
                ep.destination = e.payload["destino"]
                ep.has_box = False
    return tuple(ep.record() for ep in episodes.values())


# --- Step curves ----------------------------------------------------------------------

# How each event changes each curve. A patient waits for a box after the triage
# and again after a displacement; the staff curves move by nueva - anterior.
_DELTAS: dict[str, dict[str, int]] = {
    "patient_arrived": {"census": 1, "waiting_triage": 1},
    "triage_started": {"waiting_triage": -1, "nurses_busy": 1},
    "triage_completed": {"nurses_busy": -1, "waiting_box": 1},
    "box_assigned": {"waiting_box": -1, "boxes_busy": 1},
    "patient_displaced": {"boxes_busy": -1, "waiting_box": 1},
    "assessment_started": {"doctors_busy": 1},
    "assessment_ended": {"doctors_busy": -1},
    "patient_departed": {"census": -1, "boxes_busy": -1},
}

_STAFF_CURVE = {"enfermeria_triaje": "nurses_staff", "medicos": "doctors_staff"}

CURVES = (
    "census",
    "waiting_triage",
    "waiting_box",
    "nurses_busy",
    "doctors_busy",
    "boxes_busy",
    "nurses_staff",
    "doctors_staff",
)
"""Names of the step curves, as keys of ``StepCurves.values``."""


@dataclass(frozen=True)
class StepCurves:
    """State of the center as step functions of time, derived from the log.

    Value ``i`` of each curve holds from ``times[i]`` until ``times[i + 1]``
    (the last one until ``horizon``), after every event of instant
    ``times[i]``. ``times`` is strictly increasing and starts at 0.

    Attributes:
        times: Instants at which some curve may change, from 0.
        values: One integer array per name of ``CURVES``.
        horizon: End of the log.
    """

    times: np.ndarray
    values: MappingProxyType
    horizon: float

    def __getitem__(self, name: str) -> np.ndarray:
        return self.values[name]

    @property
    def edges(self) -> np.ndarray:
        """Step edges, ``times`` followed by ``horizon``, as ``ax.stairs`` expects."""
        return np.append(self.times, self.horizon)

    def value(self, name: str, t: float) -> int:
        """Value of a curve at instant ``t``, after the events of ``t``."""
        return int(sample_step(self.times, self.values[name], [t])[0])

    def area(self, name: str, start: float, end: float) -> float:
        """Area of a curve over ``[start, end]``, within ``[0, horizon]``.

        The same sum as ``queueing.analysis.step_time_average``, without
        dividing by the length: the identity of utilization compares areas
        with a relative tolerance of 1e-9.
        """
        self._check_interval(start, end)
        t = self.times
        next_t = np.append(t[1:], self.horizon)
        covered = np.clip(np.minimum(next_t, end) - np.maximum(t, start), 0.0, None)
        return float(np.sum(covered * self.values[name]))

    def mean(self, name: str, start: float, end: float) -> float:
        """Time average of a curve over ``[start, end]``, within ``[0, horizon]``."""
        self._check_interval(start, end)
        return step_time_average(self.times, self.values[name], start, end)

    def _check_interval(self, start: float, end: float) -> None:
        if not 0 <= start < end <= self.horizon:
            raise ValueError(
                f"need 0 <= start < end <= horizon ({self.horizon}), got {start=} and {end=}"
            )


def step_curves(events: Sequence[Event], horizon: float) -> StepCurves:
    """Build the step curves of a log.

    The changes of each instant are added up and then accumulated in time
    order (as ``queueing.analysis.occupancy``), so the curves show the state
    after every event of an instant, not the passing states inside it.

    Args:
        events: The events in file order.
        horizon: End of the log, such as ``days * 1440``.

    Returns:
        The curves.

    Raises:
        ValueError: If an event happens after ``horizon``.
    """
    index = {name: i for i, name in enumerate(CURVES)}
    times = [0.0]  # the instants, with 0 so that every curve starts there
    changes: list[tuple[int, int, int]] = []  # (position in times, curve, delta)
    for e in events:
        if e.event_type == "staffing_changed":
            change = {
                _STAFF_CURVE[e.payload["recurso"]]: e.payload["nueva"] - e.payload["anterior"]
            }
        else:
            change = _DELTAS.get(e.event_type)
            if change is None:
                continue
        times.append(e.sim_time)
        changes.extend((len(times) - 1, index[name], delta) for name, delta in change.items())

    unique, group = np.unique(np.array(times), return_inverse=True)
    if unique[-1] > horizon:
        raise ValueError(f"an event happens at {unique[-1]}, after the horizon {horizon}")
    per_instant = np.zeros((unique.size, len(CURVES)), dtype=np.int64)
    if changes:
        position, curve, delta = np.array(changes).T
        np.add.at(per_instant, (group[position], curve), delta)
    cumulative = np.cumsum(per_instant, axis=0)
    values = MappingProxyType({name: cumulative[:, i] for name, i in index.items()})
    return StepCurves(times=unique, values=values, horizon=float(horizon))
