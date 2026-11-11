"""Versioned run metadata and the on-disk catalog.

``run.json`` has two format versions. Version 1 (application phase 1) has 16
keys and only the provisional model existed. Version 2 (task 4.5b) adds
``model``, ``"provisional"`` or ``"clinico"``, and, only with the clinical
model, the original path and the fingerprint of the clinical profiles
(``perfiles.toml``). New runs always write version 2; version 1 is only read,
as a provisional run.
"""

from __future__ import annotations

import json
import math
import shutil
import stat
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Literal, Self
from zipfile import ZIP_DEFLATED, ZipFile

from edsim.engine.events import (
    CURRENT_CLINICAL_SCHEMA_VERSION,
    OUTCOME_SCHEMA_VERSION,
    PROVISIONAL_SCHEMA_VERSION,
)
from edsim.runs.identifiers import validate_run_id

_RUN_FILES = (
    "run.json",
    "centro.toml",
    "llegadas.toml",
    "eventos.jsonl",
    "ground_truth_episodios.csv",
    "ground_truth_dias.csv",
)
_PROFILES_FILE = "perfiles.toml"
"""The copy of the clinical profiles, only in runs of the clinical model."""

FORMAT_VERSION = 2
"""The version of ``run.json`` that new runs of the provisional and milestone 4 models write."""

OUTCOME_FORMAT_VERSION = 3
"""The version of ``run.json`` that new runs of the milestone 5 model write (task 5.3).

Version 2 plus ``schema_version``, the version of the catalog of its log (4).
The model stays ``"clinico``: the milestone 5 model is clinical, with its
copy of ``perfiles.toml``, and the version says which clinical model it is.
"""

RUN_MODELS = ("provisional", "clinico")
"""The patient models of a run: the provisional one of milestone 3 or the clinical one."""

type RunModel = Literal["provisional", "clinico"]

_CLINICAL_FIELDS = ("clinical_profiles_path", "clinical_profiles_fingerprint")


