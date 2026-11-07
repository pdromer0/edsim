"""Center variants preserve text and publish without exposing partial drafts."""

import copy
import dataclasses
import errno
import random
import stat
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

import edsim.runs as runs
import edsim.runs.variants as variants
from edsim.runs import (
    MAX_VARIANT_NAME_LENGTH,
    center_diff,
    center_from_values,
    load_center,
    read_center_values,
    validate_center_values,
    validate_run_id,
    write_variant,
)

# Un centro con las doce claves (el bloque provisional y la sala de resultados), con
# comentarios: desde la tarea 4.9, config/centro.toml no tiene el bloque provisional,
# y estos tests prueban el formato de cualquier clave. Las variantes de un centro sin el
# bloque se prueban aparte, con config/centro.toml. La plantilla de médicos se lee del
# fichero: estos tests prueban el formato, no unos valores.
BASE = Path(__file__).parent / "data" / "centro_sala_ejemplo.toml"
MORNING, AFTERNOON, NIGHT = read_center_values(BASE)["recursos.medicos"]
DOCTORS_LINE = f"medicos = [{MORNING}, {AFTERNOON}, {NIGHT}]".encode()
MULTILINE_DOCTORS = (
    f"medicos = [\n  {MORNING}, # morning\n  {AFTERNOON}, # afternoon\n  {NIGHT}, # night\n]"
).encode()


@pytest.fixture
def values():
    return read_center_values(BASE)


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
@pytest.mark.parametrize("final_newline", [True, False])
def test_unchanged_variant_has_exact_base_bytes(tmp_path, newline, final_newline):
    content = BASE.read_bytes().replace(b"\n", newline)
    if not final_newline:
        content = content.removesuffix(newline)
    base = tmp_path / "base.toml"
    base.write_bytes(content)
    result = write_variant(base, read_center_values(base), tmp_path / "draft.toml")
    assert result.read_bytes() == content
    assert b"0.70" in result.read_bytes()


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_one_array_element_changes_without_losing_format_or_comments(tmp_path, newline):
    original = (
        BASE.read_bytes()
        .replace(
            DOCTORS_LINE,
            MULTILINE_DOCTORS,
        )
        .replace(b"\n", newline)
    )
    assert MULTILINE_DOCTORS.replace(b"\n", newline) in original  # el replace se aplicó
    base = tmp_path / "base.toml"
    base.write_bytes(original)
    values = read_center_values(base)
    values["recursos.medicos"][1] = 15
    destination = write_variant(base, values, tmp_path / "draft.toml")
    assert AFTERNOON != 15  # el cambio es de verdad
    assert destination.read_bytes() == original.replace(
        f"{AFTERNOON}, # afternoon".encode(), b"15, # afternoon"
    )
    assert read_center_values(destination) == values


def test_changing_one_probability_preserves_other_numeric_spellings(values, tmp_path):
    values["pruebas.probabilidad"][0] = 0.9
    destination = write_variant(BASE, values, tmp_path / "draft.toml")
    assert destination.read_bytes() == BASE.read_bytes().replace(b"[0.95,", b"[0.9,")


def random_values(rng, original):
    """Generate valid raw fields independently of the production validators."""
    values = copy.deepcopy(original)
    values["turnos.inicio"] = sorted(rng.sample(range(24), 3))
    values["recursos.enfermeria_triaje"] = [rng.randint(1, 20) for _ in range(3)]
    values["recursos.medicos"] = [rng.randint(1, 40) for _ in range(3)]
    values["recursos.boxes"] = rng.randint(1, 100)
    shares = [rng.choice([0, rng.uniform(0.1, 100)]) for _ in range(5)]
    shares[rng.randrange(5)] += 1
    values["triaje.reparto_niveles"] = shares
    for name in ("triaje", "valoracion", "reevaluacion", "respuesta_pruebas"):
        median = rng.uniform(0.1, 100)
        values[f"duraciones.{name}"] = [median, median + rng.uniform(0.1, 200)]
    for key in ("pruebas.probabilidad", "destino.probabilidad_ingreso"):
        values[key] = [rng.choice([0, 1, rng.random()]) for _ in range(5)]
    return values


