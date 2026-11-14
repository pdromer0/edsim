"""``record_run``: write what the hospital wrote down of a saved run, next to the run.

It is not a new run: ``simulate_run`` is still the only writer of runs. ``record_run`` reads the
true log of a run that already exists and writes ``registros/<perfil>-s<semilla>/`` inside its
folder (docs/specs/hito-7.md, «En disco»), atomically and without touching any file of the run:

- ``registrado.jsonl``: the records, one line each, in emission order;
- ``defectos.csv``: the notebook of the slips;
- ``registro_clinico.toml``: the copy of the profiles file that was used, and the one the
  profiles are loaded from, as ``simulate_run`` does with its configuration files;
- ``registro.json``: the derived ``run_id``, the origin, the profile, the seed, the horizon, the
  fingerprint of the copy and the counts of the account. No date: the same truth, profile and
  seed give the same bytes.

``read_recorded_run`` reads one of those folders back, with the true log and the horizon and
warm-up of the run, so ``edsim.clinical_record.compare`` can reconcile it; ``read_recorded_records``
reads its ``registrado.jsonl``. A run read with ``--postgres`` takes the records from bronze
instead and never reads that file.
"""

import json
import shutil
import stat
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from edsim.arrivals.rate import MINUTES_PER_DAY
from edsim.arrivals.report import config_fingerprint
from edsim.clinical_record import (
    DEFAULT_PROFILES_FILE,
    PROFILE_NAMES,
    Comparison,
    NotebookRow,
    Record,
    compare,
    derived_run_id,
    load_record_profiles,
    notebook_csv,
    read_notebook_csv,
    record,
    record_from_json,
    record_json,
)
from edsim.engine.events import Event, from_json
from edsim.runs.store import RunStore

RECORDS_DIR = "registros"
"""The folder of a run that holds the recordings, one subfolder per profile and seed."""
RECORDED_FILE = "registrado.jsonl"
NOTEBOOK_FILE = "defectos.csv"
PROFILES_COPY = "registro_clinico.toml"
INFO_FILE = "registro.json"


class RunLogError(ValueError):
    """The true log of the run cannot be recorded: a line is not an event, or it is not the log of
    the run. It is a problem of the data, not of how ``record_run`` was called."""


@dataclass(frozen=True, slots=True)
class RecordRunResult:
    """What ``record_run`` wrote.

    Attributes:
        path: The folder ``registros/<perfil>-s<semilla>/`` of the run.
        info: The content of ``registro.json``.
    """

    path: Path
    info: Mapping[str, object]


def _check_destination(path: Path) -> None:
    """Fail if the recording exists or ``registros`` is not a folder."""
    if path.parent.exists() and not path.parent.is_dir():
        raise NotADirectoryError(f"not a directory: {path.parent}")
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"destination already exists: {path}")


def _read_events(store: RunStore, run_id: str) -> list[Event]:
    """The true log of a run, one validated event per line.

    Split by ``\\n``, not ``splitlines``: that one also splits at U+2028 inside a text.
    """
    try:
        text = store.read_file(run_id, "eventos.jsonl").decode("utf-8")
    except UnicodeDecodeError as error:
        raise RunLogError(f"eventos.jsonl: {error}") from error
    events = []
    for number, line in enumerate(text.split("\n"), start=1):
        if not line:
            continue
        try:
            events.append(from_json(line))
        except ValueError as error:
            raise RunLogError(f"eventos.jsonl:{number}: {error}") from error
    return events


