"""From a saved run to the rows of the ``verdad`` schema, without connecting (task 8.4, H8-6).

``truth_run`` reads a run saved by ``edsim.runs`` and gives its four tables of ``verdad``
(migration ``002_verdad.sql``) as ``TruthTable``: the name, the columns in the order of the rows
and ``rows``, which gives each row **one at a time**. A year is 1.4 million events and as many
rows of the notebook: nothing here builds a list of them, so a load keeps a few megabytes of rows
in memory, not the run. The load itself, with ``COPY``, is ``edsim.store.postgres.load_truth``.

- ``verdad.eventos``: the lines of ``eventos.jsonl``, each one validated by ``from_json``.
- ``verdad.episodios`` and ``verdad.dias``: the rows of ``ground_truth_episodios.csv`` and
  ``ground_truth_dias.csv``, with the columns of the CSV by name. An empty cell is ``None``
  (``NULL``); no other cell is parsed: Postgres reads the text by the type of its column.
- ``verdad.libreta``: the rows of ``registros/<perfil>-s<semilla>/defectos.csv`` of every recording
  of the run, each with the true run, the derived run, the profile and the seed in front.

**Only the current model** (D1 of the task): the 65 columns of the episodes are those of the
milestone 5 model (catalog version 4). A run of another version is a ``TruthError`` before
anything is read, with how to regenerate it.

Standard library and ``edsim`` only: the Postgres client is not needed to prepare the rows.
"""

import csv
import json
import re
import stat
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from edsim.clinical_record import NOTEBOOK_COLUMNS, PROFILE_NAMES, derived_run_id
from edsim.engine.events import OUTCOME_SCHEMA_VERSION, from_json
from edsim.engine.report import DAY_COLUMNS, OUTCOME_EPISODE_COLUMNS
from edsim.runs.recorded import NOTEBOOK_FILE, RECORDS_DIR
from edsim.runs.store import RunStore

EVENTS_FILE = "eventos.jsonl"
EPISODES_FILE = "ground_truth_episodios.csv"
DAYS_FILE = "ground_truth_dias.csv"

EVENT_COLUMNS = (
    "event_id",
    "event_type",
    "schema_version",
    "run_id",
    "episode_id",
    "patient_id",
    "source_system",
    "sim_time",
    "event_time",
    "recorded_time",
    "payload",
)
"""The columns of ``verdad.eventos``: those of ``bronce.eventos`` without the ones of Kafka,
``valor``, ``recibido`` and ``ingest_time``. The 8.1 project of dbt declares these eleven."""

LEDGER_COLUMNS = ("run_id_origen", "run_id", "perfil", "semilla", *NOTEBOOK_COLUMNS)
"""The columns of ``verdad.libreta``: the run of the truth, the derived run, the profile, the seed
and the eleven of ``defectos.csv``."""

_RECORDING_NAME = re.compile(rf"({'|'.join(PROFILE_NAMES)})-s(\d+)")


class TruthError(RuntimeError):
    """The run cannot be loaded into ``verdad``: its model is not the current one, or a file is not
    what the engine wrote. A problem of the data, which ``edsim almacen`` reports with code 1."""


@dataclass(frozen=True, slots=True)
class TruthTable:
    """One table of ``verdad``, ready to be loaded.

    Attributes:
        name: The table inside the schema, ``eventos``.
        columns: Its columns, in the order of the rows.
        rows: Gives a new iterator over the rows each time it is called, one row per step.
        run_column: The column that holds the run of the truth, which a reload deletes by.
    """

    name: str
    columns: tuple[str, ...]
    rows: Callable[[], Iterator[tuple]]
    run_column: str = "run_id"

    @property
    def qualified_name(self) -> str:
        return f"verdad.{self.name}"


