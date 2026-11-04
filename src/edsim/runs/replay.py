"""Hourly immutable checkpoints and bounded validated reads of a persisted log."""

import math
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType

from edsim.engine.analysis import CURVES
from edsim.engine.events import Event, from_json
from edsim.runs._location import LocationState
from edsim.runs.episodes import EpisodeState
from edsim.runs.results import RunReadError, RunResults, read_run_header
from edsim.runs.store import RunStore


@dataclass(frozen=True, slots=True)
class ReplayPatient:
    """An observed patient; arrival and all instants use simulation minutes."""

    episode_id: str
    patient_id: str
    arrival: float
    level: int | None
    state: EpisodeState
    box: int | None
    tests_pending: bool = False


@dataclass(frozen=True, slots=True)
class ReplayDeparture:
    """One departure in the trailing hour, with the patient's observed level."""

    episode_id: str
    patient_id: str
    arrival: float
    level: int | None
    time: float
    destination: str


@dataclass(frozen=True, slots=True)
class ReplayDisplacement:
    """Who lost a box, when, and to which episode."""

    episode_id: str
    time: float
    box: int
    displaced_by: str


@dataclass(frozen=True, slots=True)
class ReplayState:
    """State after all events <= time; recent means (time - 60, time]."""

    time: float
    patients: tuple[ReplayPatient, ...]
    staff: Mapping[str, int]
    departures: tuple[ReplayDeparture, ...]
    displacements: tuple[ReplayDisplacement, ...]
    last_events: tuple[Event, ...]
    departures_by_destination: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class ReplayCounts:
    """Curve values, never counts inferred from the replay's patient list."""

    census: int
    waiting_triage: int
    waiting_box: int
    nurses_busy: int
    doctors_busy: int
    boxes_busy: int
    nurses_staff: int
    doctors_staff: int
    boxes: int


@dataclass(frozen=True, slots=True)
class _Patient:
    episode_id: str
    patient_id: str
    arrival: float
    level: int | None = None
    location: LocationState = LocationState()

    def view(self) -> ReplayPatient:
        return ReplayPatient(
            self.episode_id,
            self.patient_id,
            self.arrival,
            self.level,
            self.location.location(),
            self.location.box,
            self.location.tests_pending,
        )


@dataclass(frozen=True, slots=True)
class _Checkpoint:
    time: float
    patients: tuple[_Patient, ...]
    staff: tuple[tuple[str, int], ...]
    departures: tuple[ReplayDeparture, ...]
    displacements: tuple[ReplayDisplacement, ...]
    last_events: tuple[Event, ...]
    offset: int
    line: int


@dataclass(frozen=True, slots=True)
class ReplayIndex:
    """Data only: pre-boundary snapshots, byte offsets and physical line numbers.

    A checkpoint at h contains only events < h. Its offset points to the first
    event >= h or EOF. The terminal checkpoint also accepts events at horizon.
    All nested records are immutable; reads never change a cached index.
    """

    run_id: str
    horizon: float
    file_size: int
    line_count: int
    _checkpoints: tuple[_Checkpoint, ...]


class _Accumulator:
    def __init__(self, checkpoint: _Checkpoint):
        self.patients = {p.episode_id: p for p in checkpoint.patients}
        self.staff = dict(checkpoint.staff)
        self.departures = deque(checkpoint.departures)
        self.displacements = deque(checkpoint.displacements)
        self.last_events = deque(checkpoint.last_events, maxlen=15)

    def apply(self, event: Event) -> None:
        self.last_events.append(event)
        episode = event.episode_id
        kind = event.event_type
        if kind == "staffing_changed":
            self.staff[event.payload["recurso"]] = event.payload["nueva"]
            return
        if kind == "patient_arrived":
            if episode in self.patients:
                raise ValueError("duplicate active arrival")
            self.patients[episode] = _Patient(episode, event.patient_id, event.sim_time)
            return
        if episode not in self.patients:
            raise ValueError(f"event of inactive episode {episode!r}")
        patient = self.patients[episode]
        patient = replace(patient, location=patient.location.apply(event))
        if kind == "triage_completed":
            patient = replace(patient, level=event.payload["nivel"])
        if kind == "patient_displaced":
            self.displacements.append(
                ReplayDisplacement(
                    episode, event.sim_time, event.payload["box"], event.payload["desalojado_por"]
                )
            )
        if kind == "patient_departed":
            self.departures.append(
                ReplayDeparture(
                    episode,
                    patient.patient_id,
                    patient.arrival,
                    patient.level,
                    event.sim_time,
                    event.payload["destino"],
                )
            )
            del self.patients[episode]
        else:
            self.patients[episode] = patient

    def snapshot(self, time: float, offset: int = 0, line: int = 1) -> _Checkpoint:
        while self.departures and self.departures[0].time <= time - 60:
            self.departures.popleft()
        while self.displacements and self.displacements[0].time <= time - 60:
            self.displacements.popleft()
        return _Checkpoint(
            time,
            tuple(self.patients.values()),
            tuple(self.staff.items()),
            tuple(self.departures),
            tuple(self.displacements),
            tuple(self.last_events),
            offset,
            line,
        )