@dataclass(frozen=True, slots=True)
class RunInfo:
    """The complete metadata stored in run.json, without transient results.

    ``model`` explains the two optional fields: with ``"clinico"`` they are the
    original path and the fingerprint of the clinical profiles, and with
    ``"provisional"`` they are ``None``. ``profile_path`` and
    ``profile_fingerprint`` are those of the arrival profile, in both models.
    ``format_version`` is the version of the file it was read from: 1 only
    with the provisional model, 3 only with the milestone 5 model.

    ``schema_version`` exists only in version 3 (task 5.3), always 4, the
    catalog of the milestone 5 model: one way to write each run. In versions 1
    and 2 it is ``None``, and the version of the catalog follows from the
    model (``catalog_version``).
    """

    format_version: int
    run_id: str
    created_at: str
    origin: Literal["app", "cli"]
    edsim_version: str
    seed: int
    days: int
    warmup_days: int
    variant: str
    center_fingerprint: str
    profile_fingerprint: str
    center_path: str
    profile_path: str
    invariant_violations: int
    window_arrivals: int
    simulation_seconds: float
    model: RunModel = "provisional"
    clinical_profiles_path: str | None = None
    clinical_profiles_fingerprint: str | None = None
    schema_version: int | None = None

    @property
    def catalog_version(self) -> int:
        """The version of the catalog of the log of the run, for any ``run.json``.

        1 with version 1 and with version 2 of the provisional model, 3 with
        version 2 of the clinical model (milestone 4) and ``schema_version``
        (4) with version 3 (milestone 5).
        """
        if self.schema_version is not None:
            return self.schema_version
        return CURRENT_CLINICAL_SCHEMA_VERSION if self.is_clinical else PROVISIONAL_SCHEMA_VERSION

    @property
    def arrivals_per_day(self) -> float:
        """Observed arrivals per day, excluding the warmup period."""
        return self.window_arrivals / (self.days - self.warmup_days)

    def __post_init__(self) -> None:
        if type(self.format_version) is not int or self.format_version not in (1, 2, 3):
            raise ValueError(f"unsupported format_version: {self.format_version!r}")
        if self.format_version == OUTCOME_FORMAT_VERSION:
            if self.model != "clinico":
                raise ValueError("format_version 3 is of the milestone 5 model, model clinico")
            if (
                type(self.schema_version) is not int
                or self.schema_version != OUTCOME_SCHEMA_VERSION
            ):
                raise ValueError(
                    f"format_version 3 needs schema_version {OUTCOME_SCHEMA_VERSION}, "
                    f"got {self.schema_version!r}"
                )
        elif self.schema_version is not None:
            raise ValueError(
                f"schema_version exists only in format_version 3, got {self.schema_version!r} "
                f"with format_version {self.format_version}"
            )
        if self.model not in RUN_MODELS:
            raise ValueError(f"model must be one of {RUN_MODELS}, got {self.model!r}")
        if self.model == "clinico":
            if self.format_version == 1:
                raise ValueError("format_version 1 has no clinical model")
            for name in _CLINICAL_FIELDS:
                if not isinstance(getattr(self, name), str) or not getattr(self, name):
                    raise ValueError(f"{name} must be a non-empty string with model clinico")
        else:
            for name in _CLINICAL_FIELDS:
                if getattr(self, name) is not None:
                    raise ValueError(f"{name} must be None with model provisional")
        validate_run_id(self.run_id)
        for name in (
            "created_at",
            "edsim_version",
            "variant",
            "center_fingerprint",
            "profile_fingerprint",
            "center_path",
            "profile_path",
        ):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError(f"{name} must be a non-empty string")
        if datetime.fromisoformat(self.created_at).utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        if self.origin not in ("app", "cli"):
            raise ValueError("origin must be app or cli")
        for name in ("seed", "days", "warmup_days", "invariant_violations", "window_arrivals"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if not 0 <= self.warmup_days < self.days:
            raise ValueError("warmup_days must be less than days")
        if (
            type(self.simulation_seconds) not in (int, float)
            or not math.isfinite(self.simulation_seconds)
            or self.simulation_seconds < 0
        ):
            raise ValueError("simulation_seconds must be finite and non-negative")

    @property
    def is_clinical(self) -> bool:
        """Whether the run used the clinical model, with a copy of ``perfiles.toml``."""
        return self.model == "clinico"

    @classmethod
    def read(cls, path: str | Path) -> Self:
        """Read metadata, rejecting incomplete or unsupported records.

        The keys must be exactly those of the version: defaults never fill a
        missing key. Version 1 is read as the provisional model.
        """
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("run.json must contain an object")
        version = data.get("format_version")
        if type(version) is not int or version not in (1, 2, 3):
            raise ValueError(f"unsupported format_version: {version!r}")
        expected = set(_V1_KEYS)
        if version >= 2:
            expected.add("model")
            if data.get("model") == "clinico":
                expected.update(_CLINICAL_FIELDS)
        if version == OUTCOME_FORMAT_VERSION:
            expected.add("schema_version")
        if data.keys() != expected:
            missing, extra = sorted(expected - data.keys()), sorted(data.keys() - expected)
            raise ValueError(
                f"invalid run.json fields for format_version {version}: "
                f"missing {missing}, unexpected {extra}"
            )
        return cls(**data)

    def write(self, path: str | Path) -> None:
        """Write version 2 or 3 in a stable UTF-8 representation, without null keys.

        Raises:
            ValueError: If the metadata is of version 1, which is only read.
        """
        if self.format_version not in (FORMAT_VERSION, OUTCOME_FORMAT_VERSION):
            raise ValueError(
                f"only format_version {FORMAT_VERSION} and {OUTCOME_FORMAT_VERSION} are written"
            )
        data = asdict(self)
        if not self.is_clinical:
            for name in _CLINICAL_FIELDS:
                del data[name]
        if self.schema_version is None:
            del data["schema_version"]
        Path(path).write_text(
            json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
            encoding="utf-8",
        )


_V1_KEYS = tuple(f.name for f in fields(RunInfo))[:16]
"""The 16 keys of version 1, which version 2 keeps in the same order."""


class RunStore:
    """Inspect and delete runs under one catalog root."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _path(self, run_id: str) -> Path:
        validate_run_id(run_id)
        path = self.root / run_id
        root = self.root.resolve()
        resolved = path.resolve()
        if path.is_symlink() or resolved == root or not resolved.is_relative_to(root):
            raise ValueError(f"run path must remain inside {root}: {run_id}")
        return path

    def open(self, run_id: str) -> RunInfo:
        """Read a valid run whose identifier matches its directory."""
        path = self._path(run_id)
        info = RunInfo.read(path / "run.json")
        if info.run_id != run_id:
            raise ValueError("run_id does not match directory name")
        return info

    def exists(self, run_id: str) -> bool:
        """Whether the name is occupied, including invalid runs and symlinks."""
        validate_run_id(run_id)
        path = self.root / run_id
        return path.exists() or path.is_symlink()

    def _scan(self) -> tuple[list[RunInfo], list[tuple[str, str]]]:
        valid, invalid = [], []
        if not self.root.exists():
            return valid, invalid
        for path in sorted(self.root.iterdir()):
            if path.name.startswith(".") or not (path.is_dir() or path.is_symlink()):
                continue
            try:
                valid.append(self.open(path.name))
            except (OSError, ValueError) as error:
                invalid.append((path.name, str(error)))
        valid.sort(
            key=lambda info: (datetime.fromisoformat(info.created_at), info.run_id), reverse=True
        )
        return valid, invalid

    def suggest_run_id(self, preferred: str) -> str | None:
        """Find a free identifier without truncating the preferred name.

        Return None when a collision suffix cannot fit in 64 characters.
        Occupied names include invalid runs, files and dangling symlinks.
        """
        validate_run_id(preferred)
        candidate = preferred
        index = 2
        while self.exists(candidate):
            candidate = f"{preferred}-{index}"
            if len(candidate) > 64:
                return None
            index += 1
        return candidate

    def list(self) -> list[RunInfo]:
        """Valid runs, most recent first; hidden and invalid runs are omitted."""
        return self._scan()[0]

    def invalid(self) -> list[tuple[str, str]]:
        """Visible invalid directories and their diagnostic reasons."""
        return self._scan()[1]

    def delete(self, run_id: str) -> None:
        """Delete an occupied directory only after validating its containment."""
        shutil.rmtree(self._path(run_id))

    def run_files(self, run_id: str) -> tuple[str, ...]:
        """The persisted files of a run: six, and ``perfiles.toml`` with the clinical model."""
        # The model comes from run.json, a regular file before reading it, never a FIFO.
        clinical = RunInfo.read(self._file(run_id, "run.json")).is_clinical
        return (*_RUN_FILES, _PROFILES_FILE) if clinical else _RUN_FILES

    def archive(self, run_id: str) -> bytes:
        """Zip the persisted files, rejecting symlinks and non-regular entries.

        Six files, and seven with the clinical model (``perfiles.toml``).
        """
        files = [self._file(run_id, name) for name in self.run_files(run_id)]
        buffer = BytesIO()
        with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
            for path in files:
                archive.write(path, arcname=path.name)
        return buffer.getvalue()

    def _file(self, run_id: str, filename: str) -> Path:
        """Resolve one regular format file before opening it, including FIFOs."""
        if filename not in (*_RUN_FILES, _PROFILES_FILE):
            raise ValueError(f"unknown run filename: {filename!r}")
        path = self._path(run_id) / filename
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError(f"run requires regular files: {path}")
        return path

    def read_file(self, run_id: str, filename: str) -> bytes:
        """Read one of the format files, rejecting links and other entries."""
        return self._file(run_id, filename).read_bytes()
