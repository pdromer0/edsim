"""``[camas]`` en el centro y ``[destino]`` opcional (tarea 5.2, decisión 72).

Un centro lleva ``[destino]`` (modelos provisional y del hito 4) o ``[camas]`` (hito 5),
nunca los dos; sin ninguno, el error dice qué falta para qué modelo. Los lectores de
``destino.probabilidad_ingreso`` fallan con un error claro ante un centro con ``[camas]``,
no con un TypeError al hacer zip con None.
"""

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from edsim.engine.center import (
    BOTH_DESTINATION_AND_BEDS,
    DESTINATION_KEY,
    MISSING_DESTINATION,
    center_from_values,
    load_center,
    read_center_values,
    require_destination,
    validate_center_values,
)
from edsim.engine.clinical import ProvisionalSampler
from edsim.engine.clinical_sampler import N_SAMPLER_STREAMS, ClinicalSampler, ModelChoiceError
from edsim.profiles.config import load_profiles
from edsim.runs import summarize_center
from edsim.seeds import child_streams

DATA = Path(__file__).parent / "data"
BEDS = (
    "[camas]\n"
    "espera = [240, 720]\n"
    "factor_turno = [0.8, 1.0, 1.5]\n"
    "factor_estacion = [1.2, 1.0, 0.9, 1.0]\n"
)
NEEDS_DESTINATION = r"need \[destino\] of the center .*this one has \[camas\]"


def example_text() -> str:
    return (DATA / "centro_ejemplo.toml").read_text(encoding="utf-8")


def without_destination(text: str) -> str:
    """El centro de ejemplo sin [destino], la última tabla del fichero."""
    return text[: text.index("[destino]")]


def write(tmp_path, text: str) -> Path:
    path = tmp_path / "centro.toml"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def beds_path(tmp_path):
    return write(tmp_path, without_destination(example_text()) + BEDS)


@pytest.fixture
def beds_center(beds_path):
    return load_center(beds_path)


def test_un_centro_con_camas_se_lee(beds_center):
    assert beds_center.has_beds
    assert beds_center.admission_probability is None
    assert beds_center.bed_wait == (240.0, 720.0)
    assert beds_center.bed_shift_factors == (0.8, 1.0, 1.5)
    assert beds_center.bed_season_factors == (1.2, 1.0, 0.9, 1.0)


def test_el_factor_de_estacion_es_opcional_y_vale_uno(tmp_path):
    text = without_destination(example_text()) + BEDS.replace(
        "factor_estacion = [1.2, 1.0, 0.9, 1.0]\n", ""
    )
    assert load_center(write(tmp_path, text)).bed_season_factors == (1.0, 1.0, 1.0, 1.0)


def test_un_centro_de_siempre_no_tiene_camas():
    center = load_center(DATA / "centro_ejemplo.toml")
    assert not center.has_beds
    assert center.bed_wait is None and center.bed_shift_factors is None
    assert center.bed_season_factors is None
    assert center.admission_probability == (0.80, 0.45, 0.15, 0.04, 0.01)


def test_destino_y_camas_a_la_vez_es_un_error(tmp_path):
    path = write(tmp_path, example_text() + BEDS)
    with pytest.raises(ValueError) as caught:
        load_center(path)
    assert str(caught.value) == f"{path}: {BOTH_DESTINATION_AND_BEDS}"
    errors = validate_center_values(read_center_values(path))
    assert errors == {DESTINATION_KEY: BOTH_DESTINATION_AND_BEDS}


def test_sin_destino_ni_camas_el_error_dice_que_falta_para_que_modelo(tmp_path):
    path = write(tmp_path, without_destination(example_text()))
    with pytest.raises(ValueError) as caught:
        load_center(path)
    assert str(caught.value) == (
        f"{path}: missing keys: destino (provisional and milestone 4 models) or camas "
        "(milestone 5 model)"
    )
    assert validate_center_values(read_center_values(path)) == {
        DESTINATION_KEY: MISSING_DESTINATION
    }


def test_camas_vacia_cuenta_como_ausente(tmp_path):
    path = write(tmp_path, without_destination(example_text()) + "[camas]\n")
    assert validate_center_values(read_center_values(path)) == {
        DESTINATION_KEY: MISSING_DESTINATION
    }


