"""Comment-preserving center drafts and normalized center differences."""

import math
import os
import stat
import tempfile
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import tomlkit

from edsim.engine.center import _KEYS, CenterConfig, _flatten_center_data, center_from_values
from edsim.runs.identifiers import validate_run_id

# Reserve '-r' and the 20 decimal digits of the largest unsigned 64-bit seed.
MAX_VARIANT_NAME_LENGTH = 64 - len("-r") - 20


def list_variants(root: str | Path) -> tuple[Path, ...]:
    """List regular, non-hidden variant files in stable name order.

    Only names are checked; contents are validated when the user opens them.
    Missing directories are empty catalogs. Other filesystem errors propagate.
    """
    root = Path(root)
    if not root.exists():
        return ()
    result = []
    for path in sorted(root.iterdir()):
        if path.is_symlink() or not path.is_file() or path.suffix != ".toml":
            continue
        try:
            validate_run_id(path.stem)
        except ValueError:
            continue
        if len(path.stem) <= MAX_VARIANT_NAME_LENGTH:
            result.append(path)
    return tuple(result)


@dataclass(frozen=True, slots=True)
class CenterDifference:
    """One changed TOML key and its normalized values, before and after."""

    key: str
    before: int | float | tuple[int | float, ...]
    after: int | float | tuple[int | float, ...]


def center_diff(a: CenterConfig, b: CenterConfig) -> tuple[CenterDifference, ...]:
    """Return normalized differences in TOML order.

    Only shares undergo arithmetic during normalization. An absolute tolerance
    of 1e-15 (about five float64 epsilons on [0, 1]) absorbs roundoff from
    percentage/fraction conversions; other fields are compared exactly.
    """
    differences = []
    for key, field in _KEYS.items():
        before, after = getattr(a, field), getattr(b, field)
        equal = before == after
        if field == "level_shares":
            equal = all(
                math.isclose(x, y, rel_tol=0, abs_tol=1e-15)
                for x, y in zip(before, after, strict=True)
            )
        if not equal:
            differences.append(CenterDifference(key, before, after))
    return tuple(differences)


def _variant_bytes(base: Path, values: Mapping[str, object]) -> bytes:
    center_from_values(values)
    source = base.read_bytes()
    text = source.decode("utf-8")
    original = _flatten_center_data(tomllib.loads(text))
    center_from_values(original)
    document = tomlkit.parse(text)
    changed = False
    for key in _KEYS:
        value = values[key]
        if original[key] != value:
            section, name = key.split(".")
            if isinstance(value, list | tuple):
                # Fixed-length arrays: editing elements retains their comments,
                # spacing and the spelling of every unchanged numeric element.
                for index, item in enumerate(value):
                    if original[key][index] != item:
                        document[section][name][index] = item
            else:
                document[section][name] = value
            changed = True
    return tomlkit.dumps(document).encode("utf-8") if changed else source


def _publish_variant(temporary: Path, path: Path, overwrite: bool) -> None:
    """Publish a complete file; hard links give atomic no-clobber creation."""
    if overwrite:
        os.replace(temporary, path)
    else:
        os.link(temporary, path)


def write_variant(
    base: str | Path,
    values: Mapping[str, object],
    path: str | Path,
    *,
    overwrite: bool = False,
) -> Path:
    """Validate and atomically publish a comment-preserving center variant.

    The destination must end in ``.toml`` and its stem follows ``run_id``'s
    rule, shortened to ``MAX_VARIANT_NAME_LENGTH`` to reserve a seed suffix.
    With no raw value changes the output is byte-for-byte identical to base.

    Hidden temporary files never end in ``.toml``. The published mode is that
    of a normal ``open()`` in the destination directory, including on overwrite;
    the process-wide umask is never changed. ``overwrite=False`` uses a hard
    link and raises ``FileExistsError`` even if another writer wins a race.
    Other link errors propagate without a fallback. All owned temporary files
    are removed on failures, including ``KeyboardInterrupt``.
    """
    path = Path(path)
    if path.suffix != ".toml":
        raise ValueError("variant path must end in .toml")
    validate_run_id(path.stem)
    if len(path.stem) > MAX_VARIANT_NAME_LENGTH:
        raise ValueError(f"variant name must contain at most {MAX_VARIANT_NAME_LENGTH} characters")
    content = _variant_bytes(Path(base), values)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    reference = temporary.with_name(temporary.name + ".permissions")
    reference_owned = False
    try:
        with os.fdopen(descriptor, "wb") as file:
            # Observe normal open() permissions without touching the global umask.
            with reference.open("xb") as permissions:
                reference_owned = True
                mode = stat.S_IMODE(os.fstat(permissions.fileno()).st_mode)
            reference.unlink()
            reference_owned = False
            os.fchmod(file.fileno(), mode)
            file.write(content)
        _publish_variant(temporary, path, overwrite)
    finally:
        temporary.unlink(missing_ok=True)
        if reference_owned:
            reference.unlink(missing_ok=True)
    return path
