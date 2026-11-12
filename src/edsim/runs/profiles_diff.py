"""Key-by-key differences between the clinical profiles of two runs (task 5.5)."""

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass

from edsim.runs.results import RunReadError
from edsim.runs.store import RunStore

PROFILES_FILE = "perfiles.toml"


@dataclass(frozen=True, slots=True)
class ProfilesDifference:
    """A key of ``perfiles.toml`` whose value differs between two runs.

    Attributes:
        key: Dotted path of the value, such as ``motivos.disnea.peso_base``.
        a: Its value in the first file, or None if that file lacks the key.
        b: Its value in the second file, or None if that file lacks the key.
    """

    key: str
    a: object
    b: object


def _leaves(table: Mapping[str, object], prefix: str = "") -> dict[str, object]:
    """Flatten nested tables to dotted keys, in file order; arrays are values (tuples)."""
    found: dict[str, object] = {}
    for name, value in table.items():
        key = f"{prefix}{name}"
        if isinstance(value, Mapping):
            found.update(_leaves(value, f"{key}."))
        else:
            found[key] = _frozen(value)
    return found


def _frozen(value: object) -> object:
    return tuple(_frozen(item) for item in value) if isinstance(value, list) else value


def profiles_diff(
    a: Mapping[str, object], b: Mapping[str, object]
) -> tuple[ProfilesDifference, ...]:
    """The values that differ between two parsed ``perfiles.toml``, key by key.

    Tables are walked to their values, so a changed weight of one reason is one
    difference. The order is that of ``a``, then the keys only in ``b`` in
    their order. A key missing on one side has ``None`` there. Values compare
    exactly, as written: ``1`` and ``1.0`` are equal, as in Python.
    """
    left, right = _leaves(a), _leaves(b)
    keys = [*left, *(key for key in right if key not in left)]
    return tuple(
        ProfilesDifference(key, left.get(key), right.get(key))
        for key in keys
        if key not in left or key not in right or left[key] != right[key]
    )


def read_run_profiles_values(store: RunStore, run_id: str) -> dict[str, object]:
    """The parsed copy of ``perfiles.toml`` of a clinical run, for ``profiles_diff``.

    Raises:
        RunReadError: If the copy is missing (a provisional run) or is not TOML.
    """
    try:
        return tomllib.loads(store.read_file(run_id, PROFILES_FILE).decode("utf-8"))
    except (OSError, ValueError) as error:
        raise RunReadError(f"{store.root / run_id / PROFILES_FILE}: {error}") from error