@pytest.mark.parametrize("key", ["espera", "factor_turno"])
def test_camas_a_medias(tmp_path, key):
    lines = [line for line in BEDS.splitlines() if not line.startswith(key)]
    path = write(tmp_path, without_destination(example_text()) + "\n".join(lines) + "\n")
    with pytest.raises(ValueError, match=rf"missing keys: camas\.{key}$"):
        load_center(path)
    assert validate_center_values(read_center_values(path)) == {
        f"camas.{key}": f"missing keys: camas.{key}"
    }


def test_una_clave_desconocida_en_camas(tmp_path):
    path = write(tmp_path, without_destination(example_text()) + BEDS + "esperaa = 3\n")
    with pytest.raises(ValueError, match=r"unknown keys: camas\.esperaa"):
        load_center(path)


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("camas.espera", [720, 240], r"camas\.espera: p90 must be greater than the median"),
        ("camas.espera", [0, 720], r"camas\.espera\[0\] \(median\) must be positive"),
        ("camas.espera", [240, float("inf")], r"camas\.espera\[1\] must be a finite number"),
        ("camas.espera", [240, 10**400], r"camas\.espera\[1\] must be a finite number"),
        ("camas.espera", [240], r"camas\.espera must have 2 values"),
        ("camas.factor_turno", [0.8, 1.0], r"camas\.factor_turno must have 3 values"),
        ("camas.factor_turno", [0.8, 0, 1.5], r"camas\.factor_turno\[1\] must be positive"),
        ("camas.factor_turno", [0.8, float("nan"), 1.5], r"factor_turno\[1\] must be a finite"),
        ("camas.factor_estacion", [1, 1, 1, 1, 1], r"factor_estacion must have 4 values"),
        ("camas.factor_estacion", [1, 1, 1, -1], r"factor_estacion\[3\] must be positive"),
    ],
)
def test_valores_no_validos_de_camas(beds_path, key, value, message):
    values = read_center_values(beds_path) | {key: value}
    with pytest.raises(ValueError, match=message):
        center_from_values(values)
    assert key in validate_center_values(values)


def test_replace_respeta_las_reglas(beds_center):
    with pytest.raises(ValueError, match=r"\[destino\] .* or \[camas\] .* not both"):
        replace(beds_center, admission_probability=(0.8, 0.45, 0.15, 0.04, 0.01))
    with pytest.raises(ValueError, match=r"^missing keys: destino\.probabilidad_ingreso"):
        replace(beds_center, bed_wait=None, bed_shift_factors=None, bed_season_factors=None)
    with pytest.raises(ValueError, match=r"^missing keys: camas\.factor_turno$"):
        replace(beds_center, bed_shift_factors=None)


# Los lectores de destino.probabilidad_ingreso (nota 4 del issue #69).


def test_require_destination(beds_center):
    require_destination(load_center(DATA / "centro_ejemplo.toml"))
    with pytest.raises(ValueError, match=NEEDS_DESTINATION):
        require_destination(beds_center)


def test_el_muestreador_provisional_pide_destino(beds_center):
    with pytest.raises(ValueError, match=NEEDS_DESTINATION):
        ProvisionalSampler(beds_center, child_streams(1, 4))


def test_el_muestreador_del_hito_4_pide_destino(beds_center):
    # Desde la 5.3, el muestreador elige el modelo con choose_model: perfiles del hito 4
    # con un centro con [camas] es un bloque a medias entre los dos ficheros, y el error
    # dice qué falta en los perfiles.
    profiles = load_profiles(DATA / "perfiles_ejemplo.toml")
    with pytest.raises(ModelChoiceError, match=r"missing \[abandono\].*has \[camas\]"):
        ClinicalSampler(
            profiles, date(2026, 1, 1), beds_center, child_streams(1, N_SAMPLER_STREAMS)
        )


def test_el_resumen_del_centro_pide_destino(beds_path):
    with pytest.raises(ValueError, match=NEEDS_DESTINATION):
        summarize_center(read_center_values(beds_path))