def record_run(
    store: RunStore,
    run_id: str,
    profile: str,
    seed: int | None = None,
    *,
    profiles_file: str | Path = DEFAULT_PROFILES_FILE,
) -> RecordRunResult:
    """Record the true log of a saved run with a profile of slips.

    Args:
        store: The catalog of runs the run is in.
        run_id: The run, which must exist and be valid.
        profile: ``limpio``, ``realista`` or ``hostil``.
        seed: The seed of the recording; by default, the one of the run.
        profiles_file: The profiles file, ``config/registro_clinico.toml`` by default.

    Returns:
        The folder written and the content of its ``registro.json``.

    Raises:
        RunLogError: If the true log of the run is not valid or is not the log of that run; a
            ``ValueError``, but of the data.
        ValueError: If the run is not valid, ``profile`` is not one of the three, ``seed`` is not
            an integer >= 0, the derived ``run_id`` does not fit in 64 characters or the profiles
            file is not valid. All before writing anything.
        FileExistsError: If ``registros/<perfil>-s<semilla>/`` already exists; nothing is
            overwritten.
        NotADirectoryError: If ``registros`` exists and is not a folder.
        OSError: If a file cannot be read or written.
        RuntimeError: If the account of the recording does not balance (a broken internal rule).
    """
    saved = store.open(run_id)
    if profile not in PROFILE_NAMES:
        raise ValueError(f"unknown profile {profile!r}: the profiles are {PROFILE_NAMES!r}")
    seed = saved.seed if seed is None else seed
    derived_run_id(run_id, profile, seed)  # ValueError for a bad seed or an id that does not fit
    run_dir = store.root / run_id
    records_dir = run_dir / RECORDS_DIR
    destination = records_dir / f"{profile}-s{seed}"
    _check_destination(destination)
    events = _read_events(store, run_id)

    temporary = Path(tempfile.mkdtemp(prefix=f".{RECORDS_DIR}-{profile}-s{seed}-", dir=run_dir))
    try:
        # The permissions a new folder gets with the umask of the process, as simulate_run does.
        reference = temporary / ".permissions"
        reference.mkdir()
        temporary.chmod(stat.S_IMODE(reference.stat().st_mode))
        reference.rmdir()

        copy = temporary / PROFILES_COPY
        shutil.copyfile(profiles_file, copy)
        profiles = load_record_profiles(copy)
        try:
            recording = record(
                events,
                profiles[profile],
                seed,
                horizon=saved.days * MINUTES_PER_DAY,
                run_id=run_id,
            )
        except ValueError as error:
            # The profile, the seed and the horizon were already checked: it is the log.
            raise RunLogError(f"eventos.jsonl: {error}") from error
        info = {
            key: recording.info[key]
            for key in ("run_id", "run_id_origen", "perfil", "semilla", "horizonte")
        }
        info["huella"] = config_fingerprint(copy)
        info["cuenta"] = dict(recording.info["cuenta"])

        recorded = "".join(record_json(r) + "\n" for r in recording.records)
        (temporary / RECORDED_FILE).write_bytes(recorded.encode("utf-8"))
        (temporary / NOTEBOOK_FILE).write_bytes(notebook_csv(recording.notebook).encode("utf-8"))
        text = json.dumps(info, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
        (temporary / INFO_FILE).write_bytes(text.encode("utf-8"))

        _check_destination(destination)
        records_dir.mkdir(exist_ok=True)
        try:
            temporary.rename(destination)
        except OSError as error:
            if destination.exists():  # another process wrote it between the check and now
                raise FileExistsError(f"destination already exists: {destination}") from error
            raise
        return RecordRunResult(path=destination, info=info)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


@dataclass(frozen=True, slots=True)
class RecordedRun:
    """A recording on disk, read back without its records: what ``compare`` needs besides them.

    Attributes:
        run_id: The true run.
        derived_run_id: The run of the recording, ``<run_id>_<perfil>_s<semilla>``.
        profile: The profile of the recording.
        seed: The seed of the recording.
        path: The folder ``registros/<perfil>-s<semilla>/``.
        info: The content of ``registro.json``.
        truth: The true log of the run, validated.
        notebook: The rows of ``defectos.csv``.
        horizon: The horizon of the run in minutes.
        warmup: The warm-up of the run in minutes.
    """

    run_id: str
    derived_run_id: str
    profile: str
    seed: int
    path: Path
    info: Mapping[str, object]
    truth: tuple[Event, ...]
    notebook: tuple[NotebookRow, ...]
    horizon: float
    warmup: float

    def compare(self, records: Sequence[Record]) -> Comparison:
        """Reconcile ``records`` (from the files or from bronze) with this run's truth."""
        return compare(self.truth, records, self.notebook, horizon=self.horizon, warmup=self.warmup)


def _read_regular(path: Path) -> bytes:
    """The bytes of a regular file, not a link: the recording must be what ``record_run`` wrote."""
    if not stat.S_ISREG(path.lstat().st_mode):
        raise RunLogError(f"{path.name}: not a regular file")
    return path.read_bytes()


def _read_text(path: Path) -> str:
    try:
        return _read_regular(path).decode("utf-8")
    except UnicodeDecodeError as error:
        raise RunLogError(f"{path.name}: {error}") from error


def read_recorded_run(
    store: RunStore, run_id: str, profile: str, seed: int | None = None
) -> RecordedRun:
    """Read ``registros/<perfil>-s<semilla>/`` of a saved run, with its truth and its notebook.

    Args:
        store: The catalog of runs the run is in.
        run_id: The run, which must exist and be valid.
        profile: ``limpio``, ``realista`` or ``hostil``.
        seed: The seed of the recording; by default, the one of the run.

    Raises:
        RunLogError: If the truth, ``registro.json`` or ``defectos.csv`` is not valid, or
            ``registro.json`` says it is the recording of another run, profile or seed.
        FileNotFoundError: If the recording does not exist (``edsim registro generar`` writes it).
        ValueError: If the run is not valid, ``profile`` is not one of the three or ``seed`` is
            not an integer >= 0.
        OSError: If a file cannot be read.
    """
    saved = store.open(run_id)
    if profile not in PROFILE_NAMES:
        raise ValueError(f"unknown profile {profile!r}: the profiles are {PROFILE_NAMES!r}")
    seed = saved.seed if seed is None else seed
    derived = derived_run_id(run_id, profile, seed)
    path = store.root / run_id / RECORDS_DIR / f"{profile}-s{seed}"
    if not path.is_dir():
        raise FileNotFoundError(f"there is no recording {profile}-s{seed} of {run_id}: {path}")

    try:
        info = json.loads(_read_text(path / INFO_FILE))
    except json.JSONDecodeError as error:
        raise RunLogError(f"{INFO_FILE}: {error}") from error
    expected = {
        "run_id": derived,
        "run_id_origen": run_id,
        "perfil": profile,
        "semilla": seed,
    }
    if not isinstance(info, dict):
        raise RunLogError(f"{INFO_FILE}: must be a JSON object")
    for key, value in expected.items():
        if info.get(key) != value:
            raise RunLogError(f"{INFO_FILE}: {key} is {info.get(key)!r}, not {value!r}")
    horizon = info.get("horizonte")
    if isinstance(horizon, bool) or not isinstance(horizon, int | float):
        raise RunLogError(f"{INFO_FILE}: horizonte must be a number, got {horizon!r}")

    notebook_text = _read_text(path / NOTEBOOK_FILE)
    try:
        notebook = read_notebook_csv(notebook_text)
    except ValueError as error:
        raise RunLogError(str(error)) from error
    return RecordedRun(
        run_id=run_id,
        derived_run_id=derived,
        profile=profile,
        seed=seed,
        path=path,
        info=info,
        truth=tuple(_read_events(store, run_id)),
        notebook=notebook,
        horizon=float(horizon),
        warmup=float(saved.warmup_days * MINUTES_PER_DAY),
    )


def read_recorded_records(run: RecordedRun) -> tuple[Record, ...]:
    """The records of ``registrado.jsonl``, in the order written.

    Split by ``\\n``, not ``splitlines``: that one also splits at U+2028 inside a text.

    Raises:
        RunLogError: If a line is not a record.
        OSError: If the file cannot be read.
    """
    records = []
    for number, line in enumerate(_read_text(run.path / RECORDED_FILE).split("\n"), start=1):
        if not line:
            continue
        try:
            records.append(record_from_json(line))
        except ValueError as error:
            raise RunLogError(f"{RECORDED_FILE}:{number}: {error}") from error
    return tuple(records)
