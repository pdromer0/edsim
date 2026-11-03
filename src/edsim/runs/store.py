"""Versioned run metadata and the on-disk catalog."""

from __future__ import annotations

import json
import math
import shutil
import stat
from dataclasses import asdict, dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Literal, Self
from zipfile import ZIP_DEFLATED, ZipFile

from edsim.runs.identifiers import validate_run_id

_RUN_FILES = (
    "run.json",
    "centro.toml",
    "llegadas.toml",
    "eventos.jsonl",
    "ground_truth_episodios.csv",
    "ground_truth_dias.csv",
)


@dataclass(frozen=True, slots=True)
class RunInfo:
    """The complete metadata stored in run.json, without transient results."""

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

    @property
    def arrivals_per_day(self) -> float:
        """Observed arrivals per day, excluding the warmup period."""
        return self.window_arrivals / (self.days - self.warmup_days)

    def __post_init__(self) -> None:
        if type(self.format_version) is not int or self.format_version != 1:
            raise ValueError(f"unsupported format_version: {self.format_version!r}")
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

    @classmethod
    def read(cls, path: str | Path) -> Self:
        """Read metadata, rejecting incomplete or unsupported records."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("run.json must contain an object")
        try:
            return cls(**data)
        except TypeError as error:
            raise ValueError(f"invalid run.json fields: {error}") from error

    def write(self, path: str | Path) -> None:
        """Write all metadata in a stable UTF-8 representation."""
        Path(path).write_text(
            json.dumps(asdict(self), ensure_ascii=False, allow_nan=False, indent=2) + "\n",
            encoding="utf-8",
        )


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

    def archive(self, run_id: str) -> bytes:
        """Zip the six persisted files, rejecting symlinks and non-regular entries."""
        files = [self._file(run_id, name) for name in _RUN_FILES]
        buffer = BytesIO()
        with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
            for path in files:
                archive.write(path, arcname=path.name)
        return buffer.getvalue()

    def _file(self, run_id: str, filename: str) -> Path:
        """Resolve one regular format file before opening it, including FIFOs."""
        if filename not in _RUN_FILES:
            raise ValueError(f"unknown run filename: {filename!r}")
        path = self._path(run_id) / filename
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError(f"run requires regular files: {path}")
        return path

    def read_file(self, run_id: str, filename: str) -> bytes:
        """Read one of the six format files, rejecting links and other entries."""
        return self._file(run_id, filename).read_bytes()