def test_random_valid_centers_roundtrip(values, tmp_path):
    rng = random.Random(30401)
    zero_shares = boundary_probabilities = changed_centers = 0
    for index in range(100):
        candidate = random_values(rng, values)
        assert validate_center_values(candidate) == {}
        zero_shares += 0 in candidate["triaje.reparto_niveles"]
        boundary_probabilities += any(p in (0, 1) for p in candidate["pruebas.probabilidad"])
        changed_centers += candidate != values
        destination = write_variant(BASE, candidate, tmp_path / f"draft-{index}.toml")
        assert read_center_values(destination) == candidate
        assert load_center(destination) == center_from_values(candidate)
    assert zero_shares > 0 and boundary_probabilities > 0 and changed_centers == 100


def test_variant_name_reserves_a_64_bit_seed_suffix(values, tmp_path):
    assert MAX_VARIANT_NAME_LENGTH == 42
    name = "x" * MAX_VARIANT_NAME_LENGTH
    assert len(str(2**64 - 1)) == 20
    assert validate_run_id(name + "-r" + str(2**64 - 1))
    assert write_variant(BASE, values, tmp_path / f"{name}.toml").exists()
    with pytest.raises(ValueError, match="at most 42 characters"):
        write_variant(BASE, values, tmp_path / f"{name}x.toml")


@pytest.mark.parametrize("name", ["-bad.toml", "bad name.toml", "ñ.toml", "draft.txt"])
def test_invalid_names_are_rejected_without_writes(values, tmp_path, name):
    directory = tmp_path / "absent"
    with pytest.raises(ValueError):
        write_variant(BASE, values, directory / name)
    assert not directory.exists()


def test_invalid_values_never_create_a_directory(values, tmp_path):
    values["recursos.boxes"] = 0
    with pytest.raises(ValueError, match="recursos.boxes"):
        write_variant(BASE, values, tmp_path / "absent" / "draft.toml")
    assert list(tmp_path.iterdir()) == []


def test_existing_destination_is_untouched(values, tmp_path):
    destination = tmp_path / "draft.toml"
    original = b"foreign bytes\r\n"
    destination.write_bytes(original)
    with pytest.raises(FileExistsError):
        write_variant(BASE, values, destination)
    assert destination.read_bytes() == original
    assert list(tmp_path.iterdir()) == [destination]


def test_racing_writer_keeps_its_file(values, tmp_path, monkeypatch):
    destination = tmp_path / "draft.toml"
    original_publish = variants._publish_variant
    calls = []

    def race(temporary, path, overwrite):
        calls.append(temporary)
        assert temporary.read_bytes() == BASE.read_bytes()
        assert not destination.exists()
        destination.write_bytes(b"another writer")
        original_publish(temporary, path, overwrite)

    monkeypatch.setattr(variants, "_publish_variant", race)
    with pytest.raises(FileExistsError):
        write_variant(BASE, values, destination)
    assert len(calls) == 1
    assert destination.read_bytes() == b"another writer"
    assert list(tmp_path.iterdir()) == [destination]


@pytest.mark.parametrize("overwrite", [False, True])
def test_temporary_is_hidden_and_not_listed_as_toml(values, tmp_path, monkeypatch, overwrite):
    destination = tmp_path / "draft.toml"
    if overwrite:
        destination.write_bytes(b"old bytes")
    original_publish = variants._publish_variant
    calls = []

    def inspect(temporary, path, replacing):
        calls.append(temporary)
        assert temporary.name.startswith(".")
        assert not temporary.name.endswith(".toml")
        assert set(tmp_path.glob("*.toml")) == ({destination} if overwrite else set())
        assert temporary.read_bytes() == BASE.read_bytes()
        original_publish(temporary, path, replacing)

    monkeypatch.setattr(variants, "_publish_variant", inspect)
    assert write_variant(BASE, values, destination, overwrite=overwrite) == destination
    assert len(calls) == 1
    assert destination.read_bytes() == BASE.read_bytes()
    assert list(tmp_path.iterdir()) == [destination]