@dataclass(frozen=True, slots=True)
class TruthRun:
    """The truth of a saved run as the rows of its four tables.

    Attributes:
        run_id: The run.
        tables: ``verdad.eventos``, ``episodios``, ``dias`` and ``libreta``, in the order they load.
        recordings: ``<perfil>-s<semilla>`` of each recording whose notebook goes to the ledger;
            empty if the run has no ``registros/`` (``edsim registro generar`` writes them).
    """

    run_id: str
    tables: tuple[TruthTable, ...]
    recordings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Recording:
    """A folder ``registros/<perfil>-s<semilla>/``, with its names already checked."""

    name: str
    path: Path
    profile: str
    seed: int
    derived_run_id: str


@dataclass(frozen=True, slots=True)
class TruthLoad:
    """What ``load_truth`` wrote.

    Attributes:
        run_id: The run.
        counts: The rows written to each table, by name (``eventos``, ``episodios``, ``dias`` and
            ``libreta``).
        recordings: ``<perfil>-s<semilla>`` of each recording whose notebook was loaded.
        seconds: Real seconds the load took, from the connection to the commit.
    """

    run_id: str
    counts: Mapping[str, int]
    recordings: tuple[str, ...]
    seconds: float


def truth_run(store: RunStore, run_id: str) -> TruthRun:
    """The four tables of ``verdad`` of a saved run, with the files checked but not read.

    Checks what can be checked cheaply before anything is written: the model of the run and the
    exact header of every CSV. The rows are read, and validated, when ``rows`` is iterated.

    Raises:
        ValueError: If ``run_id`` is not valid or the run does not exist or is not valid.
        OSError: If a file cannot be opened.
        TruthError: If the run is not of the milestone 5 model (catalog version 4), a header is not
            the one of its version, or a folder of ``registros/`` is not ``<perfil>-s<semilla>``.
    """
    info = store.open(run_id)
    if info.catalog_version != OUTCOME_SCHEMA_VERSION:
        model = "clínico del hito 4" if info.is_clinical else "provisional"
        raise TruthError(
            f"{run_id} es del esquema {info.catalog_version} (modelo {model}) y la verdad de "
            f"Postgres es la del esquema {OUTCOME_SCHEMA_VERSION} (modelo del hito 5): "
            f"regenérala con «edsim motor simular»"
        )
    recordings = _recordings(store.root / run_id, run_id)
    for filename, header in ((EPISODES_FILE, OUTCOME_EPISODE_COLUMNS), (DAYS_FILE, DAY_COLUMNS)):
        with store.open_file(run_id, filename) as source:
            _check_header(csv.reader(source, strict=True), header, filename)
    for recording in recordings:
        with _open_regular(recording.path / NOTEBOOK_FILE) as source:
            _check_header(csv.reader(source, strict=True), NOTEBOOK_COLUMNS, NOTEBOOK_FILE)
    return TruthRun(
        run_id=run_id,
        tables=(
            TruthTable("eventos", EVENT_COLUMNS, lambda: _event_rows(store, run_id)),
            TruthTable(
                "episodios",
                OUTCOME_EPISODE_COLUMNS,
                lambda: _csv_rows(store, run_id, EPISODES_FILE, OUTCOME_EPISODE_COLUMNS),
            ),
            TruthTable(
                "dias", DAY_COLUMNS, lambda: _csv_rows(store, run_id, DAYS_FILE, DAY_COLUMNS)
            ),
            TruthTable(
                "libreta",
                LEDGER_COLUMNS,
                lambda: _ledger_rows(run_id, recordings),
                run_column="run_id_origen",
            ),
        ),
        recordings=tuple(recording.name for recording in recordings),
    )


def _recordings(run_path: Path, run_id: str) -> list[_Recording]:
    """The recordings of the run, in name order; none if it has no ``registros/``."""
    directory = run_path / RECORDS_DIR
    if not directory.exists():
        return []
    found = []
    for entry in sorted(directory.iterdir(), key=lambda item: item.name):
        match = _RECORDING_NAME.fullmatch(entry.name)
        if match is None or not entry.is_dir() or entry.is_symlink():
            raise TruthError(
                f"{entry}: en {RECORDS_DIR}/ solo puede haber carpetas "
                f"<perfil>-s<semilla> ({', '.join(PROFILE_NAMES)})"
            )
        profile, seed = match[1], int(match[2])
        if f"{profile}-s{seed}" != entry.name:  # s007 is not s7: the seed is an integer
            raise TruthError(f"{entry}: la semilla no está escrita como un entero")
        try:
            derived = derived_run_id(run_id, profile, seed)
        except ValueError as error:
            raise TruthError(f"{entry}: {error}") from error
        found.append(_Recording(entry.name, entry, profile, seed, derived))
    return found