def _empty() -> _Checkpoint:
    return _Checkpoint(0.0, (), (("enfermeria_triaje", 0), ("medicos", 0)), (), (), (), 0, 1)


def _view(checkpoint: _Checkpoint) -> ReplayState:
    departures = checkpoint.departures
    return ReplayState(
        checkpoint.time,
        tuple(p.view() for p in checkpoint.patients),
        MappingProxyType(dict(checkpoint.staff)),
        departures,
        checkpoint.displacements,
        checkpoint.last_events,
        MappingProxyType(
            {d: sum(p.destination == d for p in departures) for d in ("alta", "ingreso")}
        ),
    )


def _fold(checkpoint: _Checkpoint, events: Iterable[Event], t: float) -> ReplayState:
    """Pure reconstruction, also used to compare arbitrary earlier checkpoints."""
    accumulator = _Accumulator(checkpoint)
    for event in events:
        if event.sim_time > t:
            break
        accumulator.apply(event)
    return _view(accumulator.snapshot(t))


def _check_time(t: float, horizon: float) -> None:
    if isinstance(t, bool) or not isinstance(t, int | float) or not math.isfinite(t):
        raise ValueError("time must be a finite number of simulation minutes")
    if not 0 <= t <= horizon:
        raise ValueError(f"need 0 <= time <= horizon ({horizon})")


def build_replay_index(store: RunStore, run_id: str) -> ReplayIndex:
    """Validate one binary pass and retain a full state before each hourly boundary."""
    info, _ = read_run_header(store, run_id)
    horizon = float(info.days * 1440)
    path = store.root / run_id / "eventos.jsonl"
    accumulator = _Accumulator(_empty())
    checkpoints = []
    boundary = 0
    number = 0
    previous = 0.0
    try:
        with store._file(run_id, "eventos.jsonl").open("rb") as source:
            while True:
                offset = source.tell()
                raw = source.readline()
                if not raw:
                    break
                number += 1
                event = from_json(raw.decode("utf-8"))
                if event.run_id != run_id:
                    raise ValueError("event does not match run")
                if not previous <= event.sim_time <= horizon:
                    raise ValueError("event time is unordered or exceeds horizon")
                while boundary <= event.sim_time:
                    checkpoints.append(accumulator.snapshot(float(boundary), offset, number))
                    boundary += 60
                accumulator.apply(event)
                previous = event.sim_time
            while boundary <= horizon:
                checkpoints.append(accumulator.snapshot(float(boundary), offset, number + 1))
                boundary += 60
    except (OSError, ValueError, KeyError) as error:
        where = str(path) if not number else f"{path}:{number}"
        raise RunReadError(f"{where}: {error}") from error
    return ReplayIndex(run_id, horizon, offset, number, tuple(checkpoints))


def read_replay_state(store: RunStore, run_id: str, index: ReplayIndex, t: float) -> ReplayState:
    """Seek the preceding snapshot and validate no more than its one-hour bucket."""
    _check_time(t, index.horizon)
    path = store.root / run_id / "eventos.jsonl"
    if index.run_id != run_id:
        raise RunReadError(f"{path}: index belongs to run {index.run_id!r}")
    hour = int(t // 60)
    checkpoint = index._checkpoints[hour]
    stop = (
        index._checkpoints[hour + 1].offset
        if hour + 1 < len(index._checkpoints)
        else index.file_size
    )
    number = checkpoint.line
    accumulator = _Accumulator(checkpoint)
    previous = checkpoint.time
    try:
        with store._file(run_id, "eventos.jsonl").open("rb") as source:
            if source.seek(0, 2) != index.file_size:
                raise ValueError("indexed log size has changed")
            source.seek(checkpoint.offset)
            while source.tell() < stop:
                raw = source.readline()
                if not raw or source.tell() > stop:
                    raise ValueError("indexed log is truncated or a byte boundary changed")
                event = from_json(raw.decode("utf-8"))
                if event.run_id != run_id:
                    raise ValueError("indexed event does not match run")
                if (
                    not previous <= event.sim_time <= index.horizon
                    or event.sim_time >= checkpoint.time + 60
                ):
                    raise ValueError("indexed event is outside its ordered hour")
                if event.sim_time > t:
                    break
                accumulator.apply(event)
                previous = event.sim_time
                number += 1
    except (OSError, ValueError, KeyError) as error:
        raise RunReadError(f"{path}:{number}: {error}") from error
    return _view(accumulator.snapshot(float(t)))


def replay_counts(result: RunResults, t: float) -> ReplayCounts:
    """Sample authoritative curves and saved physical capacity at time t."""
    curves = result.analysis.curves
    _check_time(t, curves.horizon)
    return ReplayCounts(
        **{name: curves.value(name, t) for name in CURVES}, boxes=result.center.boxes
    )