@pytest.mark.parametrize("mask", [0o002, 0o022, 0o027, 0o077])
@pytest.mark.parametrize("overwrite", [False, True])
def test_published_mode_matches_open_in_same_directory(tmp_path, mask, overwrite):
    # Isolate umask changes in a subprocess: production never reads it by changing it.
    script = dedent("""\
        import os
        import stat
        import sys
        from pathlib import Path
        from edsim.runs import read_center_values, write_variant

        base, directory = map(Path, sys.argv[1:3])
        os.umask(int(sys.argv[3]))
        overwrite = sys.argv[4] == "True"
        reference = directory / "reference"
        with reference.open("wb") as file:
            file.write(b"reference")
        destination = directory / "draft.toml"
        if overwrite:
            destination.write_bytes(b"old bytes")
            destination.chmod(0o400)
        write_variant(base, read_center_values(base), destination, overwrite=overwrite)
        expected = stat.S_IMODE(reference.stat().st_mode)
        actual = stat.S_IMODE(destination.stat().st_mode)
        assert actual == expected, (oct(actual), oct(expected))
    """)
    result = subprocess.run(
        [sys.executable, "-c", script, str(BASE), str(tmp_path), str(mask), str(overwrite)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert stat.S_IMODE((tmp_path / "draft.toml").stat().st_mode) == 0o666 & ~mask
    assert {p.name for p in tmp_path.iterdir()} == {"draft.toml", "reference"}


@pytest.mark.parametrize("stage", ["write", "permissions", "publish"])
@pytest.mark.parametrize("error_type", [OSError, KeyboardInterrupt])
def test_failure_cleans_all_temporaries(values, tmp_path, monkeypatch, stage, error_type):
    error = error_type("injected failure")
    calls = []

    def fail(*args, **kwargs):
        calls.append(True)
        raise error

    if stage == "publish":
        monkeypatch.setattr(variants, "_publish_variant", fail)
    elif stage == "permissions":
        monkeypatch.setattr(variants.os, "fchmod", fail)
    else:
        original_fdopen = variants.os.fdopen

        class FailingFile:
            def __init__(self, descriptor, mode):
                self.file = original_fdopen(descriptor, mode)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.file.close()

            def fileno(self):
                return self.file.fileno()

            write = staticmethod(fail)

        monkeypatch.setattr(variants.os, "fdopen", FailingFile)
    with pytest.raises(error_type) as caught:
        write_variant(BASE, values, tmp_path / "draft.toml")
    assert caught.value is error
    assert calls == [True]
    assert list(tmp_path.iterdir()) == []


def test_unsupported_hard_links_propagate_without_fallback(values, tmp_path, monkeypatch):
    error = OSError(errno.EOPNOTSUPP, "hard links unavailable")

    def fail(*args):
        raise error

    monkeypatch.setattr(variants.os, "link", fail)
    with pytest.raises(OSError) as caught:
        write_variant(BASE, values, tmp_path / "draft.toml")
    assert caught.value is error
    assert list(tmp_path.iterdir()) == []


def test_diff_normalizes_percentages_and_fractions(values):
    values["triaje.reparto_niveles"][-1] = 0
    before = center_from_values(values)
    values["triaje.reparto_niveles"] = [x * 0.01 for x in values["triaje.reparto_niveles"]]
    after = center_from_values(values)
    assert before.level_shares != after.level_shares  # Rounding really occurs.
    assert center_diff(before, after) == ()


def test_diff_order_values_and_small_real_changes(values):
    before = center_from_values(values)
    more = (MORNING + 1, AFTERNOON, NIGHT)
    after = dataclasses.replace(before, boxes=31, doctors=more, triage_time=(5, 11))
    changes = center_diff(before, after)
    assert [(d.key, d.before, d.after) for d in changes] == [
        ("recursos.medicos", (MORNING, AFTERNOON, NIGHT), more),
        ("recursos.boxes", 30, 31),
        ("duraciones.triaje", (5.0, 10.0), (5.0, 11.0)),
    ]
    assert center_diff(before, before) == ()
    shares = list(before.level_shares)
    shares[0] += 1e-14
    shares[1] -= 1e-14
    assert [
        d.key for d in center_diff(before, dataclasses.replace(before, level_shares=shares))
    ] == ["triaje.reparto_niveles"]
    probabilities = list(before.test_probability)
    probabilities[0] -= 1e-15
    assert (
        len(center_diff(before, dataclasses.replace(before, test_probability=probabilities))) == 1
    )


def test_variant_api_is_public():
    for name in ("MAX_VARIANT_NAME_LENGTH", "CenterDifference", "center_diff", "write_variant"):
        assert name in runs.__all__
        assert getattr(runs, name) is not None


def test_list_variants_filters_names_and_types_without_reading_contents(tmp_path):
    from edsim.runs import list_variants

    for name in (
        "z.toml",
        "A.toml",
        "a-2.toml",
        "x" * 42 + ".toml",
        ".hidden.toml",
        "-bad.toml",
        "ñ.toml",
        "space name.toml",
        "x" * 43 + ".toml",
        "draft.tmp",
        "draft.toml~",
        "upper.TOML",
    ):
        (tmp_path / name).write_text("contents deliberately not valid TOML")
    (tmp_path / "directory.toml").mkdir()
    (tmp_path / "linked.toml").symlink_to(tmp_path / "A.toml")
    (tmp_path / "missing.toml").symlink_to(tmp_path / "absent")
    assert [p.name for p in list_variants(tmp_path)] == [
        "A.toml",
        "a-2.toml",
        "x" * 42 + ".toml",
        "z.toml",
    ]
    assert list_variants(tmp_path / "not-created") == ()
    assert "list_variants" in runs.__all__


# --- Clave opcional espera_resultados_fuera (tarea 4.6a) ------------------------------

EJEMPLO = Path(__file__).parent / "data" / "centro_ejemplo.toml"


def test_variante_de_una_base_sin_la_clave(tmp_path):
    # El centro de ejemplo no la lleva: la variante se escribe sin añadirla.
    values = read_center_values(EJEMPLO)
    values["recursos.medicos"][1] = 15
    destination = write_variant(EJEMPLO, values, tmp_path / "draft.toml")
    assert b"espera_resultados_fuera" not in destination.read_bytes()
    assert load_center(destination).results_wait_outside == ()


def test_variante_de_la_base_conserva_la_clave(values, tmp_path):
    values["recursos.medicos"][1] = 15
    destination = write_variant(BASE, values, tmp_path / "draft.toml")
    assert b"espera_resultados_fuera = [4, 5]" in destination.read_bytes()
    assert load_center(destination).results_wait_outside == (4, 5)


def test_una_variante_no_anade_ni_quita_la_clave(values, tmp_path):
    del values["recursos.espera_resultados_fuera"]
    with pytest.raises(ValueError, match="in both the base and the values, or in neither"):
        write_variant(BASE, values, tmp_path / "draft.toml")
    assert list(tmp_path.iterdir()) == []


def test_diferencia_en_la_clave(values):
    before = center_from_values(values)
    after = dataclasses.replace(before, results_wait_outside=(5,))
    assert [(d.key, d.before, d.after) for d in center_diff(before, after)] == [
        ("recursos.espera_resultados_fuera", (4, 5), (5,))
    ]


# --- Listas de longitud variable: espera_resultados_fuera (revisión del PR #46) ------

WAIT = "recursos.espera_resultados_fuera"
COMMENT = "  # niveles que esperan los resultados fuera del box"


@pytest.fixture
def base_with_comment(tmp_path):
    """El centro base con un comentario en la línea de la clave, que debe conservarse."""
    text = BASE.read_text(encoding="utf-8")
    line = "espera_resultados_fuera = [4, 5]\n"
    assert text.count(line) == 1
    base = tmp_path / "base.toml"
    base.write_text(text.replace(line, line.rstrip("\n") + COMMENT + "\n"), encoding="utf-8")
    return base


@pytest.mark.parametrize("levels", [[], [5], [2, 4, 5]])
def test_cambiar_la_longitud_de_la_lista(base_with_comment, tmp_path, levels):
    # Con otra longitud se sustituye el array entero: antes, [] dejaba [4, 5] en silencio,
    # [5] escribía [5, 5] y [2, 4, 5] daba IndexError.
    values = read_center_values(base_with_comment)
    values[WAIT] = list(levels)
    destination = write_variant(base_with_comment, values, tmp_path / "draft.toml")

    written = read_center_values(destination)
    assert written[WAIT] == levels
    assert center_from_values(written).results_wait_outside == tuple(levels)
    assert {k: v for k, v in written.items() if k != WAIT} == {
        k: v for k, v in values.items() if k != WAIT
    }


def test_misma_longitud_se_edita_elemento_a_elemento(base_with_comment, tmp_path):
    # [4, 5] → [3, 5]: la misma longitud conserva el comentario de la línea.
    values = read_center_values(base_with_comment)
    values[WAIT] = [3, 5]
    destination = write_variant(base_with_comment, values, tmp_path / "draft.toml")

    text = destination.read_text(encoding="utf-8")
    assert "espera_resultados_fuera = [3, 5]" + COMMENT + "\n" in text
    assert read_center_values(destination)[WAIT] == [3, 5]


def test_la_red_de_seguridad_no_deja_escribir_otro_valor(values, tmp_path, monkeypatch):
    # Si la escritura con tomlkit perdiera un cambio, la relectura lo ve: ValueError y
    # ningún fichero, en lugar de una variante que no es la pedida.
    values["recursos.medicos"][1] = 15
    monkeypatch.setattr(variants.tomlkit, "dumps", lambda document: BASE.read_text("utf-8"))
    written = rf"would write recursos\.medicos = \[{MORNING}, {AFTERNOON}, {NIGHT}\]"
    with pytest.raises(ValueError, match=written):
        write_variant(BASE, values, tmp_path / "draft.toml")
    assert list(tmp_path.iterdir()) == []


# --- Centros con y sin el bloque provisional (tarea 4.9) ------------------------------


def test_diferencias_entre_un_centro_con_bloque_y_otro_sin_el():
    # Seis diferencias, con None en el lado sin bloque, y sin excepción (antes, el
    # reparto de niveles hacía zip con None).
    with_block = load_center(Path(__file__).parent / "data" / "centro_ejemplo.toml")
    fields = (
        "level_shares",
        "triage_time",
        "assessment_time",
        "reassessment_time",
        "test_turnaround",
        "test_probability",
    )
    without = dataclasses.replace(with_block, **dict.fromkeys(fields))

    changes = center_diff(with_block, without)
    assert [d.key for d in changes] == [
        "triaje.reparto_niveles",
        "duraciones.triaje",
        "duraciones.valoracion",
        "duraciones.reevaluacion",
        "duraciones.respuesta_pruebas",
        "pruebas.probabilidad",
    ]
    assert all(d.after is None and d.before is not None for d in changes)
    assert [(d.before, d.after) for d in center_diff(without, with_block)] == [
        (None, d.before) for d in changes
    ]
    assert center_diff(without, without) == ()