def _open_regular(path: Path):
    """The notebook as UTF-8 text, only if it is a regular file (not a link or a FIFO)."""
    try:
        regular = stat.S_ISREG(path.lstat().st_mode)
    except FileNotFoundError:
        raise TruthError(f"{path}: falta el fichero de la libreta") from None
    if not regular:
        raise TruthError(f"{path}: no es un fichero regular")
    return path.open(encoding="utf-8", newline="")


def _check_header(reader, expected: tuple[str, ...], filename: str) -> None:
    try:
        header = next(reader, None)
    except csv.Error as error:
        raise TruthError(f"{filename}:1: {error}") from error
    if header is None or tuple(header) != expected:
        raise TruthError(f"{filename}:1: la cabecera no es la esperada ({len(expected)} columnas)")


def _cells(reader, filename: str, width: int) -> Iterator[list[str]]:
    """The rows of ``reader`` after its header, each with exactly ``width`` cells."""
    try:
        for row in reader:
            if len(row) != width:
                raise TruthError(
                    f"{filename}:{reader.line_num}: {len(row)} celdas y la cabecera tiene {width}"
                )
            yield row
    except csv.Error as error:
        raise TruthError(f"{filename}:{reader.line_num}: {error}") from error


def _nullable(row: list[str]) -> tuple:
    """The row with every empty cell as ``None``: ``NULL`` in Postgres."""
    return tuple(None if cell == "" else cell for cell in row)


def _event_rows(store: RunStore, run_id: str) -> Iterator[tuple]:
    with store.open_file(run_id, EVENTS_FILE) as source:
        for number, line in enumerate(source, start=1):
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                event = from_json(line)
                # The payload from the line itself: that of the event has tuples and read-only
                # mappings, which ``json`` cannot write.
                payload = json.dumps(json.loads(line)["payload"], ensure_ascii=False)
            except ValueError as error:
                raise TruthError(f"{EVENTS_FILE}:{number}: {error}") from error
            if event.run_id != run_id:
                raise TruthError(
                    f"{EVENTS_FILE}:{number}: el evento es de la ejecución {event.run_id}, "
                    f"no de {run_id}"
                )
            yield (
                event.event_id,
                event.event_type,
                event.schema_version,
                event.run_id,
                event.episode_id,
                event.patient_id,
                event.source_system,
                event.sim_time,
                event.event_time,
                event.recorded_time,
                payload,
            )


def _csv_rows(
    store: RunStore, run_id: str, filename: str, header: tuple[str, ...]
) -> Iterator[tuple]:
    run_index = header.index("run_id")
    with store.open_file(run_id, filename) as source:
        reader = csv.reader(source, strict=True)
        _check_header(reader, header, filename)
        for row in _cells(reader, filename, len(header)):
            if row[run_index] != run_id:
                raise TruthError(
                    f"{filename}:{reader.line_num}: run_id es {row[run_index]!r}, no {run_id!r}"
                )
            yield _nullable(row)


def _ledger_rows(run_id: str, recordings: list[_Recording]) -> Iterator[tuple]:
    for recording in recordings:
        with _open_regular(recording.path / NOTEBOOK_FILE) as source:
            reader = csv.reader(source, strict=True)
            _check_header(reader, NOTEBOOK_COLUMNS, NOTEBOOK_FILE)
            for row in _cells(reader, f"{recording.name}/{NOTEBOOK_FILE}", len(NOTEBOOK_COLUMNS)):
                yield (
                    run_id,
                    recording.derived_run_id,
                    recording.profile,
                    recording.seed,
                    *_nullable(row),
                )
