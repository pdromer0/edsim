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
"""

import json
import shutil
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from edsim.arrivals.report import config_fingerprint
from edsim.clinical_record import (
    DEFAULT_PROFILES_FILE,
    PROFILE_NAMES,
    derived_run_id,
    load_record_profiles,
    notebook_csv,
    record,
    record_json,
)
from edsim.engine.events import Event, from_json
from edsim.runs.store import RunStore

MINUTES_PER_DAY = 1440.0
RECORDS_DIR = "registros"
"""The folder of a run that holds the recordings, one subfolder per profile and seed."""
RECORDED_FILE = "registrado.jsonl"
NOTEBOOK_FILE = "defectos.csv"
PROFILES_COPY = "registro_clinico.toml"
INFO_FILE = "registro.json"


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
    text = store.read_file(run_id, "eventos.jsonl").decode("utf-8")
    events = []
    for number, line in enumerate(text.split("\n"), start=1):
        if not line:
            continue
        try:
            events.append(from_json(line))
        except ValueError as error:
            raise ValueError(f"eventos.jsonl:{number}: {error}") from error
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
        ValueError: If the run is not valid, ``profile`` is not one of the three, ``seed`` is not
            an integer >= 0, the derived ``run_id`` does not fit in 64 characters, the log is not
            valid or the profiles file is not. All before writing anything.
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
        recording = record(
            events,
            profiles[profile],
            seed,
            horizon=saved.days * MINUTES_PER_DAY,
            run_id=run_id,
        )
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
        temporary.rename(destination)
        return RecordRunResult(path=destination, info=info)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
